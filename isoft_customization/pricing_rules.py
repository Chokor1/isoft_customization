# Copyright (c) 2026, ISOFT LDA
"""Pricing Rules Manager desk page (/app/pricing-rules-manager).

The page manages one kind of Pricing Rule only, and fixes everything about it
except the discount, the items and the dates:

    selling, never buying        -> a sales discount
    Price / Discount Percentage  -> a discount, never a margin or a fixed rate
    Apply On = Item Code         -> the items table ("Apply Rule On Item Code")
    Customer Group = the root    -> every customer

The root customer group is not a cosmetic choice: the site's "Find Items" and
"Last Active Pricing Rule" Server Scripts only read rules whose customer_group is
'All Customer Groups', so a rule scoped any other way is invisible to them.

Rules of any other shape are listed read-only and link to the desk form.

The Excel import groups rows by discount and creates one rule per distinct
discount. Before anything is written it reports the rows it cannot use and the
items that already sit in another active rule: ERPNext refuses to price a sales
line that two equal-priority rules both match ("Multiple Price Rules exists with
same criteria"), so an import that ignored them would break selling those items.
"""

import csv
import json
import re

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate, now_datetime, formatdate
from frappe.utils.nestedset import get_root_of

from isoft_customization import pricing_rule_conflicts as prc

TEMPLATE_HEADERS = ["Item Code", "UOM", "Max", "Discount %"]

# Header spellings accepted on import, compared after lowercasing and dropping
# everything that is not a letter or digit.
HEADER_ALIASES = {
	"item_code": {"itemcode", "item", "code", "codigo", "codigodoartigo", "artigo", "applyruleonitemcode"},
	"uom": {"uom", "unit", "unidade", "um"},
	"max": {"max", "maximo", "maximum", "maxqty"},
	"discount": {"discount", "discountpercentage", "discountpercent", "desconto", "descontopercentagem", "disc"},
}

MAX_TITLE = 140


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _root_customer_group():
	return get_root_of("Customer Group")


def _check_perm(ptype="read"):
	if not frappe.has_permission("Pricing Rule", ptype):
		frappe.throw(_("Not permitted to {0} Pricing Rules").format(_(ptype)), frappe.PermissionError)


def _company_currency(company):
	currency = frappe.get_cached_value("Company", company, "default_currency") if company else None
	return currency or frappe.db.get_default("currency")


def _is_simple(rule):
	"""True when the rule has the one shape this page edits."""
	return (
		rule.get("apply_on") == "Item Code"
		and rule.get("price_or_product_discount") == "Price"
		and rule.get("rate_or_discount") == "Discount Percentage"
		and cint(rule.get("selling"))
		and not cint(rule.get("buying"))
		and not rule.get("mixed_conditions")
		and not rule.get("apply_rule_on_other")
		and not rule.get("condition")
	)


def _same_scope(rule, root):
	"""Does the rule reach every customer, as the rules made here do?"""
	af = rule.get("applicable_for") or ""
	return af == "" or (af == "Customer Group" and rule.get("customer_group") == root)


def _status(rule, today):
	if cint(rule.get("disable")):
		return "Disabled"
	if rule.get("valid_upto") and getdate(rule.get("valid_upto")) < today:
		return "Expired"
	if rule.get("valid_from") and getdate(rule.get("valid_from")) > today:
		return "Scheduled"
	return "Active"


def _scope_label(rule, root):
	af = rule.get("applicable_for") or ""
	if not af:
		return "Everyone"
	value = rule.get(frappe.scrub(af))
	if af == "Customer Group" and value == root:
		return "Everyone"
	return "{0}: {1}".format(_(af), value or "?")


def _fmt_pct(value):
	v = round(flt(value), 4)
	return ("%f" % v).rstrip("0").rstrip(".") if v != int(v) else str(int(v))


def _describe_discount(rule):
	rod = rule.get("rate_or_discount")
	if rule.get("price_or_product_discount") == "Product":
		return _("Free item")
	if rod == "Discount Percentage":
		return _fmt_pct(rule.get("discount_percentage")) + "%"
	if rod == "Discount Amount":
		return frappe.format_value(rule.get("discount_amount"), {"fieldtype": "Currency"})
	if rod == "Rate":
		return _("Rate {0}").format(frappe.format_value(rule.get("rate"), {"fieldtype": "Currency"}))
	return rod or ""


def _has_max_field():
	return frappe.get_meta("Pricing Rule Item Code").has_field("max")


# ---------------------------------------------------------------------------
# list / detail
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_rules(company=None):
	"""Every selling Pricing Rule of the company (or of no company), with its
	item codes, so the screen can search by item without another round trip."""
	_check_perm("read")
	root = _root_customer_group()
	today = getdate(nowdate())

	conditions = ["pr.selling = 1"]
	values = {}
	if company:
		conditions.append("(pr.company = %(company)s or ifnull(pr.company, '') = '')")
		values["company"] = company

	rules = frappe.db.sql(
		"""
		select pr.name, pr.title, pr.disable, pr.apply_on, pr.price_or_product_discount,
			pr.rate_or_discount, pr.discount_percentage, pr.discount_amount, pr.rate,
			pr.selling, pr.buying, pr.applicable_for, pr.customer_group, pr.customer,
			pr.territory, pr.sales_partner, pr.campaign, pr.for_price_list, pr.priority,
			pr.valid_from, pr.valid_upto, pr.company, pr.mixed_conditions,
			pr.apply_rule_on_other, pr.condition, pr.modified, pr.owner
		from `tabPricing Rule` pr
		where {0}
		order by pr.modified desc
		""".format(" and ".join(conditions)),
		values,
		as_dict=True,
	)
	if not rules:
		return {"rules": [], "root_customer_group": root, "conflicts": []}

	names = [r.name for r in rules]
	children = {}
	for table, field in (
		("Pricing Rule Item Code", "item_code"),
		("Pricing Rule Item Group", "item_group"),
		("Pricing Rule Brand", "brand"),
	):
		for row in frappe.db.sql(
			"select parent, `{0}` as v from `tab{1}` where parent in %(names)s order by idx".format(field, table),
			{"names": names},
			as_dict=True,
		):
			children.setdefault(row.parent, []).append(row.v)

	out = []
	for r in rules:
		targets = children.get(r.name, [])
		out.append({
			"name": r.name,
			"title": r.title,
			"status": _status(r, today),
			"disabled": cint(r.disable),
			"simple": 1 if _is_simple(r) else 0,
			"apply_on": r.apply_on,
			"discount": _describe_discount(r),
			"discount_percentage": flt(r.discount_percentage),
			"scope": _scope_label(r, root),
			"everyone": 1 if _same_scope(r, root) else 0,
			"price_list": r.for_price_list or "",
			"priority": cint(r.priority),
			"valid_from": r.valid_from,
			"valid_upto": r.valid_upto,
			"company": r.company or "",
			"targets": targets,
			"modified": r.modified,
		})

	return {"rules": out, "root_customer_group": root, "conflicts": _conflicts(rules, root, today)}


def _conflicts(rules, root, today):
	"""Pairs of enabled rules that meet on equal footing: every line both match
	is refused by ERPNext. Same check as the Pricing Rule save guard.
	One entry per pair: {"rules": [a, b], "shared": [...], "apply_on": ...}."""
	pairs = {}
	for r in rules:
		if cint(r.disable) or r.apply_on not in prc.APPLY_ON or _status(r, today) == "Expired":
			continue
		doc = frappe.get_doc("Pricing Rule", r.name)
		for c in prc.find_conflicts(doc):
			key = tuple(sorted([r.name, c["rule"]]))
			if key not in pairs:
				pairs[key] = {"rules": list(key), "shared": c["shared"], "apply_on": r.apply_on}
	return [pairs[k] for k in sorted(pairs)]


@frappe.whitelist()
def make_rule_win(name):
	"""Give `name` the lowest priority at which it no longer collides with any
	rule, so it wins wherever it meets them. The other rules are untouched."""
	doc = frappe.get_doc("Pricing Rule", name)
	doc.check_permission("write")
	p = prc.suggest_priority(doc)
	if not p:
		frappe.throw(_("No priority up to 20 lets {0} win over every rule it collides with. "
			"Remove the shared items or disable a rule instead.").format(name))
	doc.priority = str(p)
	doc.save()
	return {"name": doc.name, "priority": p}


@frappe.whitelist()
def get_rule(name):
	_check_perm("read")
	doc = frappe.get_doc("Pricing Rule", name)
	doc.check_permission("read")
	root = _root_customer_group()
	today = getdate(nowdate())
	has_max = _has_max_field()

	items = []
	if doc.apply_on == "Item Code":
		codes = [d.item_code for d in doc.items if d.item_code]
		info = _item_info(codes)
		for d in doc.items:
			i = info.get(d.item_code) or {}
			items.append({
				"item_code": d.item_code,
				"item_name": i.get("item_name") or "",
				"uom": d.uom or "",
				"max": cint(d.get("max")) if has_max else 0,
				"uoms": i.get("uoms") or [],
				"max_discount": i.get("max_discount") or 0,
				"disabled": i.get("disabled") or 0,
			})

	return {
		"name": doc.name,
		"title": doc.title,
		"disabled": cint(doc.disable),
		"status": _status(doc.as_dict(), today),
		"simple": 1 if _is_simple(doc.as_dict()) else 0,
		"everyone": 1 if _same_scope(doc.as_dict(), root) else 0,
		"scope": _scope_label(doc.as_dict(), root),
		"apply_on": doc.apply_on,
		"discount": _describe_discount(doc.as_dict()),
		"discount_percentage": flt(doc.discount_percentage),
		"valid_from": doc.valid_from,
		"valid_upto": doc.valid_upto,
		"price_list": doc.for_price_list or "",
		"priority": cint(doc.priority),
		"company": doc.company or "",
		"currency": doc.currency,
		"description": doc.rule_description or "",
		"items": items,
		"has_max": 1 if has_max else 0,
		"can_write": 1 if doc.has_permission("write") else 0,
		"can_delete": 1 if doc.has_permission("delete") else 0,
		"modified": doc.modified,
	}


def _item_info(item_codes):
	"""name, UOMs, max_discount and disabled for each existing item. Keys are
	the canonical codes; `_resolve_items` maps typed spellings onto them."""
	codes = list({c for c in item_codes if c})
	if not codes:
		return {}
	info = {}
	for i in frappe.db.sql(
		"""select name, item_name, stock_uom, max_discount, disabled
		from tabItem where name in %(c)s""",
		{"c": codes},
		as_dict=True,
	):
		info[i.name] = {
			"item_code": i.name,
			"item_name": i.item_name,
			"stock_uom": i.stock_uom,
			"max_discount": flt(i.max_discount),
			"disabled": cint(i.disabled),
			"uoms": [i.stock_uom] if i.stock_uom else [],
		}
	if info:
		for u in frappe.db.sql(
			"select parent, uom from `tabUOM Conversion Detail` where parent in %(c)s order by idx",
			{"c": list(info)},
			as_dict=True,
		):
			lst = info[u.parent]["uoms"]
			if u.uom and u.uom not in lst:
				lst.append(u.uom)
	return info


@frappe.whitelist()
def get_item_info(item_codes):
	"""For rows added by hand in the rule drawer."""
	_check_perm("read")
	if isinstance(item_codes, str):
		item_codes = json.loads(item_codes) if item_codes.strip().startswith("[") else re.split(r"[\s,;]+", item_codes)
	resolved = _resolve_items([c for c in item_codes if c])
	info = _item_info(list(resolved.values()))
	found, missing = [], []
	for typed in item_codes:
		if not typed:
			continue
		code = resolved.get(typed.strip().lower())
		if code and code in info:
			found.append(info[code])
		else:
			missing.append(typed)
	return {"items": found, "missing": missing}


def _resolve_items(typed_codes):
	"""Map lowercased typed codes to Item names. MariaDB compares
	case-insensitively, so one query finds 'abc' for 'ABC'; the map keeps the
	stored spelling so a rule never links to a code that only matches by case."""
	typed = list({str(c).strip() for c in typed_codes if str(c).strip()})
	out = {}
	for i in range(0, len(typed), 1000):
		chunk = typed[i:i + 1000]
		for name, in frappe.db.sql("select name from tabItem where name in %(c)s", {"c": chunk}):
			out[name.lower()] = name
	return out


# ---------------------------------------------------------------------------
# overlaps with existing rules
# ---------------------------------------------------------------------------

def _candidate(item_uoms, company, valid_from, valid_upto, price_list, name=None, priority=0):
	"""A rule of this page's fixed shape, as a dict the conflict finder reads."""
	return frappe._dict(
		name=name or "", disable=0, apply_on="Item Code", price_or_product_discount="Price",
		rate_or_discount="Discount Percentage", selling=1, buying=0,
		applicable_for="Customer Group", customer_group=_root_customer_group(),
		company=company, currency=_company_currency(company), for_price_list=price_list or "",
		valid_from=valid_from or nowdate(), valid_upto=valid_upto or None, priority=priority,
		items=[{"item_code": c, "uom": u or ""} for c, u in item_uoms.items()],
	)


def _overlaps(item_uoms, company, valid_from, valid_upto, price_list, exclude=None):
	"""Active rules that would also match these items, one row per (item, rule).
	The matching is pricing_rule_conflicts.find_conflicts, the same check that
	guards every Pricing Rule save. `kind`:
	  conflict  - equal footing: ERPNext refuses the sales line (and the save)
	  shadowed  - the other rule wins quietly: higher priority, or it names the
	              price list and ours does not
	`same_scope` marks rules that, like ours, reach every customer."""
	if not item_uoms:
		return []
	root = _root_customer_group()
	cand = _candidate(item_uoms, company, valid_from, valid_upto, price_list, name=exclude)
	out = []
	for c in prc.find_conflicts(cand, include_shadowed=True):
		same = _same_scope({"applicable_for": c["applicable_for"], "customer_group": c["party"]}, root)
		for code in c["shared"]:
			out.append({
				"item_code": code,
				"rule": c["rule"],
				"title": c["title"],
				"discount": c["discount"],
				"scope": c["parties"],
				"same_scope": 1 if same else 0,
				"kind": c["kind"],
				"priority": c["priority"],
				"price_list": c["price_list"],
				"promotional_scheme": c["promotional_scheme"],
				"valid_upto": c["valid_upto"],
			})
	return sorted(out, key=lambda x: (x["item_code"], x["rule"]))


def _take_items_out(overlaps):
	"""Remove the overlapping items from the other rules. A rule left with no
	items is disabled instead, since ERPNext will not save an Item Code rule with
	an empty table; its rows stay for the record. Rules generated by a
	Promotional Scheme are left alone (the scheme would put the items back)."""
	per_rule = {}
	for o in overlaps:
		if not o.get("promotional_scheme"):
			per_rule.setdefault(o["rule"], set()).add(o["item_code"])
	touched = []
	for name, codes in per_rule.items():
		doc = frappe.get_doc("Pricing Rule", name)
		doc.check_permission("write")
		# only ever reduces overlaps; must not trip over the old rule's own clashes
		doc.flags.ignore_pricing_rule_conflicts = True
		keep = [d for d in doc.items if d.item_code not in codes]
		if keep:
			doc.set("items", keep)
			action = "trimmed"
		else:
			doc.disable = 1
			action = "disabled"
		doc.save()
		touched.append({"rule": name, "title": doc.title, "items": sorted(codes), "action": action})
	return touched


def _winning_priority(cand):
	p = prc.suggest_priority(cand, include_shadowed=True)
	if not p:
		frappe.throw(_("No priority up to 20 makes the new rule win over the existing ones. "
			"Move the items instead, or leave them out."))
	return p


# ---------------------------------------------------------------------------
# create / edit
# ---------------------------------------------------------------------------

def _apply_static(doc, company):
	"""The fixed half of every rule made here."""
	doc.apply_on = "Item Code"
	doc.price_or_product_discount = "Price"
	doc.selling = 1
	doc.buying = 0
	doc.rate_or_discount = "Discount Percentage"
	doc.margin_type = ""
	doc.margin_rate_or_amount = 0
	doc.applicable_for = "Customer Group"
	doc.customer_group = _root_customer_group()
	doc.mixed_conditions = 0
	doc.is_cumulative = 0
	doc.apply_rule_on_other = ""
	doc.company = company
	doc.currency = _company_currency(company)


def _validate_discount(value):
	d = flt(value)
	if d <= 0 or d > 100:
		frappe.throw(_("Discount must be more than 0 and at most 100 (got {0}).").format(_fmt_pct(value)))
	return round(d, 4)


@frappe.whitelist()
def save_rule(payload):
	"""Create or update a rule from the drawer.

	payload: name?, title, discount_percentage, valid_from, valid_upto,
	price_list, disabled, items[{item_code, uom, max}],
	resolve: ''       - if items overlap another active rule, save nothing and
	                    return the overlaps (and a winning priority) instead
	         'move'     - take the shared items out of the other rules
	         'priority' - give this rule the lowest priority that wins
	         'keep'     - save as is (the save guard still refuses a real conflict)
	"""
	payload = frappe.parse_json(payload)
	company = payload.get("company")
	name = payload.get("name")

	if name:
		doc = frappe.get_doc("Pricing Rule", name)
		doc.check_permission("write")
		if not _is_simple(doc.as_dict()):
			frappe.throw(_("{0} is not a simple item discount rule. Edit it in the desk form.").format(name))
		company = doc.company or company
	else:
		_check_perm("create")
		if not company:
			frappe.throw(_("Choose a company in the sidebar first."))
		doc = frappe.new_doc("Pricing Rule")

	title = (payload.get("title") or "").strip()
	if not title:
		frappe.throw(_("Give the rule a title."))
	discount = _validate_discount(payload.get("discount_percentage"))

	valid_from = payload.get("valid_from") or nowdate()
	valid_upto = payload.get("valid_upto") or None
	if valid_upto and getdate(valid_upto) < getdate(valid_from):
		frappe.throw(_("Valid Upto cannot be before Valid From."))

	rows, seen = [], set()
	typed = [str(r.get("item_code") or "").strip() for r in (payload.get("items") or [])]
	resolved = _resolve_items(typed)
	info = _item_info(list(resolved.values()))
	for r in payload.get("items") or []:
		code = resolved.get(str(r.get("item_code") or "").strip().lower())
		if not code:
			frappe.throw(_("Item {0} does not exist.").format(r.get("item_code")))
		if code in seen:
			frappe.throw(_("Item {0} is listed twice.").format(code))
		seen.add(code)
		uom = (r.get("uom") or "").strip()
		if uom and uom not in (info[code]["uoms"] or []):
			frappe.throw(_("{0} is not a unit of item {1}.").format(uom, code))
		rows.append({"item_code": code, "uom": uom or None, "max": max(cint(r.get("max")), 0)})
	if not rows:
		frappe.throw(_("Add at least one item."))

	price_list = payload.get("price_list") or ""
	disabled = cint(payload.get("disabled"))

	moved = []
	priority = cint(doc.priority) if name else 0
	if not disabled:
		item_uoms = {r["item_code"]: r["uom"] or "" for r in rows}
		overlaps = _overlaps(item_uoms, company, valid_from, valid_upto, price_list,
			exclude=doc.name if name else None)
		if overlaps:
			resolve = payload.get("resolve") or ""
			cand = _candidate(item_uoms, company, valid_from, valid_upto, price_list,
				name=doc.name if name else None, priority=priority)
			if not resolve:
				return {"saved": 0, "overlaps": overlaps,
					"suggested_priority": prc.suggest_priority(cand, include_shadowed=True)}
			if resolve == "move":
				moved = _take_items_out(overlaps)
			elif resolve == "priority":
				priority = _winning_priority(cand)

	_apply_static(doc, company)
	doc.title = title[:MAX_TITLE]
	doc.discount_percentage = discount
	doc.valid_from = valid_from
	doc.valid_upto = valid_upto
	doc.for_price_list = price_list or None
	doc.disable = disabled
	doc.priority = str(priority) if priority else ""
	has_max = _has_max_field()
	doc.set("items", [])
	for r in rows:
		row = {"item_code": r["item_code"], "uom": r["uom"]}
		if has_max:
			row["max"] = r["max"]
		doc.append("items", row)
	if name:
		doc.save()
	else:
		doc.rule_description = _("Created in Pricing Rules Manager by {0} on {1}.").format(
			frappe.session.user, formatdate(nowdate())
		)
		doc.insert()
	return {"saved": 1, "name": doc.name, "moved": moved, "priority": priority}


@frappe.whitelist()
def set_disabled(names, disabled):
	names = frappe.parse_json(names) if isinstance(names, str) and names.startswith("[") else names
	if isinstance(names, str):
		names = [names]
	done = []
	for n in names:
		doc = frappe.get_doc("Pricing Rule", n)
		doc.check_permission("write")
		if cint(doc.disable) != cint(disabled):
			doc.disable = cint(disabled)
			doc.save()
		done.append(n)
	return {"count": len(done)}


@frappe.whitelist()
def delete_rules(names):
	names = frappe.parse_json(names) if isinstance(names, str) and names.startswith("[") else names
	if isinstance(names, str):
		names = [names]
	for n in names:
		frappe.delete_doc("Pricing Rule", n)
	return {"count": len(names)}


# ---------------------------------------------------------------------------
# template / export
# ---------------------------------------------------------------------------

def _write_xlsx(rows, extra_headers=None, sheet="Pricing Rules"):
	from io import BytesIO

	from openpyxl import Workbook
	from openpyxl.styles import Alignment, Font, PatternFill

	wb = Workbook()
	ws = wb.active
	ws.title = sheet
	headers = TEMPLATE_HEADERS + list(extra_headers or [])
	ws.append(headers)
	fill = PatternFill("solid", fgColor="1E293B")
	for cell in ws[1]:
		cell.font = Font(bold=True, color="FFFFFF")
		cell.fill = fill
		cell.alignment = Alignment(horizontal="center")
	for r in rows:
		ws.append(r)
	widths = [24, 10, 8, 12] + [36] * len(extra_headers or [])
	for idx, w in enumerate(widths):
		ws.column_dimensions[chr(ord("A") + idx)].width = w
	# Item codes are text: without this Excel turns 000123 into 123.
	for row in ws.iter_rows(min_row=2, max_col=1):
		for cell in row:
			cell.number_format = "@"
	ws.freeze_panes = "A2"

	notes = wb.create_sheet("How to fill")
	for line in (
		["Column", "What to type"],
		["Item Code", "Required. The item's code exactly as in ERPNext."],
		["UOM", "Optional. Leave blank so the discount applies in every unit; a unit limits it to that unit."],
		["Max", "Optional whole number, stored on the rule's item row (the Max column). Blank = 0."],
		["Discount %", "Required. 10 means 10%. 10% typed as a percentage cell also works."],
		[],
		["One Pricing Rule is created per distinct discount: every row at 10% goes into one rule, every row at 15% into another."],
		["Every rule is: Selling, Discount Percentage, Apply On Item Code, for all customers, in the company chosen on the page."],
		["Rows on this sheet are ignored; only the first sheet is read."],
	):
		notes.append(line)
	notes.column_dimensions["A"].width = 14
	notes.column_dimensions["B"].width = 100
	for cell in notes[1]:
		cell.font = Font(bold=True)

	buf = BytesIO()
	wb.save(buf)
	return buf.getvalue()


def _send(filename, content):
	"""Stream the workbook straight to the browser. Nothing is kept as a File,
	so repeated downloads do not pile up attachments."""
	frappe.local.response.filename = filename
	frappe.local.response.filecontent = content
	frappe.local.response.type = "binary"


@frappe.whitelist()
def download_template():
	_check_perm("read")
	_send("pricing_rules_template.xlsx", _write_xlsx([]))


@frappe.whitelist()
def export_rules(names):
	"""The items of the given rules in the template's own layout, plus the rule
	they came from. Re-importing the file (with 'Replace') moves every item to
	the discount in the file and empties the old rules."""
	_check_perm("read")
	names = frappe.parse_json(names)
	if not names:
		frappe.throw(_("Nothing to export."))
	has_max = _has_max_field()
	rows = frappe.db.sql(
		"""
		select pri.item_code, ifnull(pri.uom, '') as uom, {0} as mx, pr.discount_percentage, pr.name, pr.title
		from `tabPricing Rule Item Code` pri
		inner join `tabPricing Rule` pr on pr.name = pri.parent
		where pr.name in %(n)s and pr.rate_or_discount = 'Discount Percentage'
		order by pr.discount_percentage, pr.name, pri.idx
		""".format("pri.`max`" if has_max else "0"),
		{"n": names},
		as_dict=True,
	)
	data = [[r.item_code, r.uom, cint(r.mx), flt(r.discount_percentage), "{0} · {1}".format(r.name, r.title)] for r in rows]
	content = _write_xlsx(data, extra_headers=["Rule (ignored on import)"])
	stamp = now_datetime().strftime("%Y%m%d_%H%M%S")
	_send("pricing_rules_{0}.xlsx".format(stamp), content)


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

def _norm_header(h):
	return re.sub(r"[^a-z0-9]", "", str(h or "").lower()
		.replace("ó", "o").replace("á", "a").replace("ã", "a").replace("í", "i").replace("ç", "c"))


def _read_file(file_url):
	"""Rows of the first sheet as lists, plus the header positions. Percent-
	formatted discount cells are scaled back to what the user sees (0.1 -> 10)."""
	if not file_url:
		frappe.throw(_("Upload a file first."))
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	path = file_doc.get_full_path()
	fname = (file_doc.file_name or path).lower()

	grid = []
	if fname.endswith(".csv"):
		with open(path, "r", encoding="utf-8-sig", newline="") as f:
			sample = f.read(4096)
			f.seek(0)
			try:
				dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
			except csv.Error:
				dialect = csv.excel
			grid = [[(c, False) for c in row] for row in csv.reader(f, dialect)]
	elif fname.endswith(".xlsx"):
		from openpyxl import load_workbook

		wb = load_workbook(path, read_only=True, data_only=True)
		ws = wb.worksheets[0]
		for row in ws.iter_rows():
			grid.append([
				(c.value, "%" in str(getattr(c, "number_format", "") or "")) for c in row
			])
		wb.close()
	else:
		frappe.throw(_("Upload an .xlsx or .csv file."))

	# The header is the first row that names an item-code column.
	header_at, cols = None, {}
	for idx, row in enumerate(grid[:10]):
		found = {}
		for pos, (v, _pct) in enumerate(row):
			key = _norm_header(v)
			for field, aliases in HEADER_ALIASES.items():
				if key in aliases and field not in found:
					found[field] = pos
		if "item_code" in found:
			header_at, cols = idx, found
			break
	if header_at is None:
		frappe.throw(_("No 'Item Code' column found. Use the template: {0}.").format(", ".join(TEMPLATE_HEADERS)))
	if "discount" not in cols:
		frappe.throw(_("No 'Discount %' column found."))
	return grid[header_at + 1:], cols, header_at + 1, file_doc.file_name


def _cell(row, pos):
	if pos is None or pos >= len(row):
		return None, False
	return row[pos]


def _parse_discount(value, is_pct_cell):
	if value is None or str(value).strip() == "":
		return None
	if isinstance(value, (int, float)):
		d = float(value) * (100 if is_pct_cell else 1)
	else:
		s = str(value).strip().replace("%", "").replace(" ", "")
		if "," in s and "." not in s:
			s = s.replace(",", ".")
		try:
			d = float(s)
		except ValueError:
			raise ValueError(_("'{0}' is not a number").format(value))
	return round(d, 4)


def _analyze(file_url, company, valid_from, valid_upto, price_list):
	if not company:
		frappe.throw(_("Choose a company in the sidebar first."))
	if valid_upto and getdate(valid_upto) < getdate(valid_from or nowdate()):
		frappe.throw(_("Valid Upto cannot be before Valid From."))

	data, cols, header_row, file_name = _read_file(file_url)

	raw = []
	for offset, row in enumerate(data):
		code_v, _p = _cell(row, cols.get("item_code"))
		disc_v, disc_pct = _cell(row, cols.get("discount"))
		uom_v, _p = _cell(row, cols.get("uom"))
		max_v, _p = _cell(row, cols.get("max"))
		code = str(code_v).strip() if code_v is not None else ""
		if isinstance(code_v, float) and code_v.is_integer():
			code = str(int(code_v))
		if not code and (disc_v is None or str(disc_v).strip() == ""):
			continue  # blank line
		raw.append({
			"row": header_row + offset + 1,
			"typed_code": code,
			"uom": str(uom_v).strip() if uom_v is not None else "",
			"max": max_v,
			"discount": disc_v,
			"discount_pct": disc_pct,
		})

	resolved = _resolve_items([r["typed_code"] for r in raw])
	info = _item_info(list(resolved.values()))

	ok, errors, warnings = [], [], []
	seen = {}  # item_code -> first valid row
	for r in raw:
		code = resolved.get(r["typed_code"].lower()) if r["typed_code"] else None

		def err(msg):
			errors.append({"row": r["row"], "item_code": r["typed_code"], "error": msg})

		if not r["typed_code"]:
			err(_("Item Code is empty"))
			continue
		if not code:
			err(_("Item does not exist"))
			continue
		try:
			discount = _parse_discount(r["discount"], r["discount_pct"])
		except ValueError as e:
			err(_("Discount: {0}").format(e))
			continue
		if discount is None:
			err(_("Discount is empty"))
			continue
		if discount <= 0 or discount > 100:
			err(_("Discount must be more than 0 and at most 100 (got {0})").format(_fmt_pct(discount)))
			continue
		i = info[code]
		if i["max_discount"] and discount > i["max_discount"]:
			err(_("Item allows at most {0}% discount").format(_fmt_pct(i["max_discount"])))
			continue

		uom = r["uom"]
		if uom:
			match = [u for u in i["uoms"] if u.lower() == uom.lower()]
			if not match:
				err(_("{0} is not a unit of this item (units: {1})").format(uom, ", ".join(i["uoms"]) or "-"))
				continue
			uom = match[0]

		mx_raw = r["max"]
		try:
			mx = 0 if mx_raw is None or str(mx_raw).strip() == "" else float(str(mx_raw).replace(",", "."))
		except ValueError:
			err(_("Max '{0}' is not a number").format(mx_raw))
			continue
		if mx < 0 or mx != int(mx):
			err(_("Max must be a whole number of 0 or more"))
			continue

		if code in seen:
			first = seen[code]
			err(_("Item already on row {0}. One item can have one discount; use one row per item.").format(first["row"]))
			continue

		if i["disabled"]:
			warnings.append({"row": r["row"], "item_code": code, "warning": _("Item is disabled")})
		if code != r["typed_code"]:
			warnings.append({"row": r["row"], "item_code": code,
				"warning": _("Typed as '{0}', matched item {1}").format(r["typed_code"], code)})

		entry = {"row": r["row"], "item_code": code, "item_name": i["item_name"], "uom": uom,
			"max": int(mx), "discount": discount}
		seen[code] = entry
		ok.append(entry)

	groups = {}
	for e in ok:
		groups.setdefault(e["discount"], []).append(e)

	overlaps = _overlaps({e["item_code"]: e["uom"] for e in ok}, company, valid_from, valid_upto, price_list)
	return {
		"file_name": file_name,
		"rows": len(raw),
		"ok": ok,
		"errors": errors,
		"warnings": warnings,
		"groups": [{"discount": d, "items": groups[d]} for d in sorted(groups)],
		"overlaps": overlaps,
	}


@frappe.whitelist()
def preview_import(file_url, company=None, valid_from=None, valid_upto=None, price_list=None):
	_check_perm("read")
	res = _analyze(file_url, company, valid_from, valid_upto, price_list)
	# The preview lists every item per group; the client shows them collapsed.
	res.pop("ok", None)
	overlapping = {o["item_code"] for o in res["overlaps"]}
	for g in res["groups"]:
		g["priority"] = None
		if any(e["item_code"] in overlapping for e in g["items"]):
			g["priority"] = prc.suggest_priority(_candidate(
				{e["item_code"]: e["uom"] for e in g["items"]}, company, valid_from, valid_upto, price_list),
				include_shadowed=True) or 0  # 0 = no priority wins
	return res


@frappe.whitelist()
def apply_import(file_url, company=None, title_prefix=None, valid_from=None, valid_upto=None,
		price_list=None, resolve="move"):
	"""Create one rule per distinct discount. The file is analysed again here,
	never trusted from the preview. Rows with errors are skipped.

	resolve: 'move'     - take overlapping items out of the other rules
	         'skip'     - leave those items out of the import
	         'priority' - each new rule that meets an old one gets the lowest
	                      priority that wins over it; the old rules are untouched
	"""
	_check_perm("create")
	if resolve not in ("move", "skip", "priority"):
		frappe.throw(_("Unknown overlap choice {0}").format(resolve))
	valid_from = valid_from or nowdate()
	res = _analyze(file_url, company, valid_from, valid_upto, price_list)

	overlaps = res["overlaps"]
	moved, skipped = [], set()
	if overlaps:
		if resolve == "move":
			moved = _take_items_out(overlaps)
		elif resolve == "skip":
			skipped = {o["item_code"] for o in overlaps}
	overlapping = {o["item_code"] for o in overlaps}

	prefix = (title_prefix or "").strip() or _("Import {0}").format(formatdate(nowdate()))
	has_max = _has_max_field()
	created = []
	for group in res["groups"]:
		items = [e for e in group["items"] if e["item_code"] not in skipped]
		if not items:
			continue
		label = _fmt_pct(group["discount"]) + "%"
		doc = frappe.new_doc("Pricing Rule")
		_apply_static(doc, company)
		doc.title = "{0} - {1}".format(prefix[:MAX_TITLE - len(label) - 3], label)
		doc.discount_percentage = group["discount"]
		doc.valid_from = valid_from
		doc.valid_upto = valid_upto or None
		doc.for_price_list = price_list or None
		if resolve == "priority" and any(e["item_code"] in overlapping for e in items):
			doc.priority = str(_winning_priority(_candidate(
				{e["item_code"]: e["uom"] for e in items}, company, valid_from, valid_upto, price_list)))
		doc.rule_description = _("Imported in Pricing Rules Manager from {0} by {1} on {2}.").format(
			res["file_name"], frappe.session.user, formatdate(nowdate())
		)
		for e in items:
			row = {"item_code": e["item_code"], "uom": e["uom"] or None}
			if has_max:
				row["max"] = e["max"]
			doc.append("items", row)
		doc.insert()
		created.append({"name": doc.name, "title": doc.title, "discount": group["discount"], "items": len(items),
			"priority": cint(doc.priority)})

	return {
		"created": created,
		"moved": moved,
		"skipped_overlap": sorted(skipped),
		"errors": res["errors"],
	}
