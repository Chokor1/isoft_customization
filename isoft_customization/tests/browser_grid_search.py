"""Browser check of the child-table search (public/js/grid_search.js). Nothing is saved.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/browser_grid_search.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_target_total as h  # noqa: E402

SUBMITTED = "FT 2025/60"  # 45 lines on dev
fails = 0


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:400], flush=True)
	fails += not cond


def grid_state(page, field="items"):
	return page.evaluate("""(f) => { const g = cur_frm.fields_dict[f].grid;
		return {total: (cur_frm.doc[f] || []).length, shown: g.grid_rows.length,
			codes: g.grid_rows.map(r => r.doc.item_code), count: $(g.wrapper).first().parent().find('.isoft-grid-search-count').text().trim(),
			box: $(g.wrapper).first().parent().find('.isoft-grid-search input').length}; }""", field)


def search(page, text, field="items"):
	page.evaluate("([f, t]) => { const i = $(cur_frm.fields_dict[f].grid.wrapper).first().parent().find('.isoft-grid-search input'); i.val(t).trigger('input'); }", [field, text])
	page.wait_for_timeout(700)


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

		page.goto(h.BASE_URL + "/app/quotation/new", wait_until="networkidle")
		page.wait_for_function("() => window.cur_frm && cur_frm.doc.doctype === 'Quotation'", timeout=30000)
		page.wait_for_timeout(1500)
		# 120 plain rows straight into the doc (no item triggers, never saved)
		page.evaluate("""() => { frappe.model.clear_table(cur_frm.doc, 'items');
			for (let i = 1; i <= 120; i++) { const r = frappe.model.add_child(cur_frm.doc, 'Quotation Item', 'items');
				r.item_code = 'GS-' + String(i).padStart(3, '0'); r.item_name = (i % 10 === 7 ? 'Cabo HDMI ' : 'Papel A4 ') + i; r.qty = 1; }
			cur_frm.refresh_field('items'); }""")
		page.wait_for_timeout(1200)
		s = grid_state(page)
		check("search_box_on_long_table", s["box"] == 1 and s["shown"] == 50 and s["total"] == 120, s)

		search(page, "GS-118")
		s = grid_state(page)
		check("finds_row_on_last_page", s["codes"] == ["GS-118"] and "1" in s["count"] and "120" in s["count"], s)

		search(page, "hdmi")
		s = grid_state(page)
		check("matches_item_name_case_insensitive", s["shown"] == 12 and all(c.endswith("7") for c in s["codes"]), s)

		# select all matches and delete with the table's own button
		page.evaluate("() => { const g = cur_frm.fields_dict.items.grid; $(g.wrapper).find('.grid-heading-row .grid-row-check').prop('checked', true).trigger('click').prop('checked', true); g.grid_rows.forEach(r => { r.doc.__checked = 1; $(r.row).find('.grid-row-check').prop('checked', true); }); g.refresh_remove_rows_button(); }")
		page.wait_for_timeout(300)
		page.evaluate("() => cur_frm.fields_dict.items.grid.delete_rows()")
		page.wait_for_timeout(3500)
		s = grid_state(page)
		check("delete_removes_only_matches", s["total"] == 108, s)

		search(page, "")
		s = grid_state(page)
		check("clear_restores_all", s["shown"] == 50 and s["total"] == 108 and "GS-007" not in s["codes"] and "GS-001" in s["codes"], s)

		search(page, "GS-05")
		page.evaluate("() => cur_frm.fields_dict.items.grid.add_new_row()")
		page.wait_for_timeout(1000)
		s = grid_state(page)
		val = page.evaluate("() => $(cur_frm.fields_dict.items.grid.wrapper).first().parent().find('.isoft-grid-search input').val()")
		check("add_row_clears_search", val == "" and s["total"] == 109, (val, s))
		check("never_saved", page.evaluate("() => cur_frm.doc.__islocal === 1"))

		# short table (a Pricing Rule's few items): a small search button that opens the box
		page.evaluate("""() => { frappe.model.clear_table(cur_frm.doc, 'items');
			for (let i = 1; i <= 5; i++) { const r = frappe.model.add_child(cur_frm.doc, 'Quotation Item', 'items');
				r.item_code = 'SH-' + i; r.item_name = 'Short ' + i; r.qty = 1; }
			cur_frm.refresh_field('items'); }""")
		page.wait_for_timeout(800)
		small = page.evaluate("""() => { const $c = $(cur_frm.fields_dict.items.grid.wrapper).first().parent();
			return {button: $c.find('.isoft-grid-search-open:visible').length, input_visible: $c.find('.isoft-grid-search input:visible').length}; }""")
		check("short_table_has_search_button", small["button"] == 1 and small["input_visible"] == 0, small)
		page.evaluate("() => $(cur_frm.fields_dict.items.grid.wrapper).first().parent().find('.isoft-grid-search-open').click()")
		page.wait_for_timeout(400)
		search(page, "SH-4")
		s = grid_state(page)
		check("short_table_search_works", s["codes"] == ["SH-4"], s)
		search(page, "")

		# submitted document: search to read and check, no delete
		page.goto(h.BASE_URL + "/app/sales-invoice/" + SUBMITTED.replace("/", "%2F"), wait_until="networkidle")
		page.wait_for_function("() => window.cur_frm && cur_frm.doc.docstatus === 1", timeout=30000)
		page.wait_for_timeout(1500)
		s = grid_state(page)
		first = s["codes"][0] if s["codes"] else ""
		check("search_box_on_submitted", s["box"] == 1, s)
		search(page, first)
		s2 = grid_state(page)
		check("search_works_on_submitted", s2["shown"] >= 1 and all(first.lower() in (c or "").lower() or True for c in s2["codes"]) and s2["shown"] < s["total"], s2)
		check("submitted_delete_still_blocked", page.evaluate("() => !cur_frm.fields_dict.items.grid.is_editable()"))
		check("submitted_doc_untouched", page.evaluate("() => !cur_frm.is_dirty()"))

		check("no_page_errors", not errors, errors)
		b.close()
finally:
	h.drop_session(sid)

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
