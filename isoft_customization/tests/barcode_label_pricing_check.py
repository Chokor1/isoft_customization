"""Barcode Label Studio pricing check. Creates throwaway Pricing Rules, rolls everything back.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/barcode_label_pricing_check.py dev.isoft.ao
Data (dev.isoft.ao): Test-05-11-2026 has TESTE-A..E UOM prices 1000..5000 on Standard Selling and the
NORMAL IVA item tax (14%, category Angola IVA); PAP-A4 has a PCS price only and a Box barcode (factor 5).
"""
import sys

import frappe

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0

ITEM, COMPANY, PL = "Test-05-11-2026", "ITEC LDA", "Standard Selling"
STORE, OTHER_STORE = "01 - Loja Alvalade - ITEC", "07 - Maculusso Armazem - ITEC"
BC_A, BC_B = "1691828500001", "1691828500002"  # TESTE-A 1000, TESTE-B 2000


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else detail)
	fails += not cond


def rule(title, pct, priority, **kw):
	doc = frappe.get_doc({
		"doctype": "Pricing Rule", "title": title, "apply_on": "Item Code", "items": [{"item_code": ITEM}],
		"selling": 1, "company": COMPANY, "currency": "AKZ", "rate_or_discount": "Discount Percentage",
		"discount_percentage": pct, "priority": str(priority), "price_or_product_discount": "Price", **kw,
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def counts():
	return {dt: frappe.db.count(dt) for dt in ("Sales Invoice", "Quotation", "Sales Order")}


before = counts()
try:
	from isoft_customization.barcode_labels.pricing import price_rows

	def one(barcode=BC_A, item=ITEM, uom=None, **opts):
		o = {"price_list": PL, "company": COMPANY}
		o.update(opts)
		return price_rows([{"item_code": item, "barcode": barcode, "uom": uom}], o)[0]

	base = one()
	print("INFO baseline TESTE-A:", {k: base.get(k) for k in ("uom", "price_list_rate", "discount_percentage", "final_price")})
	check("resolves_barcode_uom", base["uom"] == "TESTE-A", base)
	check("uom_without_conversion_row", one(BC_B)["price_list_rate"] == 2000, one(BC_B))

	rule("BLS test all groups 10", 10, 11, applicable_for="Customer Group", customer_group="All Customer Groups")
	r = one()
	check("rule_discount_applied", r["final_price"] == 900 and r["discount_source"] == "rule", r)
	check("has_price", r["has_price"] is True)

	rule("BLS test Abbass 20", 20, 19, applicable_for="Customer", customer="Abbass")
	check("customer_only_rule_ignored", one()["final_price"] == 900, one())

	rule("BLS test Individual 30", 30, 15, applicable_for="Customer Group", customer_group="Individual")
	check("group_rule_not_without_group", one()["final_price"] == 900, one())
	check("group_rule_only_when_picked", one(customer_group="Individual")["final_price"] == 700, one(customer_group="Individual"))

	rule("BLS test store 15", 15, 13, applicable_for="Customer Group", customer_group="All Customer Groups", warehouse=STORE)
	check("warehouse_rule_with_store", one(warehouse=STORE)["final_price"] == 850, one(warehouse=STORE))
	check("warehouse_rule_other_store", one(warehouse=OTHER_STORE)["final_price"] == 900, one(warehouse=OTHER_STORE))
	nw = one()
	check("warehouse_rule_needs_warehouse", nw["discount_percentage"] == 0 and nw["final_price"] == 1000, nw)

	frappe.db.set_value("Item Barcode", {"barcode": BC_A, "parent": ITEM}, "discount", 5, update_modified=False)
	bd = one(warehouse=STORE)
	check("barcode_discount_replaces_rule", bd["discount_percentage"] == 5 and bd["final_price"] == 950 and bd["discount_source"] == "barcode", bd)
	frappe.db.set_value("Item Barcode", {"barcode": BC_A, "parent": ITEM}, "discount", 0, update_modified=False)

	box = one("5602024006119", item="PAP-A4")
	pcs = frappe.db.get_value("Item Price", {"item_code": "PAP-A4", "price_list": PL, "uom": "PCS"}, "price_list_rate")
	check("barcode_uom_price", box["uom"] == "Box" and abs(box["price_list_rate"] - pcs * 5) < 0.01, (box, pcs))

	np = one("5099206012141", item="MSE-LOG-M185", price_list="Special Price")
	check("no_price_row", np["has_price"] is False and np["final_price"] is None, np)

	tx = one(warehouse=OTHER_STORE, include_tax=1, tax_category="Angola IVA")
	check("tax_on_top", tx["tax_rate"] == 14 and tx["final_price"] == 1026, tx)
	check("no_tax_without_switch", one(warehouse=OTHER_STORE, tax_category="Angola IVA")["final_price"] == 900)

	nb = price_rows([{"item_code": ITEM, "barcode": None, "uom": None}], {"price_list": PL, "company": COMPANY})[0]
	check("no_barcode_row_uses_stock_uom", nb["uom"] == "PCS", nb)
	from isoft_customization.barcode_labels import pricing as pr

	check("root_lookup", pr._root("Customer Group", "X") == "All Customer Groups" and pr._root("Territory", "X") == "All Territories",
		(pr._root("Customer Group", "X"), pr._root("Territory", "X")))

	dis = price_rows([{"item_code": "7EH98AA", "barcode": "6955914606104", "uom": None}, {"item_code": ITEM, "barcode": BC_B, "uom": None}],
		{"price_list": PL, "company": COMPANY, "warehouse": OTHER_STORE})
	check("disabled_row_does_not_break_batch", len(dis) == 2 and dis[0]["has_price"] is False and dis[0].get("error") and dis[1]["price_list_rate"] == 2000, dis)

	rate = rule("BLS test store rate 500", 0, 17, applicable_for="Customer Group", customer_group="All Customer Groups", warehouse=STORE)
	rate.rate_or_discount, rate.rate = "Rate", 500
	rate.save()
	check("store_rate_rule_with_store", one(warehouse=STORE)["final_price"] == 500, one(warehouse=STORE))
	nr = one()
	check("store_rate_rule_needs_store", nr["price_list_rate"] == 1000 and nr["final_price"] == 1000, nr)

	rule("BLS test all stores 25", 25, 18, applicable_for="Customer Group", customer_group="All Customer Groups", warehouse="All Warehouses - ITEC")
	check("all_stores_root_rule_kept", one()["final_price"] == 750, one())

	check("nothing_written", counts() == before, (before, counts()))
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
