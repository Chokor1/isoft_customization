"""Acceptance check for overrides/stock_analytics.py (erpnext 008f2a6b6 backport).

Runs against a live site. Everything it creates is rolled back at the end; a commit
attempt aborts the run. Each case submits Material Receipts for a fresh item, then runs
Stock Analytics through erpnext's own execute() -- patched -- and through an untouched
copy of the installed report module, which shows the 0s the backport removes.

    cd sites && ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/stock_analytics_opening_check.py \
        [--site dev.isoft.ao] [--company "TEST 2"]

Not a run-tests suite on purpose: on dev.isoft.ao run-tests commits fixtures and
ERPNext's before_tests deletes data.
"""
import argparse
import importlib
import importlib.util
import sys
import traceback

import frappe
from frappe.utils import add_years, getdate, random_string

ap = argparse.ArgumentParser()
ap.add_argument("--site", default="dev.isoft.ao")
ap.add_argument("--company", default="TEST 2")
args = ap.parse_args()

frappe.init(site=args.site, sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
frappe.set_user("Administrator")


class CommitAttempted(Exception):
	pass


def _no_commit(*args, **kwargs):
	raise CommitAttempted("something tried to commit during the check")


frappe.db.commit = _no_commit

import erpnext.accounts.general_ledger as general_ledger  # noqa: E402
from erpnext.accounts.utils import get_fiscal_year  # noqa: E402

# The cases need receipts dated before the report range; dev.isoft.ao freezes accounts
# (Accounts Settings acc_frozen_upto). In this process only, and everything rolls back.
general_ledger.check_freezing_date = lambda *args, **kwargs: None

import isoft_customization.overrides.stock_analytics as backport  # noqa: E402

MODULE = backport.MODULE
sa = importlib.import_module(MODULE)

# A private copy of the installed report, never patched: the "before" numbers.
_spec = importlib.util.spec_from_file_location("stock_analytics_upstream", sa.__file__)
upstream = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(upstream)

TAG = "SA-TEST-" + random_string(5).upper()
C = args.company
WH = frappe.db.get_value("Warehouse", {"company": C, "is_group": 0, "disabled": 0, "warehouse_name": "Stores"}) or (
	frappe.db.sql("select name from tabWarehouse where company=%s and is_group=0 and disabled=0 order by name limit 1", C)[0][0]
)
IVA_TEMPLATE = frappe.db.get_value("Item Tax Template", {"tax_type": "IVA", "company": C}) or frappe.db.get_value(
	"Item Tax Template", {"tax_type": "IVA"}
)
results = []


def check(case, label, ok, detail=""):
	results.append((case, label, bool(ok), detail))
	print("{:<8} {:<4} {}{}".format(case, "PASS" if ok else "FAIL", label, (" -- " + detail) if detail else ""))


def make_item(code):
	item = frappe.get_doc({
		"doctype": "Item", "item_code": code, "item_name": code, "item_group": "All Item Groups",
		"stock_uom": "Nos", "is_stock_item": 1, "include_item_in_manufacturing": 0,
		# dev.isoft.ao's "Item Validation" Server Script refuses items without an IVA template
		"taxes": [{"item_tax_template": IVA_TEMPLATE}] if IVA_TEMPLATE else [],
	})
	item.flags.ignore_mandatory = True
	return item.insert().name


def receive(item, qty, posting_date, rate=100):
	se = frappe.get_doc({
		"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "purpose": "Material Receipt",
		"company": C, "set_posting_time": 1, "posting_date": posting_date, "posting_time": "10:00:00",
		"items": [{
			"item_code": item, "qty": qty, "uom": "Nos", "conversion_factor": 1, "basic_rate": rate,
			"t_warehouse": WH,
			"expense_account": frappe.get_cached_value("Company", C, "stock_adjustment_account"),
			"cost_center": frappe.get_cached_value("Company", C, "cost_center"),
		}],
	})
	se.insert()
	se.submit()
	return se.name


def run(module, item, from_date, to_date, range_, value_quantity="Quantity"):
	filters = {
		"company": C, "from_date": from_date, "to_date": to_date, "range": range_,
		"value_quantity": value_quantity, "item_code": item, "warehouse": WH,
	}
	columns, data = module.execute(filters)[:2]
	periods = [c["fieldname"] for c in columns[5:] if c.get("fieldname") != "barcode"]
	row = next((r for r in data if r.get("name") == item), {})
	return [row.get(p) for p in periods], periods


def case(name, item, from_date, to_date, range_, expected, value_quantity="Quantity"):
	got, periods = run(sa, item, from_date, to_date, range_, value_quantity)
	before, _ = run(upstream, item, from_date, to_date, range_, value_quantity)
	check(name, "{} {} {}..{} = {}".format(range_, value_quantity, from_date, to_date, expected),
		got == expected, "got {} for {}; unpatched report gives {}".format(got, periods, before))
	check(name, "unpatched report shows the bug (differs)", before != expected, "unpatched {}".format(before))


try:
	# --- wiring --------------------------------------------------------------
	path = "isoft_customization.overrides.stock_analytics.apply"
	check("hooks", "before_request lists apply()", path in frappe.get_hooks("before_request"))
	check("hooks", "before_job lists apply()", path in frappe.get_hooks("before_job"))
	# exactly how frappe.utils.background_jobs.execute_job calls it
	frappe.call(path, method="frappe.ping", kwargs={}, transaction_type="job")
	frappe.call(path)
	frappe.call(path)
	check("apply", "patched and idempotent", sa.get_data is backport.get_data
		and sa.get_periodic_data is backport.get_periodic_data)

	# once ERPNext ships the fix, apply() must leave the module alone
	sa.get_data, sa.get_periodic_data = upstream.get_data, upstream.get_periodic_data
	sa.OPENING_KEY = "_opening"
	try:
		applied = backport.apply()
		check("apply", "stands down when erpnext defines OPENING_KEY",
			applied is False and sa.get_data is upstream.get_data)
	finally:
		del sa.OPENING_KEY
		backport.apply()

	# --- Yearly: stock received only in the previous fiscal year --------------
	today = getdate()
	cur_fy = get_fiscal_year(today, company=C)
	prev_fy = get_fiscal_year(add_years(today, -1), company=C)
	item = make_item(TAG + "-Y")
	receive(item, 7, prev_fy[1])
	case("yearly", item, cur_fy[1], cur_fy[2], "Yearly", [7.0])

	# --- Monthly: the upstream test -----------------------------------------
	item = make_item(TAG + "-M")
	receive(item, 10, "2026-04-15")
	receive(item, 5, "2026-08-10")
	case("monthly", item, "2026-06-01", "2026-08-28", "Monthly", [10.0, 10.0, 15.0])

	# --- Value: the opening stock value carries in ---------------------------
	item = make_item(TAG + "-V")
	receive(item, 4, "2026-04-15", rate=250)
	receive(item, 2, "2026-08-10", rate=250)
	case("value", item, "2026-06-01", "2026-08-28", "Monthly", [1000.0, 1000.0, 1500.0], "Value")
	item = make_item(TAG + "-VY")
	receive(item, 3, prev_fy[1], rate=200)
	case("value", item, cur_fy[1], cur_fy[2], "Yearly", [600.0], "Value")

except Exception:
	traceback.print_exc()
	check("run", "check completed without an exception", False)

finally:
	frappe.db.rollback()
	left = frappe.db.count("Item", {"item_code": ["like", TAG + "%"]})
	check("cleanup", "rollback left nothing behind", left == 0, "items left={}".format(left))

failed = [r for r in results if not r[2]]
print("\n{} checks, {} failed".format(len(results), len(failed)))
frappe.destroy()
sys.exit(1 if failed else 0)
