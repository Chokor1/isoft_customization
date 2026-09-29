"""Credit Note Assistant: server side of the /app/credit-note-assistant desk page.

A customer sends a list of items and quantities to be credited, without saying which
invoices they came from. The page lists the customer's submitted invoices that still
have returnable quantity for those items, the user picks one, and a credit note is
opened pre-filled with just those lines and quantities.

One credit note always points at one invoice. ERPNext's return validation, the GL
allocation (against_voucher = return_against) and the AGT payload (every line carries
``return_against`` plus the original line number from ``sales_invoice_item``) all assume
it, so a list spread over several invoices becomes several credit notes, one per
invoice, made one after the other from the page.

Returned quantity per original line comes from submitted credit notes whose rows link
back through ``sales_invoice_item``. Returns without that link (older or hand-made) are
counted per item code and consumed from the item's lines in line order, which matches
ERPNext's own check in ``validate_quantity`` (per item code, per invoice).

The credit note is built by ERPNext's ``make_sales_return`` limited to the chosen lines
(``frappe.flags.selected_children``), then quantities are set. It is returned unsaved:
saft_xml submits a credit note on its first save, so the form is the last place to
review it before it reaches AGT.
"""
from __future__ import unicode_literals

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, now

MAX_INVOICES = 300


def _parse(value):
	if isinstance(value, str):
		return json.loads(value) if value else None
	return value


def _requested_items(items):
	"""[{item_code, qty}] from the client -> ordered {item_code: qty}, duplicates summed."""
	requested = {}
	for row in _parse(items) or []:
		code = (row.get("item_code") or "").strip()
		qty = flt(row.get("qty"))
		if not code:
			continue
		if qty <= 0:
			frappe.throw(_("Quantity for Item {0} must be greater than zero.").format(frappe.bold(code)))
		requested[code] = requested.get(code, 0) + qty
	if not requested:
		frappe.throw(_("Add at least one item with a quantity."))
	return requested


def _check_read():
	if not frappe.has_permission("Sales Invoice", "read"):
		frappe.throw(_("Not permitted to read Sales Invoices."), frappe.PermissionError)


def get_invoice_lines(invoice_names, item_codes):
	"""Lines of *invoice_names* for *item_codes*, each with sold / returned / returnable qty."""
	if not invoice_names or not item_codes:
		return []

	lines = frappe.db.sql(
		"""
		select name as row, parent as invoice, idx, item_code, item_name, uom, qty,
			conversion_factor, rate, net_rate, amount, batch_no,
			ifnull(serial_no, '') != '' as has_serial_no
		from `tabSales Invoice Item`
		where parent in %(invoices)s and item_code in %(items)s and qty > 0
		order by parent, idx
		""",
		{"invoices": tuple(invoice_names), "items": tuple(item_codes)},
		as_dict=True,
	)

	returned_by_row = dict(
		frappe.db.sql(
			"""
			select r.sales_invoice_item, sum(abs(r.qty))
			from `tabSales Invoice Item` r
			join `tabSales Invoice` p on p.name = r.parent
			where p.docstatus = 1 and p.is_return = 1 and p.return_against in %(invoices)s
				and ifnull(r.sales_invoice_item, '') != ''
			group by r.sales_invoice_item
			""",
			{"invoices": tuple(invoice_names)},
		)
	)
	unlinked = {}
	for invoice, item_code, qty in frappe.db.sql(
		"""
		select p.return_against, r.item_code, sum(abs(r.qty))
		from `tabSales Invoice Item` r
		join `tabSales Invoice` p on p.name = r.parent
		where p.docstatus = 1 and p.is_return = 1 and p.return_against in %(invoices)s
			and ifnull(r.sales_invoice_item, '') = ''
		group by p.return_against, r.item_code
		""",
		{"invoices": tuple(invoice_names)},
	):
		unlinked[(invoice, item_code)] = flt(qty)

	for line in lines:
		returned = flt(returned_by_row.get(line.row))
		left = flt(line.qty) - returned
		key = (line.invoice, line.item_code)
		if unlinked.get(key) and left > 0:
			take = min(left, unlinked[key])
			unlinked[key] -= take
			returned += take
		line.returned = returned
		line.returnable = max(flt(line.qty) - returned, 0)
		line.has_serial_no = cint(line.has_serial_no)
	return lines


def get_creditable_items(company, customer, from_date=None, to_date=None, txt=None, exact=None, start=0, page_len=20):
	"""Items the customer bought (submitted invoices of *company*, optionally within the
	dates) that still have quantity left to credit.

	Credited quantity is taken per invoice and item, and clamped at zero there, so an
	over-credit on one invoice never hides quantity still open on another.
	"""
	values = {"company": company, "customer": customer, "start": cint(start), "page_len": cint(page_len) or 20}
	conditions = ""
	if from_date:
		conditions += " and si.posting_date >= %(from_date)s"
		values["from_date"] = getdate(from_date)
	if to_date:
		conditions += " and si.posting_date <= %(to_date)s"
		values["to_date"] = getdate(to_date)
	item_filter = ""
	if exact:
		item_filter = " and t.item_code = %(exact)s"
		values["exact"] = exact
	elif txt:
		item_filter = " and (t.item_code like %(txt)s or i.item_name like %(txt)s)"
		values["txt"] = "%{0}%".format(txt)

	return frappe.db.sql(
		"""
		select t.item_code, i.item_name,
			sum(greatest(t.sold - ifnull(r.credited, 0), 0)) as creditable,
			sum(case when t.sold - ifnull(r.credited, 0) > 0 then 1 else 0 end) as invoices
		from (
			select sii.parent, sii.item_code, sum(sii.qty) as sold
			from `tabSales Invoice Item` sii
			join `tabSales Invoice` si on si.name = sii.parent
			where si.company = %(company)s and si.customer = %(customer)s
				and si.docstatus = 1 and si.is_return = 0 and sii.qty > 0 {0}
			group by sii.parent, sii.item_code
		) t
		left join (
			select p.return_against, ri.item_code, sum(abs(ri.qty)) as credited
			from `tabSales Invoice Item` ri
			join `tabSales Invoice` p on p.name = ri.parent
			where p.company = %(company)s and p.customer = %(customer)s
				and p.docstatus = 1 and p.is_return = 1
			group by p.return_against, ri.item_code
		) r on r.return_against = t.parent and r.item_code = t.item_code
		join `tabItem` i on i.name = t.item_code
		where 1 = 1 {1}
		group by t.item_code, i.item_name
		having creditable > 0
		order by t.item_code
		limit %(start)s, %(page_len)s
		""".format(conditions, item_filter),
		values,
		as_dict=True,
	)


@frappe.whitelist()
def search_items(company, customer, txt=None, from_date=None, to_date=None):
	"""Suggestions for the page's item search: only items this customer can still credit."""
	_check_read()
	if not (company and customer):
		return []
	return get_creditable_items(company, customer, from_date, to_date, txt=(txt or "").strip() or None, page_len=50)


@frappe.whitelist()
def get_creditable_item(company, customer, item_code, from_date=None, to_date=None):
	"""{item_code, item_name, creditable, invoices} for one item, or None when there is
	nothing left to credit on it for this customer and dates."""
	_check_read()
	rows = get_creditable_items(company, customer, from_date, to_date, exact=item_code, page_len=1)
	return rows[0] if rows else None


@frappe.whitelist()
def search(company, customer, items, from_date=None, to_date=None, since=None):
	"""Invoices of *customer* that still have returnable qty for the requested items.

	*since* (a datetime string) is when the user started working on this list: credit
	notes submitted for the customer after it are reported and deducted from what is
	still to be credited.
	"""
	_check_read()
	requested = _requested_items(items)
	codes = list(requested)

	known = {
		r.name: r.item_name
		for r in frappe.get_all("Item", filters={"name": ("in", codes)}, fields=["name", "item_name"])
	}
	unknown = [c for c in codes if c not in known]

	conditions = ""
	values = {"company": company, "customer": customer, "items": tuple(codes)}
	if from_date:
		conditions += " and si.posting_date >= %(from_date)s"
		values["from_date"] = getdate(from_date)
	if to_date:
		conditions += " and si.posting_date <= %(to_date)s"
		values["to_date"] = getdate(to_date)

	candidates = [
		r[0]
		for r in frappe.db.sql(
			"""
			select distinct si.name
			from `tabSales Invoice` si
			join `tabSales Invoice Item` sii on sii.parent = si.name
			where si.company = %(company)s and si.customer = %(customer)s
				and si.docstatus = 1 and si.is_return = 0
				and sii.item_code in %(items)s {0}
			""".format(conditions),
			values,
		)
	]

	invoices = []
	if candidates:
		fields = ["name", "posting_date", "grand_total", "outstanding_amount", "currency", "status", "is_pos", "update_stock"]
		if frappe.get_meta("Sales Invoice").has_field("fe_angola_document_status"):
			fields.append("fe_angola_document_status as fe_status")
		# get_list, not get_all: the user's own permissions decide which invoices show
		invoices = frappe.get_list(
			"Sales Invoice",
			filters={"name": ("in", candidates)},
			fields=fields,
			order_by="posting_date desc, name desc",
			limit_page_length=0,
		)

	by_invoice = {}
	for line in get_invoice_lines([i.name for i in invoices], codes):
		by_invoice.setdefault(line.invoice, []).append(line)

	drafts = {}
	if invoices:
		for name, against in frappe.db.sql(
			"""select name, return_against from `tabSales Invoice`
			where docstatus = 0 and is_return = 1 and return_against in %(inv)s""",
			{"inv": tuple(i.name for i in invoices)},
		):
			drafts.setdefault(against, []).append(name)

	returnable_total = {c: 0 for c in codes}
	invoice_count = {c: 0 for c in codes}
	result_invoices = []
	for inv in invoices:
		lines = [l for l in by_invoice.get(inv.name, [])]
		open_lines = [l for l in lines if l.returnable > 0]
		if not open_lines:
			continue
		matched = sorted({l.item_code for l in open_lines}, key=codes.index)
		for code in matched:
			returnable_total[code] += sum(l.returnable for l in open_lines if l.item_code == code)
			invoice_count[code] += 1
		inv.lines = lines
		inv.matched_items = matched
		inv.match_count = len(matched)
		inv.returnable_value = sum(flt(l.returnable) * flt(l.rate) for l in open_lines)
		inv.draft_returns = drafts.get(inv.name, [])
		result_invoices.append(inv)

	result_invoices.sort(key=lambda i: (-i.match_count, -getdate(i.posting_date).toordinal(), i.name))
	truncated = len(result_invoices) > MAX_INVOICES

	credited, credit_notes = {}, []
	if since:
		credit_notes = frappe.get_list(
			"Sales Invoice",
			filters={
				"company": company, "customer": customer, "docstatus": 1, "is_return": 1,
				"creation": (">=", since),
			},
			fields=["name", "return_against", "posting_date", "grand_total", "currency"],
			order_by="creation asc",
			limit_page_length=0,
		)
		if credit_notes:
			for code, qty in frappe.db.sql(
				"""select item_code, sum(abs(qty)) from `tabSales Invoice Item`
				where parent in %(cn)s and item_code in %(items)s group by item_code""",
				{"cn": tuple(c.name for c in credit_notes), "items": tuple(codes)},
			):
				credited[code] = flt(qty)

	return {
		"items": [
			{
				"item_code": code,
				"item_name": known.get(code),
				"unknown": code in unknown,
				"requested": requested[code],
				"credited": credited.get(code, 0),
				"remaining": max(requested[code] - credited.get(code, 0), 0),
				"returnable_total": returnable_total[code],
				"invoice_count": invoice_count[code],
			}
			for code in codes
		],
		"invoices": result_invoices[:MAX_INVOICES],
		"truncated": truncated,
		"credit_notes": credit_notes,
		# server clock, so the page's "since" compares like with like against creation
		"now": now(),
	}


@frappe.whitelist()
def make_credit_note(source_name, rows, reason=None, warehouse=None):
	"""An unsaved credit note against *source_name* holding only *rows*.

	rows: [{"row": <Sales Invoice Item name>, "qty": <positive qty to credit>}]
	warehouse: where returned goods go back in, for invoices that moved stock. With
	Stock Settings "force warehouse selection on returns" ERPNext leaves it blank for
	the user to choose; the allow-list is still enforced when the credit note is saved.
	"""
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

	if not frappe.has_permission("Sales Invoice", "create"):
		frappe.throw(_("Not permitted to create Sales Invoices."), frappe.PermissionError)
	source = frappe.get_doc("Sales Invoice", source_name)
	source.check_permission("read")
	if source.docstatus != 1 or source.is_return:
		frappe.throw(_("{0} is not a submitted sales invoice.").format(source_name))

	wanted = {}
	for r in _parse(rows) or []:
		if flt(r.get("qty")) > 0:
			wanted[r.get("row")] = wanted.get(r.get("row"), 0) + flt(r.get("qty"))
	if not wanted:
		frappe.throw(_("Choose at least one line with a quantity to credit."))

	source_rows = {d.name: d for d in source.items}
	lines = {
		l.row: l for l in get_invoice_lines([source.name], list({source_rows[r].item_code for r in wanted if r in source_rows}))
	}
	for row, qty in wanted.items():
		line = lines.get(row)
		if not line:
			frappe.throw(_("Line {0} does not belong to {1}.").format(row, source.name))
		if qty > flt(line.returnable) + 1e-9:
			frappe.throw(
				_("Row #{0} ({1}): only {2} can still be credited, {3} requested.").format(
					line.idx, line.item_code, flt(line.returnable), qty
				)
			)

	frappe.flags.selected_children = {"items": list(wanted)}
	try:
		doc = make_sales_return(source.name)
	finally:
		frappe.flags.selected_children = None

	serial_rows = []
	for d in doc.items:
		qty = wanted.get(d.sales_invoice_item)
		if qty is None:
			continue
		d.qty = -qty
		d.stock_qty = -qty * flt(d.conversion_factor or 1)
		if d.serial_no and len([s for s in d.serial_no.split("\n") if s.strip()]) != qty:
			serial_rows.append(d.idx)

	# make_sales_return copies header amounts of the whole invoice; scale the fixed
	# ones to the share of the invoice being credited
	share = 0
	if flt(source.total):
		share = abs(sum(flt(d.qty) * flt(d.rate) for d in doc.items)) / flt(source.total)
	if flt(source.discount_amount) and not flt(source.additional_discount_percentage):
		doc.discount_amount = -flt(source.discount_amount * share, doc.precision("discount_amount"))
	for tax in doc.get("taxes"):
		if tax.charge_type == "Actual":
			source_tax = next((t for t in source.taxes if t.idx == tax.idx), None)
			if source_tax:
				tax.tax_amount = -flt(source_tax.tax_amount * share, tax.precision("tax_amount"))

	# regenerated for the new amount by set_payment_schedule on save
	doc.set("payment_schedule", [])

	if warehouse and cint(doc.update_stock):
		if frappe.db.get_value("Warehouse", warehouse, "company") != doc.company:
			frappe.throw(_("Warehouse {0} does not belong to {1}.").format(warehouse, doc.company))
		for d in doc.items:
			d.warehouse = warehouse

	if reason and doc.meta.has_field("return_reason"):
		doc.return_reason = reason

	doc.calculate_taxes_and_totals()
	if cint(doc.is_pos) and doc.get("payments"):
		# refund the whole credit through the invoice's default (else first) mode
		total = flt(doc.rounded_total or doc.grand_total)
		target = next((p for p in doc.payments if cint(p.default)), doc.payments[0])
		for p in doc.payments:
			p.amount = total if p is target else 0
			p.base_amount = flt(p.amount * flt(doc.conversion_rate or 1), p.precision("base_amount"))
		doc.calculate_taxes_and_totals()

	doc.set_onload("isoft_credit_note_serial_rows", serial_rows)
	return doc
