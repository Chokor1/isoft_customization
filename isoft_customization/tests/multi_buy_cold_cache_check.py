"""Multi-buy right after a site cache clear, in a fresh process (bench console, patches, scripts).

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/multi_buy_cold_cache_check.py dev.isoft.ao
Clears the cache in a child process first: frappe then imports this app while it loads hooks,
the package __init__ cannot wrap ERPNext's rule lookup, and only before_request / before_job
would install it later. The engine must not depend on that. Rolled back.
"""
import os
import subprocess
import sys

import frappe

SITE = sys.argv[1]
subprocess.run([sys.executable, "-c", "import frappe; frappe.init(site=%r, sites_path='.'); frappe.connect(); frappe.clear_cache()" % SITE], check=True)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import multi_buy_fixtures as fx  # noqa: E402

frappe.init(site=SITE, sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:500])
	fails += not cond


try:
	frappe.get_hooks("doc_events")  # loads the app the way a cold process does
	fx.item_group("MB Cold Group")
	fx.item("MB-CC-A", "MB Cold Group", 1000)
	fx.rule("MB cold 1+1", "MB Cold Group", 5).insert()
	fx.rule("MB cold normal 10", "MB Cold Group", 3, multibuy=False, discount_percentage=10).insert()
	d = frappe.get_doc({"doctype": "Quotation", "quotation_to": "Customer", "party_name": "Abbass", "company": fx.COMPANY,
		"transaction_date": frappe.utils.nowdate(), "selling_price_list": fx.PL, "currency": fx.CURRENCY, "conversion_rate": 1,
		"plc_conversion_rate": 1, "order_type": "Sales", "taxes": [dict(fx.IVA_ROW)], "items": [{"item_code": "MB-CC-A", "qty": 2}]})
	d.insert()
	got = [(frappe.utils.flt(r.qty), frappe.utils.flt(r.discount_percentage, 2), bool(r.isoft_multibuy_rule)) for r in d.items]
	check("cold_engine_applies_multibuy", got == [(1, 50, True), (1, 0, True)], got)
	from erpnext.accounts.doctype.pricing_rule import utils as prutils

	check("cold_erpnext_lookup_wrapped_after_engine", prutils._get_pricing_rules.__module__ == "isoft_customization.item_group_and_brand",
		prutils._get_pricing_rules.__module__)
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
