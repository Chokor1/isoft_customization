"""Scanning a barcode into a Sales Invoice must not leave the line at a 100% discount.

ERPNext v13's scan loaded the item twice (item code, then the barcode's own handler);
the queued "rate" handler then ran on the second reply's rate 0 -> discount 100% (o-index,
2026-11-25). barcode_uom_scan.js puts the barcode on the row first so the item loads once.
Nothing is saved.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/scan_no_full_discount_check.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_target_total as h  # noqa: E402

CUSTOMER = "FERPINTA ANGOLA"
# (barcode, item): no barcode UOM, a barcode UOM (PCS), the same barcode again (qty 2), a Box barcode
SCANS = [("5099206012141", "MSE-LOG-M185"), ("3664768009919", "ROL-TR57"),
	("3664768009919", "ROL-TR57"), ("5602024006119", "PAP-A4")]
fails = 0


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:400], flush=True)
	fails += not cond


sid = h.mint_session()
errors = []
try:
	from playwright.sync_api import sync_playwright

	with sync_playwright() as pw:
		b = pw.chromium.launch()
		ctx = b.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
		ctx.add_cookies([{"name": "sid", "value": sid, "domain": "dev.isoft.ao", "path": "/"}])
		page = ctx.new_page()
		page.on("pageerror", lambda e: errors.append(str(e)[:300]))
		calls = []
		page.on("request", lambda r: calls.append(1) if "get_item_details.get_item_details" in (r.url + (r.post_data or "")) else None)
		page.goto(h.BASE_URL + "/app/sales-invoice/new", wait_until="networkidle")
		page.wait_for_function("() => window.cur_frm && cur_frm.doc.doctype === 'Sales Invoice'", timeout=30000)
		page.wait_for_timeout(1500)
		page.evaluate("(c) => { cur_frm.set_value('update_stock', 0); cur_frm.set_value('customer', c); }", CUSTOMER)
		page.wait_for_timeout(2500)
		inp = page.locator('input[data-fieldname="scan_barcode"]').first
		for n, (barcode, item) in enumerate(SCANS, 1):
			calls.clear()
			inp.click()
			inp.type(barcode, delay=5)
			inp.press("Enter")
			page.wait_for_timeout(5000)
			rows = page.evaluate("""(it) => cur_frm.doc.items.filter(r => r.item_code === it).map(r =>
				({qty: r.qty, uom: r.uom, plr: r.price_list_rate, rate: r.rate, disc: r.discount_percentage, barcode: r.barcode}))""", item)
			ok = rows and all(r["plr"] and abs(r["rate"] - r["plr"]) < 0.01 and not r["disc"] for r in rows)
			check(f"scan {n} {item}: full price, 0% discount", ok, rows)
			check(f"scan {n} {item}: barcode kept on the line", rows and any(r["barcode"] == barcode for r in rows), rows)
			repeat = SCANS[:n - 1].count((barcode, item)) > 0
			if repeat:
				check(f"scan {n} {item}: same barcode again adds 1 to the line", any(r["qty"] == 2 for r in rows), rows)
			else:
				check(f"scan {n} {item}: item loaded once", len(calls) == 1, len(calls))
		check("never saved", page.evaluate("() => cur_frm.doc.__islocal === 1"))
		check("no page errors", not errors, errors)
		b.close()
finally:
	h.drop_session(sid)

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
