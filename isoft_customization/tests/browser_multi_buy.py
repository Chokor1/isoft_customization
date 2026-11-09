"""Browser check of multi-buy pricing rules: POS Awesome cart (--pos) and the desk forms (--desk).

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/browser_multi_buy.py [--pos] [--desk]
Creates ONE real Pricing Rule on dev ("MB browser test", buy 1 get 1 at 50% on PAP-A4 + MSE-LOG-M185)
and deletes it at the end. Nothing is saved or submitted in the browser.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_target_total as h  # noqa: E402
from scan_barcode_uom_check import FIND  # noqa: E402

import frappe  # noqa: E402

fails = 0
TITLE = "MB browser test"


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:500], flush=True)
	fails += not cond


def setup_rule(codes=("PAP-A4", "MSE-LOG-M185")):
	"""On mint_session's connection; codes = the two items the rule covers."""
	frappe.set_user("Administrator")
	for n in frappe.get_all("Pricing Rule", filters={"title": TITLE}, pluck="name"):
		frappe.delete_doc("Pricing Rule", n, force=True)
	d = frappe.get_doc({"doctype": "Pricing Rule", "title": TITLE, "apply_on": "Item Code",
		"items": [{"item_code": c} for c in codes], "selling": 1, "company": "ITEC LDA", "currency": "AKZ",
		"applicable_for": "Customer Group", "customer_group": "All Customer Groups", "priority": "20",
		"isoft_multibuy": 1, "isoft_buy_qty": 1, "isoft_get_qty": 1, "isoft_multibuy_discount": 50})
	d.insert(ignore_permissions=True)
	frappe.db.commit()
	return d.name


def drop_rule():
	"""On mint_session's connection, before drop_session closes it."""
	frappe.set_user("Administrator")
	for n in frappe.get_all("Pricing Rule", filters={"title": TITLE}, pluck="name"):
		frappe.delete_doc("Pricing Rule", n, force=True)
	frappe.db.commit()


def pos(page):
	page.goto(f"{h.BASE_URL}/app/posapp", wait_until="networkidle")
	page.wait_for_timeout(9000)
	page.wait_for_function("() => { " + FIND + " return sel && sel.items && sel.items.length > 0; }", timeout=60000)

	def cart():
		return page.evaluate("() => {" + FIND + " return (inv.items || []).map(i => ({item: i.item_code, plr: +i.price_list_rate, rate: +i.rate,"
			" disc: +i.discount_percentage || 0, rule: i.isoft_multibuy_rule || null})); }")

	# two plain priced items this POS profile actually shows (its item filter varies by site)
	codes = page.evaluate("() => {" + FIND + """ const seen = new Set(); return sel.items.filter(i => +i.rate > 0 && !i.has_serial_no && !i.has_batch_no
		&& !(i.item_barcode || []).some(b => b.posa_uom) && !seen.has(+i.rate) && seen.add(+i.rate)).slice(0, 2).map(i => i.item_code); }""")
	check("pos_has_two_items", len(codes) == 2, codes)
	setup_rule(codes)
	page.evaluate("() => {" + FIND + " inv.items.splice(0); sel.first_search = null; sel.search = null; }")
	page.wait_for_timeout(500)
	for code in codes:
		page.evaluate("(c) => {" + FIND + " sel.add_item(sel.items.find(i => i.item_code === c)); }", code)
		page.wait_for_timeout(2500)
	page.wait_for_timeout(2500)
	rows = {r["item"]: r for r in cart()}
	cheap, dear = sorted(rows.values(), key=lambda r: r["plr"]) if len(rows) == 2 else (None, None)
	# every basket row carries the rule (the paying one with 0 units); only the cheaper one is discounted
	check("pos_cart_shows_multibuy", cheap and cheap["rule"] and abs(cheap["disc"] - 50) < 0.01 and dear["rule"] and not dear["disc"], rows)
	check("pos_paying_row_locked", page.evaluate("(c) => {" + FIND + " return inv.discount_locked(inv.items.find(i => i.item_code === c)); }", dear["item"]))
	check("pos_tag_rendered", page.locator(".pos-mb-tag").count() >= 1, page.locator(".pos-mb-tag").count())

	srv = page.evaluate("() => {" + FIND + " return inv.update_invoice(inv.get_invoice_doc()).then(d => d && ({grand: d.grand_total,"
		" items: d.items.map(i => ({item: i.item_code, disc: i.discount_percentage, rule: i.isoft_multibuy_rule || null, rate: i.rate}))})); }")
	sitems = {i["item"]: i for i in (srv or {}).get("items", [])}
	check("pos_server_matches_cart", srv and all(abs(sitems[k]["disc"] - rows[k]["disc"]) < 0.01 and abs(sitems[k]["rate"] - rows[k]["rate"]) < 0.01
		for k in rows) and sitems[cheap["item"]]["rule"], (srv, rows))

	# pos_manual_row_out: a 5% typed on the dearer item while it is alone (no offer yet) keeps it out of
	# the basket when the cheaper one joins; one unit left in the basket -> no offer anywhere
	page.evaluate("() => {" + FIND + " inv.items.splice(0); }")
	page.wait_for_timeout(800)
	page.evaluate("(c) => {" + FIND + " sel.add_item(sel.items.find(i => i.item_code === c)); }", dear["item"])
	page.wait_for_timeout(3000)
	page.evaluate("(code) => {" + FIND + " const it = inv.items.find(i => i.item_code === code); it.discount_percentage = 5; inv.calc_item_price(it); }", dear["item"])
	page.wait_for_timeout(1500)
	page.evaluate("(c) => {" + FIND + " sel.add_item(sel.items.find(i => i.item_code === c)); }", cheap["item"])
	page.wait_for_timeout(3500)
	rows2 = {r["item"]: r for r in cart()}
	# the cheaper item falls back to whatever its normal pricing rule gives (on dev 21601 has a 10% rule)
	check("pos_manual_row_out", not rows2[cheap["item"]]["rule"] and not rows2[dear["item"]]["rule"] and abs(rows2[cheap["item"]]["disc"] - 50) > 0.01
		and abs(rows2[dear["item"]]["disc"] - 5) < 0.01, rows2)
	srv2 = page.evaluate("() => {" + FIND + " return inv.update_invoice(inv.get_invoice_doc()).then(d => d && d.items.map(i => ({item: i.item_code, disc: i.discount_percentage, rule: i.isoft_multibuy_rule || null}))); }")
	s2 = {i["item"]: i for i in srv2 or []}
	check("pos_manual_row_out_server", s2 and not s2[cheap["item"]]["rule"] and abs(s2[dear["item"]]["disc"] - 5) < 0.01, srv2)
	page.evaluate("() => {" + FIND + " inv.items.splice(0); }")

	# same item: the discounted units get their own line (user request 2026-11-09: "1 normal and 1 with 50%")
	def lines():
		return page.evaluate("() => {" + FIND + " return inv.items.map(i => [i.item_code, +i.qty, Math.round((+i.discount_percentage || 0) * 100) / 100, +i.isoft_multibuy_units || 0]); }")

	def add_one(code):
		page.evaluate("(c) => {" + FIND + " sel.add_item(sel.items.find(i => i.item_code === c)); }", code)
		page.wait_for_timeout(3500)

	def shape(rows):
		return sorted((q, d) for _c, q, d, _u in rows)

	page.wait_for_timeout(800)
	add_one(dear["item"])
	add_one(dear["item"])
	check("pos_same_item_2_split", shape(lines()) == [(1, 0), (1, 50)], lines())
	add_one(dear["item"])
	check("pos_same_item_3", shape(lines()) == [(1, 50), (2, 0)], lines())
	add_one(dear["item"])
	check("pos_same_item_4", shape(lines()) == [(2, 0), (2, 50)], lines())
	srv3 = page.evaluate("() => {" + FIND + " return inv.update_invoice(inv.get_invoice_doc()).then(d => d && d.items.map(i => [i.item_code, +i.qty, Math.round(i.discount_percentage * 100) / 100])); }")
	check("pos_split_server_matches", srv3 and sorted((q, d) for _c, q, d in srv3) == [(2, 0), (2, 50)], srv3)
	# down to one unit: the lines merge back, no discount
	page.evaluate("(c) => {" + FIND + " inv.items.filter(i => i.item_code === c).forEach(i => inv.remove_item(i)); }", dear["item"])
	page.wait_for_timeout(1500)
	add_one(dear["item"])
	add_one(cheap["item"])
	page.evaluate("(c) => {" + FIND + " inv.remove_item(inv.items.find(i => i.item_code === c)); }", cheap["item"])
	page.wait_for_timeout(3500)
	check("pos_single_unit_one_line", lines() == [[dear["item"], 1, 0, 0]], lines())
	page.evaluate("() => {" + FIND + " inv.items.splice(0); }")


def desk(page):
	A, B = "MSE-LOG-M185", "PAP-A4"  # B is the cheaper one
	setup_rule((A, B))  # the POS part replaces the rule with one on its own items
	page.goto(h.BASE_URL + "/app/quotation/new", wait_until="networkidle")
	page.wait_for_function("() => window.cur_frm && cur_frm.doc.doctype === 'Quotation'", timeout=30000)
	page.wait_for_timeout(1500)
	page.evaluate("() => { cur_frm.set_value('party_name', 'Abbass'); }")
	page.wait_for_timeout(2500)
	page.evaluate("() => { frappe.model.clear_table(cur_frm.doc, 'items'); cur_frm.refresh_field('items'); }")
	for code in (A, B):
		page.evaluate("(c) => { const r = cur_frm.add_child('items'); frappe.model.set_value(r.doctype, r.name, 'item_code', c); }", code)
		page.wait_for_timeout(3000)
	page.wait_for_timeout(3000)
	rows = page.evaluate("() => cur_frm.doc.items.map(i => ({code: i.item_code, mb: i.isoft_multibuy_rule || null, pct: +i.discount_percentage || 0}))")
	b = next((x for x in rows if x["code"] == B), {})
	a = next((x for x in rows if x["code"] == A), {})
	check("desk_quotation_live_discount", b.get("mb") and abs(b.get("pct") - 50) < 0.01 and not a.get("pct"), rows)
	ind = page.evaluate("() => $(cur_frm.page.wrapper).find('.isoft-mb-indicator:visible').text()")
	check("desk_indicator", "Multi-buy" in ind, ind)
	page.evaluate("() => { const r = cur_frm.doc.items.find(i => i.item_code === 'PAP-A4'); frappe.model.set_value(r.doctype, r.name, 'qty', 0); }")
	page.evaluate("() => { const r = cur_frm.doc.items.find(i => i.item_code === 'PAP-A4'); cur_frm.get_field('items').grid.grid_rows_by_docname[r.name].remove(); }")
	page.wait_for_timeout(4000)
	rows = page.evaluate("() => cur_frm.doc.items.map(i => ({code: i.item_code, mb: i.isoft_multibuy_rule || null, pct: +i.discount_percentage || 0}))")
	check("desk_offer_released_when_basket_breaks", rows and not any(r["mb"] for r in rows), rows)
	check("desk_never_saved", page.evaluate("() => cur_frm.doc.__islocal === 1"))

	page.goto(h.BASE_URL + "/app/pricing-rule/new", wait_until="networkidle")
	page.wait_for_function("() => window.cur_frm && cur_frm.doc.doctype === 'Pricing Rule'", timeout=30000)
	page.evaluate("() => { cur_frm.set_value('selling', 1); cur_frm.set_value('isoft_multibuy', 1); }")
	page.wait_for_timeout(1500)
	hidden = page.evaluate("() => ['discount_percentage', 'rate_or_discount', 'margin_type', 'free_item', 'mixed_conditions'].map(f => !(cur_frm.fields_dict[f] && $(cur_frm.fields_dict[f].wrapper).is(':visible')))")
	check("pricing_rule_form_hides_standard_discount", all(hidden), hidden)
	shown = page.evaluate("() => ['isoft_buy_qty', 'isoft_get_qty', 'isoft_multibuy_discount'].map(f => $(cur_frm.fields_dict[f].wrapper).is(':visible'))")
	check("pricing_rule_form_shows_multibuy", all(shown), shown)

	page.goto(h.BASE_URL + "/app/pricing-rules-manager", wait_until="networkidle")
	page.wait_for_timeout(5000)
	page.evaluate("() => { const i = document.querySelector('#pr-search'); if (i) { i.value = 'MB browser'; i.dispatchEvent(new Event('input', {bubbles: true})); } }")
	page.wait_for_timeout(2500)
	check("manager_badge", page.locator(".pr-mb-badge").count() > 0, page.locator(".pr-mb-badge").count())


def main():
	args = set(sys.argv[1:]) or {"--pos", "--desk"}
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
			if "--pos" in args:
				pos(page)
			if "--desk" in args and "desk" in globals():
				globals()["desk"](page)
			check("no_page_errors", not errors, errors)
			b.close()
	finally:
		drop_rule()
		h.drop_session(sid)
	print("FAILURES:", fails)
	sys.exit(1 if fails else 0)


if __name__ == "__main__":
	main()
