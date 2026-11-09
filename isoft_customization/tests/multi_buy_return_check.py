"""Multi-buy partial-return guard. Original invoices and earlier returns are written with db_insert as
submitted fixtures (no hooks, no GL); return drafts come from ERPNext's make_sales_return and are
only validated. Everything is rolled back.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/multi_buy_return_check.py dev.isoft.ao
"""
import os
import sys

import frappe
from frappe.utils import nowdate

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import multi_buy_fixtures as fx  # noqa: E402

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0
G = "MB Ret Group"
seq = [0]


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:600])
	fails += not cond


def original(rule, lines):
	"""lines: [(item_code, qty, plr, rate, discounted_units)] -> submitted Sales Invoice fixture."""
	seq[0] += 1
	d = frappe.get_doc({"doctype": "Sales Invoice", "customer": "Abbass", "company": fx.COMPANY, "posting_date": nowdate(),
		"due_date": nowdate(), "selling_price_list": fx.PL, "currency": fx.CURRENCY, "conversion_rate": 1, "plc_conversion_rate": 1,
		"taxes": [dict(fx.IVA_ROW)],
		"items": [{"item_code": c, "qty": q, "uom": "Nos", "conversion_factor": 1, "stock_qty": q, "price_list_rate": plr, "rate": rate,
			"discount_percentage": round(100.0 * (plr - rate) / plr, 2), "isoft_multibuy_rule": rule, "isoft_multibuy_units": u,
			"isoft_multibuy_pct": round(100.0 * (plr - rate) / plr, 2)} for c, q, plr, rate, u in lines]})
	d._action = "save"
	d.set_missing_values()
	for row, (_c, q, plr, rate, u) in zip(d.items, lines):
		row.price_list_rate, row.rate, row.qty, row.stock_qty = plr, rate, q, q
	d.name = "MB-RET-ORIG-%d" % seq[0]
	d.docstatus = 1
	d.db_insert()
	for i, row in enumerate(d.items, 1):
		row.parent, row.parenttype, row.parentfield, row.idx, row.docstatus = d.name, "Sales Invoice", "items", i, 1
		row.name = "%s-r%d" % (d.name, i)
		row.db_insert()
	return d


def submitted_return(orig, returned):
	"""returned: {item_code: qty} -> submitted return fixture."""
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

	r = make_sales_return(orig.name)
	r.items = [it for it in r.items if it.item_code in returned]
	for it in r.items:
		it.qty = -returned[it.item_code]
	seq[0] += 1
	r.name = "MB-RET-RET-%d" % seq[0]
	r.docstatus = 1
	r.db_insert()
	for i, row in enumerate(r.items, 1):
		row.parent, row.parenttype, row.parentfield, row.idx, row.docstatus = r.name, "Sales Invoice", "items", i, 1
		row.name = "%s-r%d" % (r.name, i)
		row.db_insert()
	return r


def draft_return(orig, returned):
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

	r = make_sales_return(orig.name)
	r.items = [it for it in r.items if it.item_code in returned]
	for it in r.items:
		it.qty = -returned[it.item_code]
	return r


def outcome(r):
	from isoft_customization.multi_buy import validate_return

	try:
		validate_return(r)
		return "ok"
	except frappe.ValidationError as e:
		return "refused: " + str(e)


try:
	fx.item_group(G)
	fx.item("MB-R-A", G, 10000)
	fx.item("MB-R-C", G, 3000)
	strict = fx.rule("MB ret strict", G, 5).insert()
	loose = fx.rule("MB ret loose", G, 4, isoft_allow_partial_return=1).insert()

	o = original(strict.name, [("MB-R-A", 1, 10000, 10000, 0), ("MB-R-C", 1, 3000, 1500, 1)])
	res = outcome(draft_return(o, {"MB-R-A": 1}))
	check("not_allowed_paying_unit_only_refused", res.startswith("refused") and "MB-R-C" in res, res)
	check("not_allowed_both_ok", outcome(draft_return(o, {"MB-R-A": 1, "MB-R-C": 1})) == "ok")
	check("returning_discounted_unit_alone_ok", outcome(draft_return(o, {"MB-R-C": 1})) == "ok")

	o2 = original(loose.name, [("MB-R-A", 1, 10000, 10000, 0), ("MB-R-C", 1, 3000, 1500, 1)])
	check("allowed_partial_ok", outcome(draft_return(o2, {"MB-R-A": 1})) == "ok")

	o3 = original(strict.name, [("MB-R-A", 2, 10000, 10000, 0), ("MB-R-C", 2, 3000, 1500, 2)])
	submitted_return(o3, {"MB-R-C": 1})
	check("second_partial_counts_first", outcome(draft_return(o3, {"MB-R-A": 1})) == "ok", outcome(draft_return(o3, {"MB-R-A": 1})))
	check("second_partial_still_guarded", outcome(draft_return(o3, {"MB-R-A": 2})).startswith("refused"))

	# wiring: the validate hook (release) runs the guard on returns
	from isoft_customization.multi_buy import release

	r = draft_return(o, {"MB-R-A": 1})
	try:
		release(r)
		check("release_runs_guard", False, "no error")
	except frappe.ValidationError:
		check("release_runs_guard", True)
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
