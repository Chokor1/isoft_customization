"""Multi-buy Pricing Rule: fields, validation, ERPNext lookup exclusion, conflicts. Rolled back.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/multi_buy_rule_check.py dev.isoft.ao
"""
import sys

import frappe

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0
COMPANY, PL = "ITEC LDA", "Standard Selling"


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:500])
	fails += not cond


def throws(fn):
	try:
		fn()
		return False
	except frappe.ValidationError:
		return True


try:
	import os

	sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
	import multi_buy_fixtures as fx

	fx.item_group("MB Test Group")
	fx.item("MB-T-A", "MB Test Group", 1000)

	def rule(**kw):
		d = frappe.get_doc(dict({"doctype": "Pricing Rule", "title": "MB test", "apply_on": "Item Group",
			"item_groups": [{"item_group": "MB Test Group"}], "selling": 1, "company": COMPANY, "currency": "AKZ",
			"applicable_for": "Customer Group", "customer_group": "All Customer Groups", "priority": "5",
			"isoft_multibuy": 1, "isoft_buy_qty": 2, "isoft_get_qty": 1, "isoft_multibuy_discount": 30,
			"rate_or_discount": "Discount Percentage", "discount_percentage": 30}, **kw))
		d.flags.ignore_permissions = True
		return d

	mb = rule().insert()
	mb.reload()
	check("standard_discount_zeroed", mb.discount_percentage == 0 and (mb.rate or 0) == 0 and mb.rate_or_discount == "Discount Percentage"
		and mb.selling == 1 and mb.buying == 0 and mb.price_or_product_discount == "Price", mb.as_dict())
	check("buy_qty_required", throws(lambda: rule(isoft_buy_qty=0, title="MB bad1").insert()))
	check("get_qty_required", throws(lambda: rule(isoft_get_qty=0, title="MB bad2").insert()))
	check("discount_positive", throws(lambda: rule(isoft_multibuy_discount=0, title="MB bad3").insert()))
	check("discount_max_100", throws(lambda: rule(isoft_multibuy_discount=101, title="MB bad4").insert()))
	check("no_transaction", throws(lambda: rule(apply_on="Transaction", item_groups=[], title="MB bad5").insert()))

	from erpnext.stock.get_item_details import get_item_details

	# as every desk / POS request does (a raw process right after a cache clear has no wrapper
	# until then; multi_buy_cold_cache_check covers the engine in that state)
	for method in frappe.get_hooks("before_request"):
		frappe.get_attr(method)()

	out = get_item_details({"doctype": "Sales Invoice", "item_code": "MB-T-A", "company": COMPANY, "selling_price_list": PL,
		"price_list_currency": "AKZ", "currency": "AKZ", "conversion_rate": 1, "plc_conversion_rate": 1, "qty": 3,
		"customer_group": "All Customer Groups", "territory": "All Territories", "transaction_date": frappe.utils.nowdate()})
	check("erpnext_lookup_skips_multibuy", not out.get("pricing_rules") and not out.get("discount_percentage"),
		(out.get("pricing_rules"), out.get("discount_percentage")))

	from erpnext.accounts.doctype.pricing_rule import utils as prutils

	from isoft_customization.multi_buy_rule import multibuy_lookup

	args = frappe._dict({"item_code": "MB-T-A", "item_group": "MB Test Group", "company": COMPANY, "transaction_type": "selling",
		"customer_group": "All Customer Groups", "territory": "All Territories", "currency": "AKZ", "price_list": PL,
		"transaction_date": frappe.utils.nowdate()})
	with multibuy_lookup():
		inside = [r.name for r in prutils._get_pricing_rules("Item Group", args, {})]
	outside = [r.name for r in prutils._get_pricing_rules("Item Group", args, {})]
	check("lookup_flag_only_multibuy", mb.name in inside, inside)
	check("lookup_default_never_multibuy", mb.name not in outside, outside)

	from isoft_customization.pricing_rule_conflicts import find_conflicts

	normal = frappe.get_doc({"doctype": "Pricing Rule", "title": "MB normal", "apply_on": "Item Group",
		"item_groups": [{"item_group": "MB Test Group"}], "selling": 1, "company": COMPANY, "currency": "AKZ",
		"applicable_for": "Customer Group", "customer_group": "All Customer Groups", "priority": "5",
		"rate_or_discount": "Discount Percentage", "discount_percentage": 10})
	check("conflict_same_priority", bool(find_conflicts(normal)), find_conflicts(normal))
	normal.priority = "3"
	check("no_conflict_other_priority", not find_conflicts(normal), find_conflicts(normal))

	hundred = rule(isoft_multibuy_discount=100, title="MB 100", priority="7").insert()
	check("hundred_flagged", "verify with AGT" in (hundred.rule_description or ""), hundred.rule_description)
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
