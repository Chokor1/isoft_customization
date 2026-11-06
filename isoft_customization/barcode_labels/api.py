"""Whitelisted methods of the Barcode Label Studio page (/app/barcode-label-studio)."""

import frappe
from frappe import _
from frappe.utils import cint, cstr

from isoft_customization.barcode_labels import encoder, pricing, render, settings

MAX_FILTER_ITEMS = 500


def _check_read():
	if frappe.session.user == "Guest" or not frappe.has_permission("Item", "read"):
		frappe.throw(_("Not permitted to read Items"), frappe.PermissionError)


def _merged_opts(opts):
	s = settings.get_settings()
	opts = frappe._dict(frappe.parse_json(opts) or {})
	show = dict(s["show"])
	show.update({k: cint(v) for k, v in (opts.get("show") or {}).items()})
	opts.show = show
	for k in ("currency_symbol", "symbol_position", "price_decimals"):
		if opts.get(k) is None:
			opts[k] = s[k]
	if opts.get("include_tax") is None:
		opts.include_tax = s["include_tax"]
		opts.tax_category = opts.tax_category or s["tax_category"]
	return opts, s


def _size(opts, s):
	sizes = s["sizes"]
	return next((z for z in sizes if z["label_name"] == opts.get("size")), None) or next(z for z in sizes if z["is_default"])


def _default_warehouse():
	return frappe.defaults.get_user_default("Warehouse") or frappe.db.get_single_value("Stock Settings", "default_warehouse")


@frappe.whitelist()
def get_page_defaults():
	_check_read()
	s = settings.get_settings()
	company = frappe.defaults.get_user_default("Company") or frappe.db.get_default("company")
	price_list = (
		s["default_price_list"]
		or frappe.db.get_single_value("Selling Settings", "selling_price_list")
		or frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
	)
	return {
		"settings": s,
		"company": company,
		"price_list": price_list,
		"warehouse": _default_warehouse(),
		"currency_symbol": s["currency_symbol"],
		"can_generate": frappe.has_permission("Item", "write"),
	}


@frappe.whitelist()
def search_items(txt="", limit=20):
	_check_read()
	txt = "%{}%".format(cstr(txt).strip())
	rows = frappe.get_list(
		"Item",
		filters={"disabled": 0, "has_variants": 0},
		or_filters={"name": ["like", txt], "item_name": ["like", txt]},
		fields=["name as item_code", "item_name"],
		limit_page_length=min(cint(limit) or 20, 50),
		order_by="modified desc",
	)
	counts = dict(frappe.db.sql(
		"select parent, count(*) from `tabItem Barcode` where parent in %s group by parent",
		[tuple(r.item_code for r in rows) or ("",)],
	))
	for r in rows:
		r["barcodes"] = counts.get(r.item_code, 0)
	return rows


@frappe.whitelist()
def resolve_scan(code=""):
	"""A scanned barcode -> that exact barcode row; an item code -> the item (first barcode row is not guessed)."""
	_check_read()
	code = cstr(code).strip()
	if not code:
		return {}
	fields = ["parent as item_code", "barcode"]
	if frappe.get_meta("Item Barcode").has_field("posa_uom"):
		fields.append("posa_uom as uom")
	hit = frappe.db.get_value("Item Barcode", {"barcode": code}, fields, as_dict=True)
	if hit:
		hit.setdefault("uom", None)
		return hit
	if frappe.db.exists("Item", code):
		return {"item_code": code, "barcode": None, "uom": None}
	return {}


def _rows_for(item_codes):
	if not item_codes:
		return []
	has_uom = frappe.get_meta("Item Barcode").has_field("posa_uom")
	barcodes = frappe.get_all(
		"Item Barcode",
		filters={"parent": ["in", item_codes], "parenttype": "Item"},
		fields=["parent", "barcode"] + (["posa_uom"] if has_uom else []),
		order_by="parent, idx",
	)
	by_item = {}
	for b in barcodes:
		by_item.setdefault(b.parent, []).append({"item_code": b.parent, "barcode": b.barcode, "uom": b.get("posa_uom")})
	out = []
	for code in item_codes:
		out.extend(by_item.get(code) or [{"item_code": code, "barcode": None, "uom": None}])
	return out


@frappe.whitelist()
def rows_for_items(item_codes):
	_check_read()
	codes = [c for c in (frappe.parse_json(item_codes) or []) if c]
	allowed = set(frappe.get_list("Item", filters={"name": ["in", codes]}, pluck="name")) if codes else set()
	return _rows_for([c for c in codes if c in allowed])


@frappe.whitelist()
def rows_for_filter(item_group=None, brand=None):
	_check_read()
	filters = {"disabled": 0, "has_variants": 0, "is_sales_item": 1}
	if item_group:
		lft, rgt = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"])
		groups = frappe.get_all("Item Group", filters={"lft": [">=", lft], "rgt": ["<=", rgt]}, pluck="name")
		filters["item_group"] = ["in", groups]
	if brand:
		filters["brand"] = brand
	if not item_group and not brand:
		frappe.throw(_("Pick an Item Group or a Brand"))
	codes = frappe.get_list("Item", filters=filters, pluck="name", order_by="item_name asc", limit_page_length=MAX_FILTER_ITEMS)
	return _rows_for(codes)


@frappe.whitelist()
def price(rows, opts):
	_check_read()
	opts, _s = _merged_opts(opts)
	rows = frappe.parse_json(rows) or []
	return pricing.price_rows(rows, opts)


def _priced(rows, opts):
	"""Price each distinct (item, barcode, uom) once, keep the copies."""
	keys, uniq = [], {}
	for r in rows:
		k = (r.get("item_code"), r.get("barcode"), r.get("uom"))
		keys.append(k)
		uniq.setdefault(k, {"item_code": k[0], "barcode": k[1], "uom": k[2]})
	priced = dict(zip(uniq.keys(), pricing.price_rows(list(uniq.values()), opts)))
	out = []
	for r, k in zip(rows, keys):
		if k in priced:
			out.append(dict(priced[k], copies=max(1, cint(r.get("copies") or 1))))
	return out


@frappe.whitelist()
def preview_html(row, opts):
	_check_read()
	opts, s = _merged_opts(opts)
	row = dict(frappe.parse_json(row) or {}, copies=1)
	return render.document_html(_priced([row], opts), opts, _size(opts, s))


@frappe.whitelist(methods=["POST"])
def make_pdf(rows, opts):
	_check_read()
	opts, s = _merged_opts(opts)
	rows = frappe.parse_json(rows) or []
	total = sum(max(1, cint(r.get("copies") or 1)) for r in rows)
	if total > render.MAX_LABELS:
		frappe.throw(_("{0} labels requested; one PDF holds at most {1}. Split the list.").format(total, render.MAX_LABELS))
	size = _size(opts, s)
	frappe.local.response.filename = "barcode-labels.pdf"
	frappe.local.response.filecontent = render.make_pdf_bytes(_priced(rows, opts), opts, size)
	frappe.local.response.type = "pdf"


@frappe.whitelist(methods=["POST"])
def generate_barcode(item_code):
	if not frappe.has_permission("Item", "write", doc=item_code):
		frappe.throw(_("Not permitted to change Item {0}").format(item_code), frappe.PermissionError)
	prefix = settings.get_settings()["ean_prefix"]
	width = 12 - len(prefix)
	existing = frappe.db.sql(
		"select barcode from `tabItem Barcode` where barcode like %s and char_length(barcode) = 13",
		(prefix + "%",),
	)
	seq = max([cint(b[len(prefix):12]) for (b,) in existing if b.isdigit()] or [0]) + 1
	while True:
		if seq >= 10 ** width:
			frappe.throw(_("No free EAN-13 left under prefix {0}").format(prefix))
		body = prefix + str(seq).zfill(width)
		code = body + str(encoder.ean_check_digit(body))
		if not frappe.db.exists("Item Barcode", {"barcode": code}):
			break
		seq += 1
	item = frappe.get_doc("Item", item_code)
	row = {"barcode": code, "barcode_type": "EAN"}
	if frappe.get_meta("Item Barcode").has_field("posa_uom"):
		row["posa_uom"] = item.stock_uom
	item.append("barcodes", row)
	item.save()
	return {"barcode": code, "uom": row.get("posa_uom")}
