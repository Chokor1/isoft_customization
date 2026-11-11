"""Invoice stock reservation: fields, indexes, validation, bundle components.

Phase 1 changes one Custom Field default and restores it (committed, since the installer may run
DDL). Phase 2 creates throwaway items/bundles and only validates unsaved invoices; all rolled back.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/invoice_reservation_fields_check.py dev.isoft.ao
"""
import os
import sys

import frappe

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import invoice_reservation_fixtures as fx  # noqa: E402

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
check, state = fx.check_factory()

FIELDS = {
	("Sales Invoice", "isoft_reserve_stock"): "Reserve Stock",
	("Sales Invoice", "isoft_reservation_stopped"): "Reservation Stopped",
	("Purchase Invoice", "isoft_order_stock"): "Order Stock",
	("Purchase Invoice", "isoft_ordering_stopped"): "Ordering Stopped",
}
INDEXES = [
	("Sales Invoice Item", "sales_invoice_item"),
	("Purchase Invoice Item", "purchase_invoice_item"),
	("Purchase Receipt Item", "purchase_invoice_item"),
	("Delivery Note Item", "si_detail"),
	("Packed Item", "parent_detail_docname"),
]


def raises(fn):
	try:
		fn()
		return None
	except frappe.ValidationError as e:
		return str(e) or repr(e)


try:
	from isoft_customization import invoice_reservation as ir

	# ---- phase 1: installer
	for (dt, fn), label in FIELDS.items():
		cf = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fn}, ["label", "default"], as_dict=True)
		check("fields_exist %s.%s" % (dt, fn), bool(cf) and cf.label == label and (cf.default or "0") == "0", cf)
	check("installer_sends_no_default",
		all("default" not in f for rows in ir.get_custom_fields().values() for f in rows))
	cf_name = frappe.db.get_value("Custom Field", {"dt": "Sales Invoice", "fieldname": "isoft_reserve_stock"})
	if cf_name:
		frappe.db.set_value("Custom Field", cf_name, "default", "1")
		try:
			ir.setup_custom_fields()
			check("fields_keep_custom_default", frappe.db.get_value("Custom Field", cf_name, "default") == "1")
		finally:
			frappe.db.set_value("Custom Field", cf_name, "default", None)
			frappe.db.commit()
	for dt, col in INDEXES:
		check("indexes_exist %s.%s" % (dt, col), bool(frappe.db.sql("show index from `tab%s` where Column_name=%%s" % dt, col)))

	# ---- phase 2: validation (rolled back)
	a = fx.stock_item("IR-T1-A")
	b = fx.stock_item("IR-T1-B")
	svc = fx.stock_item("IR-T1-SVC", stock=False)
	bun = fx.bundle("IR-T1-BUN", [(a, 2), (b, 3)])

	# Called directly: dev's "Sales Invoice" Server Script refuses Update Stock lines without
	# stock, and is_pos needs payments; the hook is what is under test here.
	d = fx.draft_si([(a, 1)], update_stock=1)
	ir.validate_sales_invoice(d)
	check("validate_off_with_update_stock", d.isoft_reserve_stock == 0, d.isoft_reserve_stock)
	d = fx.draft_si([(a, 1)], is_pos=1)
	ir.validate_sales_invoice(d)
	check("validate_off_with_is_pos", d.isoft_reserve_stock == 0, d.isoft_reserve_stock)
	check("hook_wired", "isoft_customization.invoice_reservation.validate_sales_invoice"
		in frappe.get_hooks("doc_events")["Sales Invoice"]["validate"]
		and "isoft_customization.invoice_reservation.validate_purchase_invoice"
		in frappe.get_hooks("doc_events")["Purchase Invoice"]["validate"])
	d = fx.validate(fx.draft_si([(a, 1)], isoft_reservation_stopped=1))
	check("validate_clears_stopped_on_draft", d.isoft_reservation_stopped == 0)

	d = fx.draft_si([(a, 1)])
	d.items[0].warehouse = None
	msg = raises(lambda: fx.validate(d))
	check("validate_requires_warehouse", bool(msg) and "Row 1" in msg, msg)

	d = fx.draft_si([(a, 1)])
	d.items[0].warehouse = None
	d.isoft_reserve_stock = 0
	check("unticked_needs_no_warehouse", raises(lambda: fx.validate(d)) is None)

	d = fx.draft_si([(svc, 1, {"warehouse": None})])
	check("non_stock_line_needs_no_warehouse", raises(lambda: fx.validate(d)) is None)

	d = fx.draft_si([(a, 1, {"so_detail": "dummy-so-row"}), (b, 1)])
	ir.validate_sales_invoice(d)  # direct: core rejects the dummy order reference
	check("validate_keeps_box_for_mixed_lines", d.isoft_reserve_stock == 1)
	check("line_counts so_detail False / free True",
		ir.line_counts(d, d.items[0]) is False and ir.line_counts(d, d.items[1]) is True,
		(ir.line_counts(d, d.items[0]), ir.line_counts(d, d.items[1])))

	d = fx.validate(fx.draft_si([(bun, 2)]))
	packed = {p.item_code: p.qty for p in d.get("packed_items")}
	check("validate_builds_packed_items", packed == {a: 4, b: 6}, packed)
	check("line_counts bundle parent", ir.line_counts(d, d.items[0]) is True)
	d = fx.validate(fx.draft_si([(bun, 2)], reserve=0))
	check("unticked_no_packed_items", not d.get("packed_items"), d.get("packed_items"))

	d = fx.draft_pi([(a, 1)], is_return=1)
	ir.validate_purchase_invoice(d)
	check("validate_purchase_off_on_return", d.isoft_order_stock == 0)
	d = fx.draft_pi([(a, 1)], update_stock=1)
	ir.validate_purchase_invoice(d)
	check("validate_purchase_off_with_update_stock", d.isoft_order_stock == 0)
	d = fx.draft_pi([(a, 1)])
	d.items[0].warehouse = None
	msg = raises(lambda: fx.validate(d))
	check("validate_purchase_requires_warehouse", bool(msg) and "Row 1" in msg, msg)
	d = fx.draft_pi([(a, 1, {"po_detail": "dummy-po-row"})])
	ir.validate_purchase_invoice(d)
	check("line_counts po_detail False", ir.line_counts(d, d.items[0]) is False)
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.destroy()
	sys.exit(1 if state["fails"] else 0)
