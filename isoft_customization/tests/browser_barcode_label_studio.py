"""Browser check of /app/barcode-label-studio (Playwright, Administrator session; nothing is saved).

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/browser_barcode_label_studio.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_target_total as h  # noqa: E402

fails = 0


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:400])
	fails += not cond


def settle(page):
	page.wait_for_timeout(300)
	page.wait_for_function("() => !frappe.request.ajax_count", timeout=60000)
	page.wait_for_timeout(700)


sid = h.mint_session()
errors, pdf_responses = [], []
try:
	from playwright.sync_api import sync_playwright

	with sync_playwright() as pw:
		b = pw.chromium.launch()
		ctx = b.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 900})
		ctx.add_cookies([{"name": "sid", "value": sid, "domain": "dev.isoft.ao", "path": "/"}])
		ctx.on("response", lambda r: "barcode_labels.api.make_pdf" in r.url and pdf_responses.append((r.status, r.headers.get("content-type"))))
		page = ctx.new_page()
		page.on("pageerror", lambda e: errors.append(str(e)[:300]))
		page.goto(h.BASE_URL + "/app/barcode-label-studio", wait_until="networkidle")
		page.wait_for_selector(".bls-host", timeout=30000)
		settle(page)
		check("page_loads", page.locator(".bls-host").count() == 1)
		check("price_list_default", bool(page.evaluate("() => frappe.pages['barcode-label-studio'].bls.opts.price_list")))

		scan = page.locator("#bls-scan")
		scan.click()
		page.keyboard.type("5602024006119", delay=5)
		page.keyboard.press("Enter")
		settle(page)
		row = page.locator(".bls-row[data-item='PAP-A4']")
		check("scan_adds_row", row.count() == 1, row.count())
		check("scan_row_uom_box", row.count() and "Box" in row.first.locator(".bls-uom").inner_text())
		check("scan_row_priced", row.count() and "Kz" in row.first.locator(".bls-final").inner_text(), row.first.inner_text() if row.count() else "")

		page.click("#bls-add-filter")
		page.wait_for_selector(".modal:visible [data-fieldname='item_group'] input", timeout=10000)
		page.evaluate("() => frappe.pages['barcode-label-studio'].bls.dialog.set_value('item_group', 'TEST CATEGORY')")
		page.wait_for_timeout(500)
		page.locator(".modal:visible .btn-primary").click()
		settle(page)
		check("filter_adds_rows", page.locator(".bls-row[data-item='Test-05-11-2026']").count() == 5, page.locator(".bls-row").count())

		first = page.locator(".bls-row").first.locator(".bls-copies")
		first.fill("3")
		first.dispatch_event("change")
		page.wait_for_timeout(400)
		total = page.evaluate("() => frappe.pages['barcode-label-studio'].bls.rows.reduce((a, r) => a + (+r.copies || 1), 0)")
		check("copies_counted", total == 3 + 5 and str(total) in page.locator("#bls-count").inner_text(), (total, page.locator("#bls-count").inner_text()))

		page.locator(".bls-row[data-item='PAP-A4']").first.click()
		settle(page)
		srcdoc = page.evaluate("() => document.querySelector('#bls-preview iframe').srcdoc")
		check("default_hides_price", "Kz" not in srcdoc and "<svg" in srcdoc, srcdoc[:200])

		page.click("#bls-fields")
		page.locator("[data-show='price'] input").check()
		settle(page)
		srcdoc = page.evaluate("() => document.querySelector('#bls-preview iframe').srcdoc")
		check("toggle_price_on", "Kz" in srcdoc and "<svg" in srcdoc, srcdoc[:200])
		page.locator("[data-show='price'] input").uncheck()
		settle(page)
		srcdoc = page.evaluate("() => document.querySelector('#bls-preview iframe').srcdoc")
		check("toggle_price_off", "Kz" not in srcdoc and "<svg" in srcdoc, srcdoc[:200])
		page.keyboard.press("Escape")

		page.select_option("#bls-size", label="30×50")
		settle(page)
		box = page.evaluate("() => { const r = document.querySelector('#bls-preview .bls-paper').getBoundingClientRect(); return [r.width, r.height]; }")
		check("size_portrait_preview", box[1] > box[0], box)

		with ctx.expect_page():
			page.click("#bls-print")
		for _ in range(60):  # a PDF tab never fires "load" headless: wait for the response itself
			if pdf_responses:
				break
			page.wait_for_timeout(500)
		check("print_pdf", any(s == 200 and (t or "").startswith("application/pdf") for s, t in pdf_responses), pdf_responses)

		page.click("#bls-gear")
		page.wait_for_selector(".modal:visible .modal-title", timeout=10000)
		check("gear_opens_settings", "Barcode Label Settings" in page.locator(".modal:visible .modal-title").first.inner_text())
		page.keyboard.press("Escape")

		check("no_page_errors", not errors, errors)
		b.close()
finally:
	h.drop_session(sid)

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
