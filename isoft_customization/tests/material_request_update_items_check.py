"""Editing a submitted Material Request (Stock Settings switch, material_request_items.py). Rolled back.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/material_request_update_items_check.py dev.isoft.ao
"""
import sys

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0
WH, WH2 = "01 - Loja Alvalade - ITEC", "07 - Maculusso Armazem - ITEC"


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:400])
	fails += not cond


def refused(fn):
	try:
		fn()
		return False
	except frappe.ValidationError:
		frappe.db.rollback(save_point="mr_case")
		return True


def indented(item, wh):
	return flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": wh}, "indented_qty"))


try:
	from isoft_customization import material_request_items as mri

	s = frappe.get_single("Stock Settings")
	s.set(mri.FIELD, 1)
	s.save()
	meta = frappe.get_meta("Material Request")
	check("items_table_allow_on_submit", meta.get_field("items").allow_on_submit == 1)
	check("qty_allow_on_submit", frappe.get_meta("Material Request Item").get_field("qty").allow_on_submit == 1)

	mr = frappe.get_doc({"doctype": "Material Request", "material_request_type": "Purchase", "company": "ITEC LDA",
		"transaction_date": nowdate(), "schedule_date": add_days(nowdate(), 7), "items": [
			{"item_code": "PAP-A4", "qty": 5, "warehouse": WH, "schedule_date": add_days(nowdate(), 7)},
			{"item_code": "MSE-LOG-M185", "qty": 3, "warehouse": WH, "schedule_date": add_days(nowdate(), 7)},
			{"item_code": "CBL-SN4", "qty": 2, "warehouse": WH, "schedule_date": add_days(nowdate(), 7)}]})
	mr.insert()
	mr.submit()
	before_pap = indented("PAP-A4", WH)

	mr = frappe.get_doc("Material Request", mr.name)
	mr.items[0].qty = 8                                   # change an unused line
	mr.remove(mr.items[2])                                # remove an unused line
	mr.append("items", {"item_code": "21601", "qty": 4, "warehouse": WH2, "schedule_date": getdate(add_days(nowdate(), 10))})  # add
	mr.save()
	mr = frappe.get_doc("Material Request", mr.name)
	got = sorted((x.item_code, flt(x.qty), x.warehouse) for x in mr.items)
	check("lines_updated", got == sorted([("PAP-A4", 8, WH), ("MSE-LOG-M185", 3, WH), ("21601", 4, WH2)]), got)
	check("stock_qty_follows", all(flt(x.stock_qty) == flt(x.qty) * flt(x.conversion_factor or 1) for x in mr.items),
		[(x.qty, x.stock_qty, x.conversion_factor) for x in mr.items])
	check("new_line_filled", all(x.stock_uom and x.item_name for x in mr.items))
	check("requested_qty_updated", abs(indented("PAP-A4", WH) - before_pap - 3) < 0.001, (before_pap, indented("PAP-A4", WH)))
	check("comment_logged", frappe.db.exists("Comment", {"reference_doctype": "Material Request", "reference_name": mr.name, "comment_type": "Info"}))

	# a line already used by a Purchase Order (ordered 2)
	used_name = next(x.name for x in mr.items if x.item_code == "MSE-LOG-M185")
	frappe.db.set_value("Material Request Item", used_name, "ordered_qty", 2)
	frappe.db.savepoint("mr_case")

	def edit(fn):
		def run():
			d = frappe.get_doc("Material Request", mr.name)
			fn(d, next(x for x in d.items if x.name == used_name))
			d.save()
		return run

	check("used_line_qty_not_below_ordered", refused(edit(lambda d, r: setattr(r, "qty", 1))))
	check("used_line_warehouse_locked", refused(edit(lambda d, r: setattr(r, "warehouse", WH2))))
	check("used_line_item_locked", refused(edit(lambda d, r: setattr(r, "item_code", "PAP-A4"))))
	check("used_line_cannot_be_removed", refused(edit(lambda d, r: d.remove(r))))
	edit(lambda d, r: setattr(r, "qty", 6))()
	check("used_line_qty_can_grow", flt(frappe.db.get_value("Material Request Item", used_name, "qty")) == 6)
	frappe.db.savepoint("mr_case")
	check("all_lines_removed_refused", refused(edit(lambda d, r: d.set("items", []))))

	# switch off: back to standard (no allow on submit)
	s = frappe.get_single("Stock Settings")
	s.set(mri.FIELD, 0)
	s.save()
	check("switch_off_restores", frappe.get_meta("Material Request").get_field("items").allow_on_submit == 0)
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.clear_cache(doctype="Material Request")
	frappe.clear_cache(doctype="Material Request Item")
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
