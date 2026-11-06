"""Barcode Label Settings check. Rolls back everything.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/barcode_label_settings_check.py dev.isoft.ao
"""
import json
import sys

import frappe

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else detail)
	fails += not cond


try:
	from isoft_customization.barcode_labels import settings as st

	s = st.get_settings()
	names = [z["label_name"] for z in s["sizes"]]
	check("seeded_sizes", names[:3] == ["50×30", "30×50", "50×80"], names)
	check("one_default", sum(1 for z in s["sizes"] if z["is_default"]) == 1, s["sizes"])
	z = {x["label_name"]: x for x in s["sizes"]}
	check("size_dims", z.get("30×50", {}).get("width_mm") == 30 and z.get("30×50", {}).get("height_mm") == 50, z.get("30×50"))
	check("ean_prefix_default", s["ean_prefix"] == "200", s["ean_prefix"])
	off = ("company", "item_name", "uom", "price", "discount")
	check("show_defaults", all(s["show"][k] == 0 for k in off) and all(s["show"][k] == 1 for k in ("item_code", "barcode", "barcode_digits")), s["show"])
	check("currency_defaults", s["currency_symbol"] == "Kz" and s["symbol_position"] == "After" and s["price_decimals"] == 2, s)

	s["sizes"].append({"label_name": "40×25", "width_mm": 40, "height_mm": 25, "padding_mm": 1, "font_size_pt": 6, "is_default": 0})
	s2 = st.save_settings(json.dumps(s))
	check("save_round_trip", "40×25" in [x["label_name"] for x in s2["sizes"]] and len(s2["sizes"]) == 4, s2["sizes"])

	frappe.set_user("Guest")
	try:
		st.save_settings(json.dumps(s))
		check("guest_cannot_save", False)
	except frappe.PermissionError:
		check("guest_cannot_save", True)
	frappe.set_user("Administrator")
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
