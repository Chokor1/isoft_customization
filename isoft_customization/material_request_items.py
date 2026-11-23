"""Stock Settings "Allow editing submitted Material Requests".

On: the Material Request items table and its fields get "Allow on Submit" (Property
Setters), so a submitted request can be changed in the form and saved with Update:
quantities, units, warehouses, dates, new lines, removed lines.

Guarded here, because ERPNext builds on the submitted lines:
- a line already used (ordered / received / referenced by a Purchase Order, Stock Entry,
  Work Order, Supplier Quotation or RFQ) cannot be removed nor moved to another item,
  unit or warehouse, and its qty cannot go below what is already ordered or received;
- Stopped / Cancelled requests and an empty table are refused;
- afterwards the requested qty (Bin indented_qty) of every touched item + warehouse,
  Ordered % / Received % and the status are recomputed, and a comment records the change.
Off: the Property Setters are removed and the form is standard again.
"""
import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt

FIELD = "isoft_mr_edit_after_submit"
LOCKED_ON_USED = ("item_code", "uom", "warehouse", "from_warehouse", "conversion_factor")
NEVER_EDITABLE = ("ordered_qty", "received_qty", "material_request_plan_item", "production_plan")
REFERENCES = (  # (child doctype, field pointing at the Material Request Item, parent doctype or None)
	("Purchase Order Item", "material_request_item", "Purchase Order"),
	("Stock Entry Detail", "material_request_item", "Stock Entry"),
	("Supplier Quotation Item", "material_request_item", "Supplier Quotation"),
	("Request for Quotation Item", "material_request_item", "Request for Quotation"),
	("Work Order", "material_request_item", None),
)


def setup_custom_fields(*args, **kwargs):
	create_custom_fields({"Stock Settings": [{
		"fieldname": FIELD, "fieldtype": "Check", "default": "0", "insert_after": "mr_qty_allowance",
		"label": "Allow editing submitted Material Requests",
		"description": "Change quantities, units, warehouses and dates, add or remove lines on a submitted "
			"Material Request and save with Update. Lines already ordered or transferred stay locked "
			"(their qty can only stay at or above what was ordered).",
	}]}, update=True)


def enabled():
	return cint(frappe.db.get_single_value("Stock Settings", FIELD)) if frappe.get_meta("Stock Settings").has_field(FIELD) else 0


# ---------------------------------------------------------------------------- switch
def _targets():
	"""(doctype, fieldname) whose standard allow_on_submit is 0 and that the switch opens."""
	out = [("Material Request", "items")]
	for name, fieldtype, allow in frappe.db.sql("""select fieldname, fieldtype, allow_on_submit from tabDocField
		where parent = 'Material Request Item'"""):
		if fieldtype in ("Section Break", "Column Break", "Tab Break", "HTML", "Button") or name in NEVER_EDITABLE or cint(allow):
			continue
		out.append(("Material Request Item", name))
	return out


def apply_switch(doc=None, method=None, *args, **kwargs):
	"""Stock Settings on_update: add or remove the Property Setters."""
	on = cint((doc or frappe.get_single("Stock Settings")).get(FIELD))
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	for dt, fieldname in _targets():
		existing = frappe.db.get_value("Property Setter",
			{"doc_type": dt, "field_name": fieldname, "property": "allow_on_submit"}, "name")
		if on and not existing:
			make_property_setter(dt, fieldname, "allow_on_submit", 1, "Check", validate_fields_for_doctype=False)
		elif not on and existing:
			frappe.delete_doc("Property Setter", existing, ignore_permissions=True, force=True)
	frappe.clear_cache(doctype="Material Request")
	frappe.clear_cache(doctype="Material Request Item")


# ---------------------------------------------------------------------------- guard
def _used(row):
	if flt(row.get("ordered_qty")) > 0 or flt(row.get("received_qty")) > 0:
		return True
	for child_dt, field, parent_dt in REFERENCES:
		if not frappe.get_meta(child_dt).has_field(field):
			continue
		if parent_dt:
			hit = frappe.db.sql("""select 1 from `tab{c}` c join `tab{p}` p on p.name = c.parent
				where c.`{f}` = %s and p.docstatus < 2 limit 1""".format(c=child_dt, p=parent_dt, f=field), row.name)
		else:
			hit = frappe.db.sql("select 1 from `tab{c}` where `{f}` = %s and docstatus < 2 limit 1".format(c=child_dt, f=field), row.name)
		if hit:
			return True
	return False


def before_update_after_submit(doc, method=None, *args, **kwargs):
	if not enabled():
		return
	if doc.status in ("Stopped", "Cancelled"):
		frappe.throw(_("A {0} Material Request cannot be changed. Re-open it first.").format(_(doc.status)))
	rows = [r for r in doc.get("items") if r.get("item_code")]
	if not rows:
		frappe.throw(_("A Material Request needs at least one item."))

	before = frappe.get_doc(doc.doctype, doc.name)  # as it is in the database
	old = {r.name: r for r in before.items}
	doc.flags.isoft_mr_old_bins = {(r.item_code, r.warehouse) for r in before.items}
	changes = []

	current = {r.name for r in doc.items}
	for name, r in old.items():
		if name not in current:
			if _used(r):
				frappe.throw(_("Row #{0} ({1}) is already ordered or transferred and cannot be removed.").format(r.idx, r.item_code))
			changes.append(_("removed {0} × {1}").format(flt(r.qty), r.item_code))

	for r in doc.items:
		prev = old.get(r.name)
		if prev is None or r.is_new():
			_fill_new_row(doc, r)
			changes.append(_("added {0} × {1}").format(flt(r.qty), r.item_code))
		else:
			if _used(prev):
				for f in LOCKED_ON_USED:
					if (r.get(f) or None) != (prev.get(f) or None) and not (f == "conversion_factor" and flt(r.get(f)) == flt(prev.get(f))):
						frappe.throw(_("Row #{0} ({1}) is already ordered or transferred: its {2} cannot change.").format(
							r.idx, prev.item_code, _(r.meta.get_label(f))))
			if flt(r.qty) != flt(prev.qty):
				changes.append(_("{0}: {1} → {2}").format(r.item_code, flt(prev.qty), flt(r.qty)))
			elif r.item_code != prev.item_code or r.warehouse != prev.warehouse:
				changes.append(_("row #{0} changed").format(r.idx))
		cf = flt(r.conversion_factor) or 1
		r.conversion_factor = cf
		r.stock_qty = flt(r.qty) * cf
		done = max(flt(r.get("ordered_qty")), flt(r.get("received_qty")))
		if flt(r.stock_qty) + 1e-9 < done:
			frappe.throw(_("Row #{0} ({1}): {2} is below the {3} already ordered or received.").format(
				r.idx, r.item_code, flt(r.qty), done / cf))
		if flt(r.qty) <= 0:
			frappe.throw(_("Row #{0} ({1}): the quantity must be greater than zero.").format(r.idx, r.item_code))
	doc.flags.isoft_mr_changes = changes


def _fill_new_row(doc, r):
	item = frappe.get_cached_value("Item", r.item_code, ["item_name", "description", "stock_uom", "item_group", "brand"], as_dict=True)
	if not item:
		frappe.throw(_("Item {0} not found").format(r.item_code))
	r.item_name = r.item_name or item.item_name
	r.description = r.description or item.description or item.item_name
	r.stock_uom = item.stock_uom
	r.uom = r.uom or item.stock_uom
	if r.uom == item.stock_uom:
		r.conversion_factor = 1
	elif not flt(r.conversion_factor):
		r.conversion_factor = flt(frappe.db.get_value("UOM Conversion Detail", {"parent": r.item_code, "uom": r.uom}, "conversion_factor")) or 1
	r.item_group = r.get("item_group") or item.item_group
	r.brand = r.get("brand") or item.brand
	r.schedule_date = r.schedule_date or doc.schedule_date
	r.warehouse = r.warehouse or doc.get("set_warehouse")
	if not r.warehouse:
		frappe.throw(_("Row #{0} ({1}): set a warehouse.").format(r.idx, r.item_code))
	r.ordered_qty = r.received_qty = 0


def on_update_after_submit(doc, method=None, *args, **kwargs):
	if not enabled() or doc.flags.isoft_mr_old_bins is None:
		return
	from erpnext.stock.stock_balance import get_indented_qty, update_bin_qty

	bins = set(doc.flags.isoft_mr_old_bins) | {(r.item_code, r.warehouse) for r in doc.items}
	for item_code, warehouse in bins:
		if item_code and warehouse and cint(frappe.get_cached_value("Item", item_code, "is_stock_item")):
			update_bin_qty(item_code, warehouse, {"indented_qty": get_indented_qty(item_code, warehouse)})
	for field, ref in (("per_ordered", "ordered_qty"), ("per_received", "received_qty")):
		if doc.meta.has_field(field):
			doc._update_percent_field({"target_dt": "Material Request Item", "target_parent_dt": doc.doctype,
				"target_parent_field": field, "target_ref_field": "stock_qty", "target_field": ref, "name": doc.name}, True)
	doc.reload()
	doc.set_status(update=True)
	changes = doc.flags.isoft_mr_changes or []
	if changes:
		doc.add_comment("Info", _("Items updated after submit: {0}").format("; ".join(changes)))
	doc.flags.isoft_mr_old_bins = None
