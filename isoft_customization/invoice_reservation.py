"""Invoice stock reservation: a Sales Invoice can reserve, a Purchase Invoice can order.

In Angola the selling flow is Quotation -> Sales Invoice -> Delivery Note; nobody makes Sales
Orders. A Sales Invoice with "Reserve Stock" ticked counts its undelivered quantity in the
item/warehouse Bin.reserved_qty, exactly as an open Sales Order line would, until Delivery Notes
made from the invoice deliver it (or a credit note, cancel or "Stop reserving" settles it). A
Purchase Invoice with "Order Stock" does the same for Bin.ordered_qty until Purchase Receipts made
from it arrive.

Design: docs/superpowers/specs/2026-11-11-invoice-stock-reservation-design.md
"""
import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, now

SI, PI = "Sales Invoice", "Purchase Invoice"

# (doctype, column) that the pending-quantity queries join on.
INDEXES = (
	("Sales Invoice Item", "sales_invoice_item"),
	("Purchase Invoice Item", "purchase_invoice_item"),
	("Purchase Receipt Item", "purchase_invoice_item"),
	("Delivery Note Item", "si_detail"),
	("Packed Item", "parent_detail_docname"),
)


# ---------------------------------------------------------------- fields


def get_custom_fields():
	"""No `default` key on purpose: a default changed in Customize Form must survive migrate."""
	return {
		SI: [
			{
				"fieldname": "isoft_reserve_stock", "fieldtype": "Check", "label": "Reserve Stock",
				"insert_after": "update_stock", "print_hide": 1,
				"depends_on": "eval:!doc.update_stock && !doc.is_pos && !doc.is_return",
				"description": "Count undelivered quantities as Reserved until Delivery Notes made from this invoice deliver them.",
			},
			{
				"fieldname": "isoft_reservation_stopped", "fieldtype": "Check", "label": "Reservation Stopped",
				"insert_after": "isoft_reserve_stock", "read_only": 1, "allow_on_submit": 1, "no_copy": 1,
				"print_hide": 1, "depends_on": "eval:doc.docstatus==1 && doc.isoft_reserve_stock",
			},
		],
		PI: [
			{
				"fieldname": "isoft_order_stock", "fieldtype": "Check", "label": "Order Stock",
				"insert_after": "update_stock", "print_hide": 1,
				"depends_on": "eval:!doc.update_stock && !doc.is_return",
				"description": "Count unreceived quantities as Ordered until Purchase Receipts made from this invoice receive them.",
			},
			{
				"fieldname": "isoft_ordering_stopped", "fieldtype": "Check", "label": "Ordering Stopped",
				"insert_after": "isoft_order_stock", "read_only": 1, "allow_on_submit": 1, "no_copy": 1,
				"print_hide": 1, "depends_on": "eval:doc.docstatus==1 && doc.isoft_order_stock",
			},
		],
	}


def setup_custom_fields(*args, **kwargs):
	"""Idempotent; runs from after_migrate."""
	fields = get_custom_fields()
	missing = {
		dt for dt, rows in fields.items() for row in rows
		if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": row["fieldname"]})
	}
	create_custom_fields(fields, update=True)
	for dt, col in INDEXES:
		frappe.db.add_index(dt, [col])
	# Browsers cache form meta keyed on DocType.modified, which a new Custom Field does not touch.
	for dt in missing:
		frappe.db.set_value("DocType", dt, "modified", now(), update_modified=False)
		frappe.clear_cache(doctype=dt)


# ---------------------------------------------------------------- validation


def _box(doc):
	return "isoft_reserve_stock" if doc.doctype == SI else "isoft_order_stock"


def _stopped_field(doctype):
	return "isoft_reservation_stopped" if doctype == SI else "isoft_ordering_stopped"


def _is_bundle(item_code):
	return bool(item_code) and bool(frappe.db.exists("Product Bundle", {"new_item_code": item_code}))


def line_counts(doc, row):
	"""Whether this invoice line takes part in the reservation (ignores the tick box itself)."""
	if cint(doc.get("update_stock")) or cint(doc.get("is_return")) or cint(doc.get("is_pos")):
		return False
	links = ("so_detail", "dn_detail") if doc.doctype == SI else ("po_detail", "pr_detail")
	if any(row.get(f) for f in links) or cint(row.get("delivered_by_supplier")):
		return False
	if not row.item_code:
		return False
	if cint(frappe.get_cached_value("Item", row.item_code, "is_stock_item")):
		return True
	return doc.doctype == SI and _is_bundle(row.item_code)


def _validate(doc, message):
	box = _box(doc)
	if cint(doc.get("update_stock")) or cint(doc.get("is_return")) or cint(doc.get("is_pos")):
		doc.set(box, 0)
	if doc.docstatus == 0:
		doc.set(_stopped_field(doc.doctype), 0)
	if not cint(doc.get(box)):
		return False
	for row in doc.items:
		if line_counts(doc, row) and not row.warehouse:
			frappe.throw(_(message).format(row.idx, frappe.bold(row.item_code)))
	return True


def validate_sales_invoice(doc, method=None):
	if _validate(doc, "Row {0}: Warehouse is required to reserve stock for {1}."):
		# Core empties packed_items when Update Stock is off (update_packing_list, earlier in
		# validate); a reserving invoice keeps its bundle components so they can be reserved.
		from erpnext.stock.doctype.packed_item.packed_item import make_packing_list

		make_packing_list(doc)


def validate_purchase_invoice(doc, method=None):
	_validate(doc, "Row {0}: Warehouse is required to order stock for {1}.")


# ---------------------------------------------------------------- the invoice part of Bin figures
# Pending per line, in stock UOM, never below 0. Recomputed from documents every time.

_SI_BASE = """si.docstatus = 1 and si.isoft_reserve_stock = 1
	and si.update_stock = 0 and si.is_return = 0 and si.is_pos = 0"""
_SI_HEADER = _SI_BASE + " and si.isoft_reservation_stopped = 0"
_SI_LINE = """ifnull(sii.so_detail, '') = '' and ifnull(sii.dn_detail, '') = ''
	and ifnull(sii.delivered_by_supplier, 0) = 0"""
# Every credit note against the line counts: core refuses an Update Stock credit note against an
# invoice without Update Stock, so the goods never come back through one.
_SI_PENDING = """greatest(sii.stock_qty - ifnull(sii.delivered_qty, 0) * sii.conversion_factor
	- ifnull((select sum(-ri.stock_qty) from `tabSales Invoice Item` ri
		join `tabSales Invoice` r on r.name = ri.parent
		where ri.sales_invoice_item = sii.name and r.docstatus = 1 and r.is_return = 1), 0), 0)"""

_PI_BASE = """pi.docstatus = 1 and pi.isoft_order_stock = 1
	and pi.update_stock = 0 and pi.is_return = 0"""
_PI_HEADER = _PI_BASE + " and pi.isoft_ordering_stopped = 0"
_PI_LINE = """ifnull(pii.po_detail, '') = '' and ifnull(pii.pr_detail, '') = ''"""
# Received = non-return receipts made from the line (PR returns carry no link back, by design).
# A debit note WITH Update Stock sends received goods back and cancels out, so only debit notes
# without Update Stock reduce what is still owed.
_PI_PENDING = """greatest(pii.stock_qty
	- ifnull((select sum(pri.received_stock_qty) from `tabPurchase Receipt Item` pri
		join `tabPurchase Receipt` pr on pr.name = pri.parent
		where pri.purchase_invoice_item = pii.name and pr.docstatus = 1 and pr.is_return = 0), 0)
	- ifnull((select sum(-ri.stock_qty) from `tabPurchase Invoice Item` ri
		join `tabPurchase Invoice` r on r.name = ri.parent
		where ri.purchase_invoice_item = pii.name and r.docstatus = 1 and r.is_return = 1
		and r.update_stock = 0), 0), 0)"""


def invoice_reserved_qty(item_code, warehouse):
	"""Stock-UOM quantity that reserving Sales Invoices still owe for this item and warehouse."""
	row = frappe.db.sql(
		"""select
			ifnull((select sum({pending})
				from `tabSales Invoice Item` sii
				join `tabSales Invoice` si on si.name = sii.parent
				join `tabItem` i on i.name = sii.item_code and i.is_stock_item = 1
				where sii.item_code = %(item)s and sii.warehouse = %(wh)s and {header} and {line}), 0)
			+ ifnull((select sum(pk.qty * {pending} / sii.stock_qty)
				from `tabPacked Item` pk
				join `tabSales Invoice Item` sii on sii.name = pk.parent_detail_docname
				join `tabSales Invoice` si on si.name = pk.parent
				where pk.parenttype = 'Sales Invoice' and pk.item_code = %(item)s and pk.warehouse = %(wh)s
				and sii.stock_qty > 0 and {header} and {line}), 0)""".format(
			pending=_SI_PENDING, header=_SI_HEADER, line=_SI_LINE),
		{"item": item_code, "wh": warehouse},
	)
	return float(row[0][0] or 0)


def invoice_ordered_qty(item_code, warehouse):
	"""Stock-UOM quantity that ordering Purchase Invoices still expect for this item and warehouse."""
	row = frappe.db.sql(
		"""select sum({pending})
			from `tabPurchase Invoice Item` pii
			join `tabPurchase Invoice` pi on pi.name = pii.parent
			join `tabItem` i on i.name = pii.item_code and i.is_stock_item = 1
			where pii.item_code = %(item)s and pii.warehouse = %(wh)s and {header} and {line}""".format(
			pending=_PI_PENDING, header=_PI_HEADER, line=_PI_LINE),
		{"item": item_code, "wh": warehouse},
	)
	return float(row[0][0] or 0)


def _wrap(module, name, extra, also):
	current = getattr(module, name)
	if not getattr(current, "_isoft_original", None):
		original = current

		def wrapper(item_code, warehouse):
			return original(item_code, warehouse) + extra(item_code, warehouse)

		wrapper._isoft_original = original
		wrapper.__name__ = name
		setattr(module, name, wrapper)
		current = wrapper
	for other in also:
		setattr(other, name, current)


def apply(*args, **kwargs):
	"""Make ERPNext's Reserved / Ordered calculation include invoices.

	stock_balance.get_reserved_qty / get_ordered_qty feed every Bin refresh and repost; the Sales
	Order and Purchase Order modules import them by name, so those bindings are replaced too.
	Idempotent; runs at import (isoft_customization/__init__.py) and per request / job (hooks.py).
	"""
	try:
		from erpnext.buying.doctype.purchase_order import purchase_order
		from erpnext.selling.doctype.sales_order import sales_order
		from erpnext.stock import stock_balance
	except Exception:
		return
	_wrap(stock_balance, "get_reserved_qty", invoice_reserved_qty, [sales_order])
	_wrap(stock_balance, "get_ordered_qty", invoice_ordered_qty, [purchase_order])


# ---------------------------------------------------------------- keeping Bins current


def invoice_pairs(doctype, name):
	"""(item_code, warehouse) of the invoice's lines and bundle components."""
	child = "Sales Invoice Item" if doctype == SI else "Purchase Invoice Item"
	pairs = set(frappe.db.sql(
		"select item_code, warehouse from `tab{0}` where parent = %s and ifnull(warehouse, '') != ''".format(child),
		name))
	if doctype == SI:
		pairs |= set(frappe.db.sql(
			"""select item_code, warehouse from `tabPacked Item`
			where parenttype = 'Sales Invoice' and parent = %s and ifnull(warehouse, '') != ''""", name))
	return pairs


def refresh_invoice(doctype, name):
	"""Recompute Reserved (Sales Invoice) or Ordered (Purchase Invoice) for every Bin the invoice touches."""
	if not name or not cint(frappe.db.get_value(doctype, name, "isoft_reserve_stock" if doctype == SI else "isoft_order_stock")):
		return
	apply()
	from erpnext.stock import stock_balance

	for item_code, warehouse in invoice_pairs(doctype, name):
		if doctype == SI:
			qty = {"reserved_qty": stock_balance.get_reserved_qty(item_code, warehouse)}
		else:
			qty = {"ordered_qty": stock_balance.get_ordered_qty(item_code, warehouse)}
		stock_balance.update_bin_qty(item_code, warehouse, qty)


def on_sales_invoice_event(doc, method=None):
	"""on_submit / on_cancel: the invoice itself, or the one a credit note is against."""
	refresh_invoice(SI, doc.return_against if cint(doc.is_return) else doc.name)


def on_purchase_invoice_event(doc, method=None):
	refresh_invoice(PI, doc.return_against if cint(doc.is_return) else doc.name)


def on_delivery_note_event(doc, method=None):
	"""on_submit / on_cancel, after core has updated the invoice lines' delivered_qty (DN returns too)."""
	for name in {row.against_sales_invoice for row in doc.items if row.get("si_detail") and row.get("against_sales_invoice")}:
		refresh_invoice(SI, name)


def on_purchase_receipt_event(doc, method=None):
	for name in {row.purchase_invoice for row in doc.items if row.get("purchase_invoice_item") and row.get("purchase_invoice")}:
		refresh_invoice(PI, name)


# ---------------------------------------------------------------- Stop / Resume and the form indicator


def _check_invoice_doctype(doctype):
	if doctype not in (SI, PI):
		frappe.throw(_("Only Sales Invoices and Purchase Invoices reserve or order stock."))


@frappe.whitelist()
def pending_summary(doctype, name):
	"""What the invoice still reserves / expects, in stock units, whether or not it is stopped."""
	_check_invoice_doctype(doctype)
	if not frappe.has_permission(doctype, "read", name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	box = "isoft_reserve_stock" if doctype == SI else "isoft_order_stock"
	values = frappe.db.get_value(doctype, name, [box, _stopped_field(doctype)], as_dict=True) or {}
	if doctype == SI:
		qty = frappe.db.sql(
			"""select
				ifnull((select sum({pending}) from `tabSales Invoice Item` sii
					join `tabSales Invoice` si on si.name = sii.parent
					join `tabItem` i on i.name = sii.item_code and i.is_stock_item = 1
					where si.name = %(name)s and {base} and {line}), 0)
				+ ifnull((select sum(pk.qty * {pending} / sii.stock_qty) from `tabPacked Item` pk
					join `tabSales Invoice Item` sii on sii.name = pk.parent_detail_docname
					join `tabSales Invoice` si on si.name = pk.parent
					where pk.parenttype = 'Sales Invoice' and si.name = %(name)s and sii.stock_qty > 0
					and {base} and {line}), 0)""".format(pending=_SI_PENDING, base=_SI_BASE, line=_SI_LINE),
			{"name": name})
	else:
		qty = frappe.db.sql(
			"""select sum({pending}) from `tabPurchase Invoice Item` pii
				join `tabPurchase Invoice` pi on pi.name = pii.parent
				join `tabItem` i on i.name = pii.item_code and i.is_stock_item = 1
				where pi.name = %(name)s and {base} and {line}""".format(pending=_PI_PENDING, base=_PI_BASE, line=_PI_LINE),
			{"name": name})
	return {
		"enabled": cint(values.get(box)),
		"stopped": cint(values.get(_stopped_field(doctype))),
		"pending_qty": float(qty[0][0] or 0),
	}


@frappe.whitelist()
def set_stopped(doctype, name, stopped):
	"""Stop / Resume: a stopped invoice keeps its lines but no longer reserves / orders anything."""
	_check_invoice_doctype(doctype)
	doc = frappe.get_doc(doctype, name)
	box = "isoft_reserve_stock" if doctype == SI else "isoft_order_stock"
	if doc.docstatus != 1 or not cint(doc.get(box)):
		frappe.throw(_("{0} {1} is not a submitted invoice that reserves or orders stock.").format(_(doctype), name))
	if not frappe.has_permission(doctype, "submit", doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	doc.db_set(_stopped_field(doctype), 1 if cint(stopped) else 0)
	refresh_invoice(doctype, name)
	return pending_summary(doctype, name)


# ---------------------------------------------------------------- lines, for other screens (POS Customer Orders)


def reserving_invoice_lines(company, warehouse, item_code=None, invoice=None, open_only=True, from_date=None, to_date=None):
	"""Lines (and bundle components) of reserving Sales Invoices for one warehouse, in stock units.

	open_only: only invoices that still reserve (not stopped) and lines with something pending; the
	rows then add up to exactly what invoice_reserved_qty counts for that warehouse.
	"""
	cond = ["si.company = %(company)s", _SI_HEADER if open_only else _SI_BASE, _SI_LINE]
	args = {"company": company, "wh": warehouse, "item": item_code, "invoice": invoice,
		"from_date": from_date, "to_date": to_date}
	if invoice:
		cond.append("si.name = %(invoice)s")
	if from_date:
		cond.append("si.posting_date >= %(from_date)s")
	if to_date:
		cond.append("si.posting_date <= %(to_date)s")
	where = " and ".join(cond)
	head = """si.name as invoice, si.customer, si.customer_name, si.posting_date, si.grand_total, si.currency"""
	rows = frappe.db.sql(
		"""select {head}, sii.idx, 0 as sub, sii.item_code, sii.item_name, sii.stock_uom as uom, sii.stock_qty as qty,
				ifnull(sii.delivered_qty, 0) * sii.conversion_factor as delivered_qty, {pending} as pending,
				sii.rate / sii.conversion_factor as rate, sii.amount
			from `tabSales Invoice Item` sii
			join `tabSales Invoice` si on si.name = sii.parent
			join `tabItem` i on i.name = sii.item_code and i.is_stock_item = 1
			where sii.warehouse = %(wh)s {item} and {where}
		union all
		select {head}, sii.idx, pk.idx as sub, pk.item_code, pk.item_name, pk.uom, pk.qty,
				pk.qty * (1 - {pending} / sii.stock_qty) as delivered_qty, pk.qty * {pending} / sii.stock_qty as pending,
				0 as rate, 0 as amount
			from `tabPacked Item` pk
			join `tabSales Invoice Item` sii on sii.name = pk.parent_detail_docname
			join `tabSales Invoice` si on si.name = pk.parent
			where pk.parenttype = 'Sales Invoice' and pk.warehouse = %(wh)s and sii.stock_qty > 0
				{pk_item} and {where}
		order by posting_date, invoice, idx, sub""".format(
			head=head, pending=_SI_PENDING, where=where,
			item="and sii.item_code = %(item)s" if item_code else "",
			pk_item="and pk.item_code = %(item)s" if item_code else ""),
		args, as_dict=True)
	return [r for r in rows if r.pending > 0] if open_only else rows
