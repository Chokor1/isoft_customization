"""Label HTML and PDF: one label = one PDF page of exactly the chosen size (wkhtmltopdf)."""

import base64
import os

import frappe
from frappe import _
from frappe.utils import cint, flt
from frappe.utils import pdf as fpdf  # attribute lookup at call time (tests patch fpdf.get_pdf)
from markupsafe import Markup, escape

from isoft_customization.barcode_labels import encoder

PT_MM = 0.3528
MAX_LABELS = 2000
_TEMPLATE = os.path.join(os.path.dirname(__file__), "templates", "label.html")


def format_amount(value, decimals=2):
	"""1234.5 -> '1 234,50' (Angolan style, non-breaking thousands space)."""
	text = "{:,.{d}f}".format(flt(value), d=cint(decimals))
	return text.replace(",", " ").replace(".", ",")


def _money(value, opts, currency=None):
	amount = format_amount(value, opts.get("price_decimals", 2))
	symbol = opts.get("currency_symbol") or ""
	if currency and opts.get("_base_currency") and currency != opts["_base_currency"]:
		# the configured symbol is the company currency's; a foreign price list shows its own
		symbol = frappe.db.get_value("Currency", currency, "symbol") or currency
	if not symbol:
		return amount
	return (symbol + " " + amount) if opts.get("symbol_position") == "Before" else (amount + " " + symbol)


def _fit_pt(text, pt, width_mm, bold=False):
	"""Largest font size up to `pt` at which `text` fits on one line of `width_mm` (average glyph width)."""
	glyph = 0.6 if bold else 0.55
	fit = width_mm / max(1, len(text)) / (glyph * PT_MM)
	return round(max(4.0, min(pt, fit)), 2)


def _company_html(opts):
	company = opts.get("company")
	if not company:
		return None
	logo = frappe.db.get_value("Company", company, "company_logo")
	if logo:
		try:
			f = frappe.get_doc("File", {"file_url": logo})
			content = f.get_content()
			ext = (os.path.splitext(logo)[1].lstrip(".") or "png").lower().replace("jpg", "jpeg").replace("svg", "svg+xml")
			return Markup('<img src="data:image/%s;base64,%s" style="max-height:%smm;max-width:100%%">' % (
				ext, base64.b64encode(content).decode(), opts.get("_logo_h", 3)))
		except Exception:  # noqa: BLE001 - a missing logo file must never stop a print run
			pass
	return escape(company)


def label_context(rows, opts, size):
	"""rows: priced rows (pricing.price_rows output) + copies. opts carries the merged show flags."""
	show = opts.get("show") or {}
	w, h = flt(size["width_mm"]), flt(size["height_mm"])
	p = flt(size.get("padding_mm", 1.5))
	base_pt = flt(size.get("font_size_pt")) or 7
	fs = {"base": base_pt, "small": round(base_pt * 0.85, 2), "price": round(base_pt * 1.45, 2)}
	lh = {k: round(v * PT_MM * 1.18, 2) for k, v in fs.items()}
	inner_w, inner_h, gap = w - 2 * p, h - 2 * p - 0.3, 0.5
	chars_per_line = max(8, int(inner_w / (base_pt * PT_MM * 0.52)))
	opts = dict(opts, _logo_h=lh["small"])
	company_html = _company_html(opts) if show.get("company") else None

	labels = []
	for r in rows:
		name = r.get("item_name") or r.get("item_code") if show.get("item_name") else None
		# the width estimate is optimistic for bold capitals: keep a second line from ~60% of it
		name_lines = 1 if not name or len(name) <= chars_per_line * 0.6 else 2
		code_bits = []
		if show.get("item_code"):
			code_bits.append(r.get("item_code"))
		if show.get("uom") and r.get("uom"):
			code_bits.append(r.get("uom"))
		code_line = " · ".join(code_bits) or None
		barcode = r.get("barcode")
		digits = barcode if barcode and show.get("barcode_digits") else None

		price_html = was_html = None
		price_pt = was_pt = 0
		if show.get("price") and r.get("has_price"):
			final = _money(r["final_price"], opts, r.get("currency"))
			price_html = escape(final)
			price_pt = _fit_pt(final, fs["price"], inner_w, bold=True)
			if show.get("discount") and flt(r.get("discount_percentage")):
				old = _money(r["price_list_rate"], opts, r.get("currency"))
				pct = "-%s%%" % ("{:g}".format(flt(r["discount_percentage"], 2)))
				was_pt = _fit_pt(old + "  " + pct, fs["small"], inner_w)
				was_html = Markup('<s>%s</s> <span class="off">%s</span>' % (escape(old), escape(pct)))

		used = (lh["small"] if company_html else 0) + (name_lines * lh["base"] if name else 0)
		used += (lh["small"] if code_line else 0) + (lh["small"] if digits else 0)
		price_lh = round(price_pt * PT_MM * 1.18, 2)
		was_lh = round(was_pt * PT_MM * 1.25, 2)
		used += (price_lh + gap if price_html else 0) + (was_lh if was_html else 0)
		bar_h = 0
		svg = None
		if barcode and show.get("barcode"):
			bar_h = max(4.0, min(inner_h - used - gap, inner_w * 0.6, 30.0))
			svg = Markup(encoder.to_svg(barcode, height_mm=bar_h, width_mm=inner_w))
		label = {
			"company_html": company_html, "name": name, "name_lines": name_lines, "code_line": code_line,
			"svg": svg, "bar_h": round(bar_h, 2), "digits": digits, "price_html": price_html,
			"price_pt": price_pt, "price_lh": price_lh, "was_html": was_html, "was_pt": was_pt, "was_lh": was_lh,
		}
		labels.extend([label] * max(1, cint(r.get("copies") or 1)))
	return {"labels": labels, "w": w, "h": h, "p": p, "fs": fs, "lh": lh, "bw": round(inner_w, 2), "gap": gap}


def document_html(rows, opts, size):
	with open(_TEMPLATE, encoding="utf-8") as f:
		template = f.read()
	return frappe.render_template(template, label_context(rows, opts, size))


def make_pdf_bytes(rows, opts, size):
	total = sum(max(1, cint(r.get("copies") or 1)) for r in rows)
	if total > MAX_LABELS:
		frappe.throw(_("{0} labels requested; one PDF holds at most {1}. Split the list.").format(total, MAX_LABELS))
	if not total:
		frappe.throw(_("Add at least one label"))
	html = document_html(rows, opts, size)
	# no "page-size": frappe forwards "Custom" verbatim and wkhtmltopdf rejects it; an explicit
	# page-width/height wins over the A4 that frappe adds from Print Settings
	options = {
		"page-width": "%smm" % flt(size["width_mm"]),
		"page-height": "%smm" % flt(size["height_mm"]),
		"margin-top": "0mm",
		"margin-bottom": "0mm",
		"margin-left": "0mm",
		"margin-right": "0mm",
	}
	return fpdf.get_pdf(html, options)
