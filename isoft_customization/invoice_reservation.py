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

_SI_HEADER = """si.docstatus = 1 and si.isoft_reserve_stock = 1 and si.isoft_reservation_stopped = 0
	and si.update_stock = 0 and si.is_return = 0 and si.is_pos = 0"""
_SI_LINE = """ifnull(sii.so_detail, '') = '' and ifnull(sii.dn_detail, '') = ''
	and ifnull(sii.delivered_by_supplier, 0) = 0"""
# Every credit note against the line counts: core refuses an Update Stock credit note against an
# invoice without Update Stock, so the goods never come back through one.
_SI_PENDING = """greatest(sii.stock_qty - ifnull(sii.delivered_qty, 0) * sii.conversion_factor
	- ifnull((select sum(-ri.stock_qty) from `tabSales Invoice Item` ri
		join `tabSales Invoice` r on r.name = ri.parent
		where ri.sales_invoice_item = sii.name and r.docstatus = 1 and r.is_return = 1), 0), 0)"""

_PI_HEADER = """pi.docstatus = 1 and pi.isoft_order_stock = 1 and pi.isoft_ordering_stopped = 0
	and pi.update_stock = 0 and pi.is_return = 0"""
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
