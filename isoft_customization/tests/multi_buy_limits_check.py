"""Multi-buy discounts vs discount limits (isoft_customization per-user limits and POS Awesome cashier
limits). Settings and the POS Profile User row are changed inside the transaction and rolled back.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/multi_buy_limits_check.py dev.isoft.ao
"""
import os
import sys

import frappe

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import multi_buy_fixtures as fx  # noqa: E402

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0
G = "MB Lim Group"


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:500])
	fails += not cond


def raises(fn):
	try:
		fn()
		return None
	except frappe.ValidationError as e:
		return str(e) or "error"


def row(code, pct, rule=None, **kw):
	plr = 10000.0
	rate = plr * (1 - pct / 100.0)
	return frappe._dict(dict({"item_code": code, "qty": 2, "price_list_rate": plr, "rate": rate, "discount_percentage": pct,
		"discount_amount": plr - rate, "pricing_rules": "", "isoft_multibuy_rule": rule, "isoft_multibuy_pct": pct if rule else 0,
		"isoft_multibuy_units": 1 if rule else 0, "idx": 1}, **kw))


try:
	fx.item_group(G)
	fx.item("MB-L-A", G, 10000)
	fx.item("MB-L-B", G, 10000)
	rule = fx.rule("MB lim", G, 5).insert()

	# ---- isoft_customization per-user limits: nobody has a row, fallback 0%
	s = frappe.get_single("Sales Discount Limit Settings")
	s.enabled = 1
	s.users_without_limit = "No discount allowed (0%)"
	s.check_quotation = 1
	s.save()
	from isoft_customization.discount_limits import validate_discounts

	def quote(rows):
		return frappe._dict({"doctype": "Quotation", "owner": "Administrator", "is_pos": 0, "is_return": 0, "items": rows})

	err = raises(lambda: validate_discounts(quote([row("MB-L-A", 25, rule.name)])))
	check("user_limit_exempts_multibuy", err is None, err)
	err = raises(lambda: validate_discounts(quote([row("MB-L-A", 30, rule.name, isoft_multibuy_pct=25)])))
	check("user_limit_blocks_extra_on_multibuy_row", err is not None)
	err = raises(lambda: validate_discounts(quote([row("MB-L-A", 25, rule.name), row("MB-L-B", 5, idx=2)])))
	check("user_limit_still_blocks_manual", err is not None and "MB-L-B" in err, err)

	# ---- POS Awesome cashier limit: Administrator at 10% on Alvalade
	prof = frappe.get_doc("POS Profile", "Alvalade")
	u = prof.append("applicable_for_users", {"user": "Administrator", "max_discount_allowed": 10})
	u.parent, u.parenttype, u.parentfield, u.idx = prof.name, "POS Profile", "applicable_for_users", 99
	u.db_insert()
	frappe.clear_document_cache("POS Profile", "Alvalade")
	from posawesome.posawesome.api.discounts import check_discount_limits

	def pos(rows):
		return frappe._dict({"doctype": "Sales Invoice", "is_pos": 1, "is_return": 0, "pos_profile": "Alvalade", "items": rows})

	err = raises(lambda: check_discount_limits(pos([row("MB-L-A", 50, rule.name)]), {}))
	check("pos_cashier_limit_exempts_multibuy", err is None, err)
	err = raises(lambda: check_discount_limits(pos([row("MB-L-B", 15)]), {}))
	check("pos_cashier_limit_still_blocks_manual", err is not None, err)
	err = raises(lambda: check_discount_limits(pos([row("MB-L-A", 60, rule.name, isoft_multibuy_pct=50)]), {}))
	check("pos_cashier_limit_blocks_extra_on_multibuy_row", err is not None, err)
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.clear_document_cache("POS Profile", "Alvalade")
	frappe.clear_document_cache("Sales Discount Limit Settings", "Sales Discount Limit Settings")
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
