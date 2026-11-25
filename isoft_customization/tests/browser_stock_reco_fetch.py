"""Browser check of Fetch Items from Warehouse with Brand / Item Group (public/js/stock_reconciliation.js).

Builds a NEW Stock Reconciliation in the browser and never saves it.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/browser_stock_reco_fetch.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_target_total as h  # noqa: E402

COMPANY, WAREHOUSE, BRAND, GROUP = "ITEC LDA", "17 - Loja Benguela - ITEC", "HP", "CONSUMIVEIS"
fails = 0


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:400], flush=True)
	fails += not cond


def open_dialog(page):
	page.locator("button:has-text('Fetch Items from Warehouse')").first.click()
	page.wait_for_function("() => window.cur_dialog && cur_dialog.display && cur_dialog.fields_dict.warehouse", timeout=15000)
	page.wait_for_timeout(500)


def fill_and_update(page, values):
	page.evaluate("(v) => Promise.all(Object.keys(v).map(k => cur_dialog.set_value(k, v[k])))", values)
	page.wait_for_timeout(800)
	page.evaluate("() => cur_dialog.get_primary_btn().click()")
	page.wait_for_timeout(500)
	page.wait_for_function("() => !frappe.dom.freeze_count", timeout=60000)
	page.wait_for_timeout(800)


def rows(page):
	return page.evaluate("() => (cur_frm.doc.items || []).filter(r => r.item_code).map(r => r.item_code)")


sid = h.mint_session()
import frappe  # noqa: E402  (connected by mint_session)
from frappe.utils.nestedset import get_descendants_of  # noqa: E402

errors = []
try:
	from playwright.sync_api import sync_playwright

	with sync_playwright() as pw:
		b = pw.chromium.launch()
		ctx = b.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
		ctx.add_cookies([{"name": "sid", "value": sid, "domain": "dev.isoft.ao", "path": "/"}])
		page = ctx.new_page()
		page.on("pageerror", lambda e: errors.append(str(e)[:300]))

		page.goto(h.BASE_URL + "/app/stock-reconciliation/new", wait_until="networkidle")
		page.wait_for_function("() => window.cur_frm && cur_frm.doc.doctype === 'Stock Reconciliation'", timeout=30000)
		page.evaluate("(c) => cur_frm.set_value('company', c)", COMPANY)
		page.wait_for_timeout(1500)

		open_dialog(page)
		fields = page.evaluate("() => cur_dialog.fields.map(f => f.fieldname)")
		check("dialog has Brand and Item Group", {"brand", "item_group"} <= set(fields), fields)
		check("ERPNext's fields are still there", {"warehouse", "item_code", "ignore_empty_stock"} <= set(fields), fields)

		fill_and_update(page, {"warehouse": WAREHOUSE, "brand": BRAND})
		codes = rows(page)
		brands = {c: frappe.db.get_value("Item", c, "brand") for c in set(codes)}
		check("brand fetch fills the table (%d rows)" % len(codes), len(codes) > 10, len(codes))
		check("every row is brand " + BRAND, set(brands.values()) == {BRAND}, set(brands.values()))
		check("rows carry the warehouse and current qty", page.evaluate(
			"(w) => cur_frm.doc.items.every(r => r.warehouse === w && r.current_qty !== undefined)", WAREHOUSE))

		open_dialog(page)
		fill_and_update(page, {"warehouse": WAREHOUSE, "brand": BRAND, "item_group": GROUP})
		codes2 = rows(page)
		groups = set([GROUP] + get_descendants_of("Item Group", GROUP))
		check("brand + item group narrows it (%d rows)" % len(codes2), 0 < len(codes2) < len(codes), len(codes2))
		check("every row is in the group or a sub-group", all(
			frappe.db.get_value("Item", c, "item_group") in groups and frappe.db.get_value("Item", c, "brand") == BRAND for c in codes2))

		# An item of another brand + this brand: nothing matches, the table is left alone.
		other = frappe.db.sql("""select b.item_code from tabBin b join tabItem i on i.name=b.item_code
			where b.warehouse=%s and ifnull(i.brand,'')!=%s and i.disabled=0 limit 1""", (WAREHOUSE, BRAND))[0][0]
		open_dialog(page)
		fill_and_update(page, {"warehouse": WAREHOUSE, "item_code": other, "brand": BRAND})
		msg = page.evaluate("() => $('.modal.show .msgprint').text().trim()")
		check("no match: says so", "No items found" in msg or "Nenhum artigo" in msg, msg)
		check("no match: table untouched", rows(page) == codes2, len(rows(page)))

		check("no page errors", not errors, errors)
		b.close()
finally:
	h.drop_session(sid)

print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
