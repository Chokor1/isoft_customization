"""Barcode Label Settings: read with defaults, save from the page's gear dialog."""

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt

DOCTYPE = "Barcode Label Settings"
SHOW_FIELDS = ("company", "item_name", "item_code", "barcode", "barcode_digits", "uom", "price", "discount")
# off unless switched on (user request 2026-11-06: no name, price or discount by default)
SHOW_DEFAULTS = {"company": 0, "item_name": 0, "uom": 0, "price": 0, "discount": 0}
DEFAULT_SIZES = (
	{"label_name": "50×30", "width_mm": 50, "height_mm": 30, "padding_mm": 1.5, "font_size_pt": 7, "is_default": 1},
	{"label_name": "30×50", "width_mm": 30, "height_mm": 50, "padding_mm": 1.5, "font_size_pt": 6.5, "is_default": 0},
	{"label_name": "50×80", "width_mm": 50, "height_mm": 80, "padding_mm": 2, "font_size_pt": 9, "is_default": 0},
)
WRITE_ROLES = ("System Manager", "Stock Manager")


def _saved():
	return bool(frappe.db.sql("select 1 from tabSingles where doctype=%s limit 1", DOCTYPE))


@frappe.whitelist()
def get_settings():
	doc = frappe.get_single(DOCTYPE)  # get_cached_doc goes stale after a db.set_value on Singles
	saved = _saved()
	sizes = [
		{
			"label_name": r.label_name,
			"width_mm": flt(r.width_mm),
			"height_mm": flt(r.height_mm),
			"padding_mm": flt(r.padding_mm) if r.padding_mm is not None else 1.5,
			"font_size_pt": flt(r.font_size_pt) or 7,
			"is_default": cint(r.is_default),
		}
		for r in (doc.get("sizes") or [])
		if r.label_name and flt(r.width_mm) > 0 and flt(r.height_mm) > 0
	]
	if not sizes:
		sizes = [dict(z) for z in DEFAULT_SIZES]
	if sum(z["is_default"] for z in sizes) != 1:
		for i, z in enumerate(sizes):
			z["is_default"] = 1 if i == 0 else 0

	def show(key):
		value = doc.get("show_" + key)
		if not saved or value is None:
			return SHOW_DEFAULTS.get(key, 1)
		return cint(value)

	return {
		"sizes": sizes,
		"default_price_list": doc.default_price_list or None,
		"ean_prefix": cstr(doc.ean_prefix).strip() or "200",
		"currency_symbol": doc.currency_symbol if saved and doc.currency_symbol is not None else "Kz",
		"symbol_position": doc.symbol_position or "After",
		"price_decimals": cint(doc.price_decimals) if saved and doc.price_decimals not in (None, "") else 2,
		"include_tax": cint(doc.include_tax),
		"tax_category": doc.tax_category or None,
		"show": {k: show(k) for k in SHOW_FIELDS},
		"can_write": bool(set(WRITE_ROLES) & set(frappe.get_roles())),
	}


@frappe.whitelist()
def save_settings(settings):
	if not set(WRITE_ROLES) & set(frappe.get_roles()):
		frappe.throw(_("Not permitted to change Barcode Label Settings"), frappe.PermissionError)
	settings = frappe.parse_json(settings) or {}
	doc = frappe.get_single(DOCTYPE)
	doc.set("sizes", [])
	for z in settings.get("sizes") or []:
		if not z.get("label_name") or flt(z.get("width_mm")) <= 0 or flt(z.get("height_mm")) <= 0:
			continue
		doc.append("sizes", {
			"label_name": cstr(z.get("label_name")).strip(),
			"width_mm": flt(z.get("width_mm")),
			"height_mm": flt(z.get("height_mm")),
			"padding_mm": 1.5 if z.get("padding_mm") in (None, "") else flt(z.get("padding_mm")),
			"font_size_pt": flt(z.get("font_size_pt")) or 7,
			"is_default": cint(z.get("is_default")),
		})
	doc.default_price_list = settings.get("default_price_list") or None
	prefix = cstr(settings.get("ean_prefix")).strip() or "200"
	if not prefix.isdigit() or not 2 <= len(prefix) <= 7:
		frappe.throw(_("The EAN-13 prefix must be 2 to 7 digits"))
	doc.ean_prefix = prefix
	doc.currency_symbol = cstr(settings.get("currency_symbol"))
	doc.symbol_position = settings.get("symbol_position") or "After"
	doc.price_decimals = cstr(cint(settings.get("price_decimals", 2)))
	doc.include_tax = cint(settings.get("include_tax"))
	doc.tax_category = settings.get("tax_category") or None
	for k in SHOW_FIELDS:
		doc.set("show_" + k, cint((settings.get("show") or {}).get(k, SHOW_DEFAULTS.get(k, 1))))
	doc.save(ignore_permissions=True)  # role checked above
	return get_settings()
