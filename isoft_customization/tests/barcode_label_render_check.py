"""Barcode Label Studio: label HTML, PDF, barcode generation and API permissions. Rolls back everything.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/barcode_label_render_check.py dev.isoft.ao
"""
import io
import json
import shutil
import subprocess
import sys
import tempfile

import frappe

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0
ITEM, PL, COMPANY = "Test-05-11-2026", "Standard Selling", "ITEC LDA"


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:600])
	fails += not cond


def pdf_from(rows, opts):
	from isoft_customization.barcode_labels import api

	frappe.local.response = frappe._dict()
	api.make_pdf(json.dumps(rows), json.dumps(opts))
	return frappe.local.response


try:
	from PyPDF2 import PdfFileReader

	from isoft_customization.barcode_labels import api, encoder, render

	opts = {"price_list": PL, "company": COMPANY, "size": "50×30", "show": {"item_name": 1, "price": 1, "discount": 1}}
	rows = [
		{"item_code": ITEM, "barcode": "1691828500001", "uom": None, "copies": 2},
		{"item_code": "PAP-A4", "barcode": "5602024006119", "uom": None, "copies": 1},
	]
	resp = pdf_from(rows, opts)
	check("pdf_response", resp.get("type") == "pdf" and resp.get("filename") == "barcode-labels.pdf", {k: resp.get(k) for k in ("type", "filename")})
	reader = PdfFileReader(io.BytesIO(resp.filecontent))
	sizes = [(float(p.mediaBox.getWidth()), float(p.mediaBox.getHeight())) for p in (reader.getPage(i) for i in range(reader.getNumPages()))]
	check("pdf_pages_and_size", len(sizes) == 3 and all(abs(w - 141.7) < 1.5 and abs(h - 85.0) < 1.5 for w, h in sizes), sizes)

	# portrait size: 30×50 mm = 85.0 × 141.7 pt
	r2 = pdf_from(rows[:1], dict(opts, size="30×50"))
	p = PdfFileReader(io.BytesIO(r2.filecontent)).getPage(0)
	check("pdf_portrait_size", abs(float(p.mediaBox.getWidth()) - 85.0) < 1.5 and abs(float(p.mediaBox.getHeight()) - 141.7) < 1.5)

	html = api.preview_html(json.dumps(rows[0]), json.dumps(opts))
	check("preview_has_svg", "<svg" in html and "Kz" in html and ITEM in html and "1691828500001" in html, html)
	dflt = api.preview_html(json.dumps(rows[0]), json.dumps({"price_list": PL, "company": COMPANY, "size": "50×30"}))
	check("defaults_hide_name_price", "Kz" not in dflt and "Test_05112026" not in dflt and ITEM in dflt and "<svg" in dflt, dflt)
	off = api.preview_html(json.dumps(rows[0]), json.dumps(dict(opts, show={"price": 0, "discount": 0, "item_code": 0})))
	check("toggles_respected", "Kz" not in off and ITEM not in off and "<svg" in off, off)
	nob = api.preview_html(json.dumps(rows[0]), json.dumps(dict(opts, show={"barcode": 0, "barcode_digits": 0})))
	check("toggle_barcode_off", "<svg" not in nob and "1691828500001" not in nob, nob)

	np = api.preview_html(json.dumps({"item_code": "MSE-LOG-M185", "barcode": "5099206012141"}), json.dumps(dict(opts, price_list="Special Price")))
	check("no_price_label_has_no_price", "Kz" not in np and "MSE-LOG-M185" in np, np)

	# discount shows old price struck through, the % and the final price
	frappe.db.set_value("Item Barcode", {"barcode": "1691828500001", "parent": ITEM}, "discount", 10, update_modified=False)
	dh = api.preview_html(json.dumps(rows[0]), json.dumps(opts))
	check("discount_shown", "<s" in dh and "-10%" in dh and "900" in dh and "1 000" in dh.replace(" ", " ").replace(".", " "), dh)
	frappe.db.set_value("Item Barcode", {"barcode": "1691828500001", "parent": ITEM}, "discount", 0, update_modified=False)

	# accents
	frappe.db.set_value("Item", ITEM, "item_name", "Proteção Acessórios Ação", update_modified=False)
	frappe.clear_document_cache("Item", ITEM)
	frappe.cache().hdel("item_name_cache", ITEM) if hasattr(frappe.cache(), "hdel") else None
	label = render.document_html(
		[dict(r, item_name="Proteção Acessórios Ação") for r in __import__("isoft_customization.barcode_labels.pricing", fromlist=["x"]).price_rows(rows[:1], opts)],
		dict(opts, show={"item_name": 1, "barcode": 1}), [s for s in __import__("isoft_customization.barcode_labels.settings", fromlist=["x"]).get_settings()["sizes"] if s["label_name"] == "50×30"][0],
	)
	check("utf8_meta", '<meta charset="utf-8">' in label and "Proteção" in label, label[:300])
	acc = pdf_from(rows[:1], opts)
	if shutil.which("pdftotext"):
		with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
			f.write(acc.filecontent)
			f.flush()
			text = subprocess.run(["pdftotext", f.name, "-"], capture_output=True, text=True).stdout
		check("accents_survive_pdf", "Proteção" in text, text[:200])
	else:
		print("INFO pdftotext missing: accents checked in HTML only")

	size_5030 = {"width_mm": 50, "height_mm": 30, "padding_mm": 1.5, "font_size_pt": 7}
	base_row = {"item_code": "X1", "barcode": "5901234123457", "has_price": True, "final_price": 100, "price_list_rate": 100,
		"discount_percentage": 0, "currency": "AKZ", "copies": 1}
	show_all = {"item_name": 1, "item_code": 1, "barcode": 1, "barcode_digits": 1, "price": 1}
	ctx2 = render.label_context([dict(base_row, item_name="CABO HDMI 2.0 4K PREMIUM BLINDADO 3M")], {"show": show_all}, size_5030)
	check("name_two_lines", ctx2["labels"][0]["name_lines"] == 2, ctx2["labels"][0]["name_lines"])
	esc_html = render.document_html([dict(base_row, item_name="Cabo <2m> & A")], {"show": show_all}, size_5030)
	check("escapes_name", "&lt;2m&gt;" in esc_html and "<2m>" not in esc_html, esc_html[-600:])
	usd = render.label_context([dict(base_row, item_name="x", currency="USD")],
		{"show": show_all, "currency_symbol": "Kz", "_base_currency": "AKZ", "price_decimals": 2}, size_5030)
	usd_price = str(usd["labels"][0]["price_html"])
	check("foreign_currency_symbol", "Kz" not in usd_price and ("USD" in usd_price or "$" in usd_price), usd_price)

	dis_scan = api.resolve_scan("6955914606104")
	check("resolve_scan_disabled", not dis_scan.get("item_code") and dis_scan.get("error"), dis_scan)
	check("rows_for_items_skips_disabled", api.rows_for_items(json.dumps(["7EH98AA"])) == [])

	# cap
	import frappe.utils.pdf as fpdf

	orig, called = fpdf.get_pdf, []
	fpdf.get_pdf = lambda *a, **k: called.append(1) or b""
	try:
		pdf_from([dict(rows[0], copies=2001)], opts)
		check("label_cap_enforced", False, "no error")
	except frappe.ValidationError:
		check("label_cap_enforced", not called)
	finally:
		fpdf.get_pdf = orig

	# api rows
	r = api.resolve_scan("5602024006119")
	check("resolve_scan", r.get("item_code") == "PAP-A4" and r.get("uom") == "Box", r)
	check("resolve_scan_item_code", api.resolve_scan("PAP-A4").get("item_code") == "PAP-A4")
	check("resolve_scan_unknown", api.resolve_scan("nope-xyz") == {})
	ri = api.rows_for_items(json.dumps(["PAP-A4", ITEM]))
	check("rows_for_items", len([x for x in ri if x["item_code"] == "PAP-A4"]) == 2 and len([x for x in ri if x["item_code"] == ITEM]) == 5, ri)
	rf = api.rows_for_filter(item_group="TEST CATEGORY")
	check("rows_for_filter", any(x["item_code"] == ITEM for x in rf), rf[:3])
	priced = api.price(json.dumps(rows), json.dumps(opts))
	check("price_api", len(priced) == 2 and priced[0]["final_price"] == 1000, priced)
	d = api.get_page_defaults()
	check("page_defaults", d["price_list"] and d["settings"]["sizes"] and "warehouse" in d, d)
	check("search_items", any(x["item_code"] == "PAP-A4" for x in api.search_items("PAP-A4")))

	# generate
	new_item = frappe.get_all("Item", filters={"disabled": 0, "has_variants": 0, "name": ["not in", frappe.get_all("Item Barcode", pluck="parent")]}, limit=1, pluck="name")[0]
	g1 = api.generate_barcode(new_item)
	ok = len(g1["barcode"]) == 13 and g1["barcode"].startswith("200") and encoder.detect(g1["barcode"]) == "EAN13"
	check("generate_barcode_valid", ok, g1)
	check("generate_barcode_saved", frappe.db.get_value("Item Barcode", {"parent": new_item, "barcode": g1["barcode"]}, "barcode_type") == "EAN")
	check("generate_barcode_unique", frappe.db.count("Item Barcode", {"barcode": g1["barcode"]}) == 1)
	g2 = api.generate_barcode(new_item)
	check("generate_barcode_next", g2["barcode"] != g1["barcode"] and encoder.detect(g2["barcode"]) == "EAN13", (g1, g2))

	# permissions: a throwaway Sales User (rolled back with everything else)
	u = frappe.get_doc({"doctype": "User", "email": "bls-sales-check@example.com", "first_name": "BLS check", "send_welcome_email": 0,
	                     "roles": [{"role": "Sales User"}]})
	u.flags.ignore_permissions = True
	u.insert()
	frappe.set_user(u.name)
	check("sales_user_can_price", len(api.price(json.dumps(rows[:1]), json.dumps(opts))) == 1)
	try:
		api.generate_barcode(new_item)
		check("generate_needs_write", False, "generated")
	except frappe.PermissionError:
		check("generate_needs_write", True)
	frappe.set_user("Guest")
	try:
		api.price(json.dumps(rows[:1]), json.dumps(opts))
		check("permission_checked", False, "guest priced")
	except frappe.PermissionError:
		check("permission_checked", True)
	frappe.set_user("Administrator")
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.set_user("Administrator")
	frappe.db.rollback()
	frappe.clear_document_cache("Item", ITEM)  # the item_name edit above must not survive in redis
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
