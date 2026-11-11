"""Invoice stock reservation: the invoice part of Reserved / Ordered and the wrap of ERPNext's functions.

Documents are submitted fixtures written with db_insert (no hooks, no GL); everything is rolled back.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/invoice_reservation_calc_check.py dev.isoft.ao
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
WH = fx.WH

try:
	from isoft_customization.invoice_reservation import apply, invoice_ordered_qty, invoice_reserved_qty

	def R(code):
		return invoice_reserved_qty(code, WH)

	def O(code):
		return invoice_ordered_qty(code, WH)

	# --- spec example 1: 10, DN 6, credit 3, DN 7
	i1 = fx.stock_item("IR-T2-E1")
	s = fx.si([fx.line(i1, 10)])
	check("calc_spec_example_1 invoice", R(i1) == 10, R(i1))
	fx.set_line(s["items"][0], delivered_qty=6)
	check("calc_spec_example_1 dn6", R(i1) == 4, R(i1))
	fx.credit_note(s, [(s["items"][0], i1, 3)])
	check("calc_spec_example_1 credit3", R(i1) == 1, R(i1))
	fx.set_line(s["items"][0], delivered_qty=7)
	check("calc_spec_example_1 dn7", R(i1) == 0, R(i1))

	# --- spec example 2: delivered 8 after a DN return, then credit 2
	i2 = fx.stock_item("IR-T2-E2")
	s = fx.si([fx.line(i2, 10, delivered_qty=8)])
	check("calc_spec_example_2 owed again", R(i2) == 2, R(i2))
	fx.credit_note(s, [(s["items"][0], i2, 2)])
	check("calc_spec_example_2 credit", R(i2) == 0, R(i2))

	# --- UOM
	i3 = fx.stock_item("IR-T2-UOM", uoms=[("Box", 12)])
	s = fx.si([fx.line(i3, 2, cf=12, uom="Box")])
	check("calc_uom", R(i3) == 24, R(i3))
	fx.set_line(s["items"][0], delivered_qty=1)
	check("calc_uom delivered 1 box", R(i3) == 12, R(i3))

	# --- lines and invoices that never count
	i4 = fx.stock_item("IR-T2-IGN")
	fx.si([fx.line(i4, 5, so_detail="x-so")])
	check("calc_so_line_ignored", R(i4) == 0, R(i4))
	fx.si([fx.line(i4, 5, dn_detail="x-dn")])
	check("calc_dn_line_ignored", R(i4) == 0, R(i4))
	fx.si([fx.line(i4, 1)], isoft_reserve_stock=0)
	fx.si([fx.line(i4, 1)], isoft_reservation_stopped=1)
	fx.si([fx.line(i4, 1)], update_stock=1)
	fx.si([fx.line(i4, 1)], is_pos=1)
	fx.si([fx.line(i4, 1)], docstatus=2)
	fx.si([fx.line(i4, 1)], docstatus=0)
	fx.si([fx.line(i4, 1, delivered_by_supplier=1)])
	check("calc_excluded_invoices", R(i4) == 0, R(i4))
	svc = fx.stock_item("IR-T2-SVC", stock=False)
	fx.si([fx.line(svc, 3)])
	check("calc_non_stock_ignored", R(svc) == 0, R(svc))
	other_wh = "01 - Armazém Central Luanda - NDA"
	fx.si([fx.line(i4, 4, warehouse=other_wh)])
	check("calc_other_warehouse", R(i4) == 0 and invoice_reserved_qty(i4, other_wh) == 4, (R(i4), invoice_reserved_qty(i4, other_wh)))

	i5 = fx.stock_item("IR-T2-OVER")
	fx.si([fx.line(i5, 10, delivered_qty=12)])
	fx.si([fx.line(i5, 3)])
	check("calc_over_delivered_floor", R(i5) == 3, R(i5))

	# --- bundle: 2 bundles of (A x2, B x3), parent delivered 1
	a = fx.stock_item("IR-T2-BA")
	b = fx.stock_item("IR-T2-BB")
	bun = fx.bundle("IR-T2-BUN", [(a, 2), (b, 3)])
	s = fx.si([fx.line(bun, 2)])
	pline = s["items"][0]
	for code, q in ((a, 4), (b, 6)):
		frappe.get_doc({"doctype": "Packed Item", "name": "%s-pk-%s" % (s["name"], code), "parent": s["name"],
			"parenttype": "Sales Invoice", "parentfield": "packed_items", "item_code": code, "parent_item": bun,
			"qty": q, "warehouse": WH, "parent_detail_docname": pline, "docstatus": 1}).db_insert()
	check("calc_bundle full", (R(a), R(b), R(bun)) == (4, 6, 0), (R(a), R(b), R(bun)))
	fx.set_line(pline, delivered_qty=1)
	check("calc_bundle delivered 1", (R(a), R(b)) == (2, 3), (R(a), R(b)))
	fx.credit_note(s, [(pline, bun, 1)])
	check("calc_bundle credited 1", (R(a), R(b)) == (0, 0), (R(a), R(b)))

	# --- purchase
	p1 = fx.stock_item("IR-T2-P1")
	p = fx.pi([fx.line(p1, 10)])
	pl = p["items"][0]
	check("calc_purchase invoice", O(p1) == 10, O(p1))
	fx.receipt([(pl, p1, 6)])
	check("calc_purchase received 6", O(p1) == 4, O(p1))
	fx.debit_note(p, [(pl, p1, 3)])
	check("calc_purchase debit no stock", O(p1) == 1, O(p1))
	fx.debit_note(p, [(pl, p1, 2)], update_stock=1)
	check("calc_purchase debit with stock ignored", O(p1) == 1, O(p1))
	fx.receipt([(None, p1, -1)], is_return=1)
	fx.receipt([(pl, p1, 5)], docstatus=2)
	check("calc_purchase pr return and cancelled pr ignored", O(p1) == 1, O(p1))
	p2 = fx.stock_item("IR-T2-P2")
	fx.pi([fx.line(p2, 5, po_detail="x-po")])
	fx.pi([fx.line(p2, 5, pr_detail="x-pr")])
	fx.pi([fx.line(p2, 5)], isoft_order_stock=0)
	fx.pi([fx.line(p2, 5)], isoft_ordering_stopped=1)
	fx.pi([fx.line(p2, 5)], update_stock=1)
	check("calc_purchase excluded", O(p2) == 0, O(p2))
	check("calc_purchase sales side untouched", R(p1) == 0 and O(i1) == 0, (R(p1), O(i1)))

	# --- the wrap
	from erpnext.buying.doctype.purchase_order import purchase_order
	from erpnext.selling.doctype.sales_order import sales_order
	from erpnext.stock import stock_balance

	apply()
	w = stock_balance.get_reserved_qty
	orig = getattr(w, "_isoft_original", None)
	check("calc_wrap reserved", orig is not None and w(a, WH) == orig(a, WH) + R(a) and w(i5, WH) == orig(i5, WH) + 3,
		(orig, w(i5, WH)))
	check("calc_wrap sales_order binding", sales_order.get_reserved_qty is w)
	apply()
	check("calc_wrap idempotent reserved", stock_balance.get_reserved_qty is w)
	wo = stock_balance.get_ordered_qty
	origo = getattr(wo, "_isoft_original", None)
	check("calc_wrap ordered", origo is not None and wo(p1, WH) == origo(p1, WH) + 1, (origo, wo(p1, WH)))
	check("calc_wrap purchase_order binding", purchase_order.get_ordered_qty is wo)
	apply()
	check("calc_wrap idempotent ordered", stock_balance.get_ordered_qty is wo)
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.destroy()
	sys.exit(1 if state["fails"] else 0)
