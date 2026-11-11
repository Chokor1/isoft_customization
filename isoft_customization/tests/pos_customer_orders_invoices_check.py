"""POS Awesome Customer Orders lists Sales Invoices that reserve stock (read-only, no pull).

Fixtures are db_insert'ed submitted invoices for the "Loja Talatona" POS Profile (NDA); rolled back.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/pos_customer_orders_invoices_check.py dev.isoft.ao
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
PROFILE = "Loja Talatona"

try:
	from posawesome.posawesome.api import customer_orders as co

	from isoft_customization.invoice_reservation import invoice_reserved_qty

	before = co.count_open_customer_orders(PROFILE)
	item = fx.stock_item("IR-T5-A")
	other = fx.stock_item("IR-T5-B")
	s = fx.si([fx.line(item, 7, delivered_qty=2, rate=1000, amount=7000), fx.line(other, 1)])
	frappe.db.set_value("Sales Invoice", s["name"], {"posting_date": frappe.utils.nowdate(), "grand_total": 9000,
		"currency": "AKZ", "customer_name": fx.CUSTOMER}, update_modified=False)

	rows = co.search_customer_orders(PROFILE, status="open")
	mine = [r for r in rows if r.get("name") == s["name"]]
	check("pos_lists_invoice", len(mine) == 1 and mine[0].get("doctype") == "Sales Invoice", mine)
	check("pos_orders_keep_doctype", all(r.get("doctype") in ("Sales Order", "Sales Invoice") for r in rows),
		{r.get("doctype") for r in rows})

	rows = co.search_customer_orders(PROFILE, item_code=item, status="open")
	mine = [r for r in rows if r.get("name") == s["name"]]
	check("pos_item_pending", len(mine) == 1 and mine[0].item_pending == 5 == invoice_reserved_qty(item, fx.WH),
		(mine, invoice_reserved_qty(item, fx.WH)))

	rows = co.search_customer_orders(PROFILE, txt="Boa Vida", status="open")
	check("pos_txt_filter", any(r.get("name") == s["name"] for r in rows))
	rows = co.search_customer_orders(PROFILE, txt="no such customer zzz", status="open")
	check("pos_txt_filter_excludes", not any(r.get("name") == s["name"] for r in rows))

	check("pos_count", co.count_open_customer_orders(PROFILE) == before + 1, (before, co.count_open_customer_orders(PROFILE)))

	lines = co.get_customer_order_items(PROFILE, s["name"], doctype="Sales Invoice")
	by = {l.item_code: l for l in lines}
	check("pos_invoice_lines", set(by) == {item, other} and by[item].pending == 5 and by[item].delivered_qty == 2,
		lines)

	fx.set_doc(s["name"], isoft_reservation_stopped=1)
	rows = co.search_customer_orders(PROFILE, status="open")
	check("pos_not_listed_when_stopped", not any(r.get("name") == s["name"] for r in rows))
	check("pos_count_stopped", co.count_open_customer_orders(PROFILE) == before)

	rows = co.search_customer_orders(PROFILE, status="all")
	mine = [r for r in rows if r.get("name") == s["name"]]
	check("pos_all_shows_stopped", len(mine) == 1 and mine[0].status == "Stopped", mine)

	# one line fully delivered (4/4), one with 1 of 4 delivered -> 5 of 8 delivered overall = 62.5%
	s2 = fx.si([fx.line(item, 4, delivered_qty=4), fx.line(other, 4, delivered_qty=1)])
	frappe.db.set_value("Sales Invoice", s2["name"], {"posting_date": frappe.utils.nowdate(), "grand_total": 1,
		"currency": "AKZ", "customer_name": fx.CUSTOMER}, update_modified=False)
	rows = co.search_customer_orders(PROFILE, status="open")
	mine = [r for r in rows if r.get("name") == s2["name"]]
	check("pos_per_delivered_all_lines", len(mine) == 1 and abs(mine[0].per_delivered - 62.5) < 1e-6, mine)

	# the badge query must not scan every Sales Invoice
	plan = frappe.db.sql("""explain select si.name from `tabSales Invoice` si
		where si.company = %s and si.isoft_reserve_stock = 1 and si.docstatus = 1""", fx.COMPANY, as_dict=True)
	check("pos_badge_uses_index", plan and plan[0].get("type") != "ALL", plan)

	so_rows = co.search_customer_orders(PROFILE, status="open")
	check("pos_sales_orders_still_listed", all(r.get("doctype") == "Sales Order" for r in so_rows
		if r.get("name") not in (s["name"], s2["name"])))
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.destroy()
	sys.exit(1 if state["fails"] else 0)
