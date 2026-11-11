"""POS Customer Contacts report check (read-only, dev data).

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/pos_customer_contacts_check.py dev.isoft.ao
"""
import sys

import frappe
from frappe.utils import flt

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0
COMPANY, FROM, TO = "ITEC LDA", "2020-01-01", "2030-12-31"


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:500])
	fails += not cond


try:
	from isoft_customization.isoft_customization.report.pos_customer_contacts.pos_customer_contacts import execute

	base = {"company": COMPANY, "from_date": FROM, "to_date": TO}
	cols, data = execute(frappe._dict(base, show="Amount"))[:2]
	names = [c["fieldname"] for c in cols]
	profiles = frappe.get_all("POS Profile", filters={"company": COMPANY}, pluck="name")
	prof_cols = [c for c in cols if c["fieldname"].startswith("pos_")]
	check("one_column_per_profile", sorted(c["label"] for c in prof_cols if c["fieldname"] != "pos__desk")
		== sorted(profiles), [c["label"] for c in prof_cols])
	check("desk_column", "pos__desk" in names)
	for f in ("customer", "customer_name", "phone", "email", "total_amount", "total_qty", "invoices", "last_purchase"):
		check("column_" + f, f in names, names)
	check("rows_have_contact", data and all(r.get("phone") or r.get("email") for r in data), data[:3])
	check("sorted_by_amount", [r["total_amount"] for r in data] == sorted([r["total_amount"] for r in data], reverse=True))

	# totals against plain SQL for one profile/customer
	row = next((r for r in data if any(flt(r.get(c["fieldname"])) for c in prof_cols if c["fieldname"] != "pos__desk")), None)
	if row:
		col = next(c for c in prof_cols if c["fieldname"] != "pos__desk" and flt(row.get(c["fieldname"])))
		sql = frappe.db.sql("""select sum(base_grand_total) from `tabSales Invoice` where docstatus=1 and company=%s
			and customer=%s and pos_profile=%s and posting_date between %s and %s""", (COMPANY, row["customer"], col["label"], FROM, TO))[0][0]
		check("profile_amount_matches_sql", abs(flt(sql) - flt(row[col["fieldname"]])) < 0.01, (sql, row[col["fieldname"]]))
		check("total_is_sum_of_columns", abs(sum(flt(row.get(c["fieldname"])) for c in prof_cols) - flt(row["total_amount"])) < 0.05, row)

	cols_q, data_q = execute(frappe._dict(base, show="Qty"))[:2]
	check("qty_mode_float", all(c["fieldtype"] == "Float" for c in cols_q if c["fieldname"].startswith("pos_")))
	cols_y, data_y = execute(frappe._dict(base, show="Yes/No"))[:2]
	vals = {r.get(c["fieldname"]) for r in data_y for c in cols_y if c["fieldname"].startswith("pos_")}
	check("yes_no_mode", vals <= {"Yes", "No", "", None} and "Yes" in vals, vals)

	one = profiles[0]
	cols_1, data_1 = execute(frappe._dict(base, show="Amount", pos_profiles=[one], include_desk=0))[:2]
	check("profile_filter_columns", [c["label"] for c in cols_1 if c["fieldname"].startswith("pos_")] == [one], [c["label"] for c in cols_1])
	# every row bought at that profile (a sale fully returned nets to 0 but is still a customer there)
	check("profile_filter_rows", data_1 and all(("pos_" + frappe.scrub(one)) in r and r["invoices"] > 0 for r in data_1), data_1[:3])

	_c, data_all = execute(frappe._dict(base, show="Amount", contact="Any"))[:2]
	check("any_contact_shows_more", len(data_all) >= len(data), (len(data_all), len(data)))
	_c, data_phone = execute(frappe._dict(base, show="Amount", contact="Phone"))[:2]
	check("phone_filter", all(r.get("phone") for r in data_phone))

	_c, data_narrow = execute(frappe._dict(base, from_date="2099-01-01", to_date="2099-12-31"))[:2]
	check("date_filter", data_narrow == [], data_narrow[:2])
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
