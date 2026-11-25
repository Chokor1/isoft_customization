"""An item load must never leave a selling line at a 100% discount (public/js/item_details_rate.js).

Replays ERPNext v13's original scan sequence (item code, then barcode -> the item loads twice),
which put every line at 100%: with the protection switched off it must still do so (the test
really reproduces the bug), with it on every line must keep the full price at 0%. Nothing is saved.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/item_load_no_full_discount_check.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_target_total as h  # noqa: E402
PAIRS = [["MSE-LOG-M185", "5099206012141"], ["ROL-TR57", "3664768009919"], ["PAP-A4", "5602024006102"]]
fails = 0
sid = h.mint_session()
try:
	from playwright.sync_api import sync_playwright
	with sync_playwright() as pw:
		b = pw.chromium.launch()
		ctx = b.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
		ctx.add_cookies([{"name": "sid", "value": sid, "domain": "dev.isoft.ao", "path": "/"}])
		for off in (True, False):
			page = ctx.new_page(); errs = []
			page.on("pageerror", lambda e: errs.append(str(e)[:200]))
			page.goto(h.BASE_URL + "/app/sales-invoice/new", wait_until="networkidle")
			page.wait_for_function("() => window.cur_frm && cur_frm.doc.doctype === 'Sales Invoice'", timeout=30000); page.wait_for_timeout(1500)
			page.evaluate("() => { cur_frm.set_value('update_stock', 0); cur_frm.set_value('customer', 'FERPINTA ANGOLA'); }"); page.wait_for_timeout(2500)
			page.evaluate("(off) => { isoft.item_details_rate.off = off; frappe.model.clear_table(cur_frm.doc, 'items'); cur_frm.refresh_field('items'); }", off)
			for item, barcode in PAIRS * 3:
				# ERPNext's ORIGINAL scan sequence, without the scan fix: item code, then barcode
				page.evaluate("""([item, barcode]) => { const row = frappe.model.add_child(cur_frm.doc, 'Sales Invoice Item', 'items'); cur_frm.refresh_field('items');
					cur_frm.from_barcode = cur_frm.from_barcode ? cur_frm.from_barcode + 1 : 1;
					frappe.model.set_value(row.doctype, row.name, {item_code: item, qty: 1});
					frappe.model.set_value(row.doctype, row.name, 'barcode', barcode); }""", [item, barcode])
				page.wait_for_timeout(3500)
			res = page.evaluate("() => cur_frm.doc.items.map(r => ({plr: r.price_list_rate, rate: r.rate, disc: r.discount_percentage}))")
			bad = sum(1 for r in res if r["plr"] and r["disc"] >= 99)
			good = sum(1 for r in res if r["plr"] and abs(r["rate"] - r["plr"]) < 0.01 and not r["disc"])
			print(f"protection {'OFF' if off else 'ON '}: lines={len(res)} at 100%: {bad} | correct (full price, 0%): {good} | errors: {errs[:2]}", flush=True)
			ok = (bad == len(res)) if off else (good == len(res) and not errs)
			print("PASS" if ok else "FAIL", "bug reproduced without the protection" if off else "every line correct with the protection", flush=True)
			fails += not ok
			page.close()
		b.close()
finally:
	h.drop_session(sid)

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
