# Copyright (c) 2026, Isoft and contributors
# For license information, please see license.txt
"""Credit Note Register: every credit note beside the invoice it credits.

One row per credit note (Sales Invoice with is_return = 1), with its own net
total, taxes and grand total, then the same figures and the posting date of the
invoice in `return_against`, and how much of that invoice has been credited so
far across all its credit notes. A credit note issued without a reference still
appears, with the invoice columns empty.
"""
import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns(filters)
	data = get_data(filters)
	return columns, data


def get_columns(filters):
	columns = [
		{"label": _("Credit Note"), "fieldname": "name", "fieldtype": "Link", "options": "Sales Invoice", "width": 200},
		{"label": _("Posting Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 160},
		{"label": _("Customer Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 180},
		{"label": _("Net Total"), "fieldname": "net_total", "fieldtype": "Currency", "options": "currency", "width": 130},
		{"label": _("Taxes"), "fieldname": "taxes", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("Grand Total"), "fieldname": "grand_total", "fieldtype": "Currency", "options": "currency", "width": 130},
		{"label": _("Return Against"), "fieldname": "return_against", "fieldtype": "Link", "options": "Sales Invoice", "width": 200},
		{"label": _("Invoice Date"), "fieldname": "invoice_date", "fieldtype": "Date", "width": 100},
		{"label": _("Invoice Net Total"), "fieldname": "invoice_net_total", "fieldtype": "Currency", "options": "currency", "width": 130},
		{"label": _("Invoice Taxes"), "fieldname": "invoice_taxes", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("Invoice Grand Total"), "fieldname": "invoice_grand_total", "fieldtype": "Currency", "options": "currency", "width": 130},
		{"label": _("Credited So Far"), "fieldname": "credited_so_far", "fieldtype": "Currency", "options": "currency", "width": 130},
		{"label": _("Credited %"), "fieldname": "credited_percent", "fieldtype": "Percent", "width": 90},
	]
	if frappe.get_meta("Sales Invoice").has_field("return_reason"):
		columns.append({"label": _("Reason"), "fieldname": "return_reason", "fieldtype": "Data", "width": 220})
	if filters.get("include_cancelled"):
		columns.insert(1, {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90})
	columns.append({"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 80, "hidden": 1})
	return columns


def get_conditions(filters):
	conditions = ["cn.is_return = 1"]
	values = {}

	if filters.get("include_cancelled"):
		conditions.append("cn.docstatus in (1, 2)")
	else:
		conditions.append("cn.docstatus = 1")

	for field in ("company", "customer", "return_against"):
		if filters.get(field):
			conditions.append(f"cn.{field} = %({field})s")
			values[field] = filters[field]

	if filters.get("from_date"):
		conditions.append("cn.posting_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("cn.posting_date <= %(to_date)s")
		values["to_date"] = filters.to_date

	return " and ".join(conditions), values


def get_data(filters):
	where, values = get_conditions(filters)
	has_reason = frappe.get_meta("Sales Invoice").has_field("return_reason")
	reason = ", cn.return_reason" if has_reason else ""

	rows = frappe.db.sql(
		f"""
		select
			cn.name, cn.posting_date, cn.customer, cn.customer_name, cn.currency, cn.docstatus,
			cn.net_total, cn.total_taxes_and_charges as taxes, cn.grand_total,
			cn.return_against,
			inv.posting_date as invoice_date,
			inv.net_total as invoice_net_total,
			inv.total_taxes_and_charges as invoice_taxes,
			inv.grand_total as invoice_grand_total
			{reason}
		from `tabSales Invoice` cn
		left join `tabSales Invoice` inv on inv.name = cn.return_against
		where {where}
		order by cn.posting_date desc, cn.name desc
		""",
		values,
		as_dict=True,
	)

	# Everything credited against each referenced invoice, not only the rows on
	# screen: an invoice may have older credit notes outside the date filter.
	invoices = list({r.return_against for r in rows if r.return_against})
	credited = {}
	if invoices:
		for r in frappe.db.sql(
			"""
			select return_against, sum(grand_total) as total
			from `tabSales Invoice`
			where is_return = 1 and docstatus = 1 and return_against in %(invoices)s
			group by return_against
			""",
			{"invoices": invoices},
			as_dict=True,
		):
			credited[r.return_against] = -flt(r.total)

	for r in rows:
		r.status = _("Cancelled") if r.docstatus == 2 else _("Submitted")
		if r.return_against:
			r.credited_so_far = credited.get(r.return_against, 0)
			if flt(r.invoice_grand_total):
				r.credited_percent = flt(r.credited_so_far) / flt(r.invoice_grand_total) * 100
		else:
			r.credited_so_far = None
			r.credited_percent = None
			r.invoice_net_total = r.invoice_taxes = r.invoice_grand_total = None

	# Own total row: Frappe's would also add up the invoice columns, which repeat
	# the same invoice on every one of its credit notes.
	if rows:
		rows.append(
			{
				"name": _("Total"),
				"currency": rows[0].currency,
				"net_total": sum(flt(r.net_total) for r in rows if r.docstatus == 1),
				"taxes": sum(flt(r.taxes) for r in rows if r.docstatus == 1),
				"grand_total": sum(flt(r.grand_total) for r in rows if r.docstatus == 1),
				"bold": 1,
			}
		)

	return rows
