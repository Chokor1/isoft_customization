"""Multi-buy (Buy X get Y at d%) document engine.

Runs right before every calculate_taxes_and_totals during validate (the wrapper is put on
in before_validate, as linked_document_prices does), on Quotation / Sales Order /
Delivery Note / Sales Invoice, desk and POS. It:

1. works out each row's normal pricing rule itself (POS never sends `pricing_rules`);
2. leaves out rows whose discount the normal rule does not explain (typed discounts,
   POS offers, barcode discounts), free items, rows kept by the keep-prices switches and
   rows carried with a multi-buy result from their source document;
3. per multi-buy rule, highest priority first, pools the eligible units of the rows it
   matches (a normal rule of higher or equal priority keeps its row); a basket that does
   not qualify frees its rows for the next rule, and they keep their normal discount;
4. gives the cheapest floor(N / (Buy+Get)) x Get units the rule's discount, written as a
   blended row discount plus the row fields isoft_multibuy_rule / _units / _pct.

Rules come from ERPNext's own lookup (multi_buy_rule.multibuy_lookup), so Apply On,
customer / group / territory, store, price list, currency and dates match exactly as for
any pricing rule. Spec: docs/superpowers/specs/2026-11-09-multi-buy-pricing-rule-design.md
"""
import json
import math

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from isoft_customization.multi_buy_rule import multibuy_lookup

DOCTYPES = ("Quotation", "Sales Order", "Delivery Note", "Sales Invoice")
SOURCE_LINKS = (
	# (row field, source item doctype)
	("quotation_item", "Quotation Item"),
	("so_detail", "Sales Order Item"),
	("dn_detail", "Delivery Note Item"),
)
ROW_FIELDS = ("isoft_multibuy_rule", "isoft_multibuy_units", "isoft_multibuy_pct")
TOL = 0.01


# ---------------------------------------------------------------------------- allocation
def allocate(units, buy, get, max_units=0):
	"""units: [(row_key, unit_price, idx, count)]. The cheapest floor(N/(buy+get))*get units
	(ties by idx) are discounted. Returns {row_key: discounted_count}."""
	n = sum(max(0, int(c)) for _k, _p, _i, c in units)
	group = cint(buy) + cint(get)
	if group <= 0:
		return {}
	d = (n // group) * cint(get)
	if cint(max_units) > 0:
		d = min(d, cint(max_units))
	out = {}
	for key, _price, _idx, count in sorted(units, key=lambda u: (flt(u[1]), u[2])):
		if d <= 0:
			break
		take = min(int(count), d)
		if take > 0:
			out[key] = out.get(key, 0) + take
			d -= take
	return out


# ---------------------------------------------------------------------------- hooks
def before_validate(doc, method=None, *args, **kwargs):
	if doc.doctype not in DOCTYPES or doc.docstatus != 0:
		return
	_ensure_lookup_wrapper()  # before ERPNext prices the rows in validate
	core = doc.calculate_taxes_and_totals

	def calculate_taxes_and_totals(*a, **kw):
		if not doc.flags.isoft_multibuy_running:
			doc.flags.isoft_multibuy_running = True
			try:
				apply(doc)
			finally:
				doc.flags.isoft_multibuy_running = False
		return core(*a, **kw)

	doc.calculate_taxes_and_totals = calculate_taxes_and_totals


def release(doc, method=None, *args, **kwargs):
	doc.__dict__.pop("calculate_taxes_and_totals", None)
	doc.flags.isoft_multibuy_cache = None
	if cint(doc.get("is_return")) and doc.docstatus < 2:
		validate_return(doc)


# ---------------------------------------------------------------------------- returns
RETURN_REF = {"Sales Invoice": "sales_invoice_item", "Delivery Note": "dn_detail"}


def validate_return(doc):
	"""A rule without "Allow partial return": what the customer keeps after this return
	(and the submitted ones before it) may not carry more discount than it earns."""
	ref_field = RETURN_REF.get(doc.doctype)
	if not ref_field or not doc.get("return_against"):
		return
	rules = {r.isoft_multibuy_rule for r in doc.items if r.get("isoft_multibuy_rule")}
	item_dt = doc.doctype + " Item"
	for rule_name in rules:
		rule = frappe.db.get_value("Pricing Rule", rule_name,
			["isoft_buy_qty", "isoft_get_qty", "isoft_multibuy_discount", "isoft_multibuy_max_units", "isoft_allow_partial_return"],
			as_dict=True)
		if not rule or cint(rule.isoft_allow_partial_return):
			continue
		original = frappe.get_all(item_dt,
			filters={"parent": doc.return_against, "isoft_multibuy_rule": rule_name},
			fields=["name", "idx", "item_code", "qty", "price_list_rate", "rate", "conversion_factor", "isoft_multibuy_units"])
		if not original:
			continue
		names = [o.name for o in original]
		returned = {}
		for name, qty in frappe.db.sql(
			"""select i.`{ref}`, sum(i.qty) from `tab{dt}` i join `tab{parent}` p on p.name = i.parent
			where p.docstatus = 1 and p.is_return = 1 and p.return_against = %s and i.`{ref}` in %s and p.name != %s
			group by i.`{ref}`""".format(ref=ref_field, dt=item_dt, parent=doc.doctype),
			(doc.return_against, tuple(names), doc.name or ""),
		):
			returned[name] = returned.get(name, 0) + abs(flt(qty))
		for r in doc.items:
			if r.get(ref_field) in names:
				returned[r.get(ref_field)] = returned.get(r.get(ref_field), 0) + abs(flt(r.qty))

		remaining = {o.name: max(0.0, flt(o.qty) - returned.get(o.name, 0)) for o in original}
		if not any(remaining.values()):
			continue  # everything of this offer came back
		kept = sum(remaining[o.name] * (flt(o.price_list_rate) - flt(o.rate)) for o in original)
		units = [(o.name, flt(o.price_list_rate) / (flt(o.conversion_factor) or 1), cint(o.idx),
			int(math.floor(remaining[o.name] * (flt(o.conversion_factor) or 1) + 1e-9))) for o in original]
		given = allocate(units, rule.isoft_buy_qty, rule.isoft_get_qty, rule.isoft_multibuy_max_units)
		price = {u[0]: u[1] for u in units}
		earned = sum(cnt * price[name] * flt(rule.isoft_multibuy_discount) / 100.0 for name, cnt in given.items())
		if kept > earned + TOL:
			keep_discounted = sorted({o.item_code for o in original if flt(o.isoft_multibuy_units) and remaining[o.name] > 0})
			frappe.throw(
				_("This return breaks the offer {0}: the items kept would still carry {1} of discount but only earn {2}. "
					"Return the discounted item(s) too: {3}.").format(
					frappe.bold(frappe.db.get_value("Pricing Rule", rule_name, "title") or rule_name),
					frappe.format(kept, {"fieldtype": "Currency"}), frappe.format(earned, {"fieldtype": "Currency"}),
					", ".join(keep_discounted)),
				title=_("Partial return not allowed"),
			)


# ---------------------------------------------------------------------------- engine
def _ensure_lookup_wrapper():
	"""ERPNext's rule lookup must hide multi-buy rules (and show only them inside
	multibuy_lookup). The wrapper is installed per request / job and by the package import,
	but a process that loaded this app while frappe was still reading hooks (right after a
	cache clear: consoles, patches, scripts) has none: install it here, idempotent and cheap."""
	from isoft_customization.item_group_and_brand import apply as install

	install()


def apply(doc):
	result = {"rules": {}, "rows": {}}
	if doc.doctype not in DOCTYPES or cint(doc.get("is_return")) or not doc.get("items"):
		return result
	_ensure_lookup_wrapper()
	skip_all = cint(doc.get("ignore_pricing_rule")) and not cint(doc.get("is_pos"))
	cache = doc.flags.isoft_multibuy_cache = doc.flags.isoft_multibuy_cache or {}
	# Discounted units get their own line, as in the POS (whose cart does it itself), so a
	# desk document and a POS sale of the same basket total the same to the cent: one
	# blended line has to round its rate to 2 decimals and drifts with the quantity.
	split = not cint(doc.get("is_pos"))
	if split:
		_merge_split_rows(doc)

	candidates = []  # rows that may join a basket
	for row in doc.items:
		if not row.get("item_code"):
			continue
		if _carried(doc, row):
			_set_row(row, flt(row.isoft_multibuy_pct), row.isoft_multibuy_rule, flt(row.isoft_multibuy_units))
			continue
		was_ours = bool(row.get("isoft_multibuy_rule"))
		normal = _normal_effect(doc, row, cache)
		if not was_ours and _has_multibuy_rule(row.get("pricing_rules")):
			# priced by an ERPNext lookup that ran without the wrapper: that 0% is not a
			# typed discount, the row gets its real normal price
			_set_normal(row, normal)
			was_ours = True
		if was_ours:
			_set_normal(row, normal)  # start from the row's normal price
		if skip_all:
			continue
		if cint(row.get("is_free_item")) or flt(row.qty) <= 0 or _kept_by_switch(doc, row):
			continue
		if abs(_effective_rate(row) - normal["rate"]) > TOL and not was_ours:
			continue  # a discount its normal rule does not explain: typed, POS offer, barcode
		rules = _multibuy_rules(doc, row, cache)
		if rules:
			candidates.append((row, normal, rules))

	free = {id(r): (r, normal, rules) for r, normal, rules in candidates}
	all_rules = {}
	for _r, _n, rules in candidates:
		for rule in rules:
			all_rules[rule.name] = rule
	for rule in sorted(all_rules.values(), key=lambda x: (-cint(x.priority), x.name)):
		basket = [
			(r, normal) for r, normal, rules in free.values()
			if any(x.name == rule.name for x in rules) and (normal["priority"] is None or cint(rule.priority) > normal["priority"])
		]
		claimed = _evaluate(doc, rule, basket, split)
		if claimed is None:
			continue
		for r, _normal in basket:
			free.pop(id(r), None)
		result["rules"][rule.name] = claimed
		for r, info in claimed["rows"].items():
			result["rows"][r] = info
	return result


def _evaluate(doc, rule, basket, split=False):
	"""Price the rule's basket; None when it does not qualify (rows stay free)."""
	if not basket:
		return None
	units, amount, n = [], 0.0, 0
	for row, _normal in basket:
		cf = flt(row.conversion_factor) or 1
		# from qty: ERPNext refreshes stock_qty only later in validate
		count = int(math.floor(flt(row.qty) * cf + 1e-9))
		unit_price = flt(row.price_list_rate) / cf
		units.append((row.name or row.idx, unit_price, cint(row.idx), count))
		amount += flt(row.price_list_rate) * flt(row.qty)
		n += count
	if n < cint(rule.isoft_buy_qty) + cint(rule.isoft_get_qty):
		return None
	if flt(rule.min_qty) and n < flt(rule.min_qty):
		return None
	if flt(rule.max_qty) and n > flt(rule.max_qty):
		return None
	if flt(rule.min_amt) and amount < flt(rule.min_amt):
		return None
	if flt(rule.max_amt) and amount > flt(rule.max_amt):
		return None
	given = allocate(units, rule.isoft_buy_qty, rule.isoft_get_qty, rule.isoft_multibuy_max_units)
	if not given:
		return None
	d = flt(rule.isoft_multibuy_discount)
	out = {"units": sum(given.values()), "amount": 0.0, "rows": {}}
	for row, _normal in basket:
		key = row.name or row.idx
		cnt = given.get(key, 0)
		plr, qty = flt(row.price_list_rate), flt(row.qty)
		cf = flt(row.conversion_factor) or 1
		value = cnt * (plr / cf) * d / 100.0
		pct = 100.0 * value / (plr * qty) if plr and qty else 0
		cap = flt(frappe.get_cached_value("Item", row.item_code, "max_discount"))
		if cap > 0:
			pct = min(pct, cap)
		part_qty = cnt / cf
		if split and 0 < cnt and part_qty < qty - 1e-9 and abs(part_qty - round(part_qty)) < 1e-9 and _splittable(row):
			full = min(d, cap) if cap > 0 else d
			_split_row(doc, row, part_qty, cnt, full, rule.name)
			out["amount"] += (plr - flt(row.rate)) * flt(row.qty)
			out["rows"][key] = {"rule": rule.name, "units": 0, "pct": 0}
			continue
		_set_row(row, pct, rule.name, cnt)
		out["amount"] += (plr - flt(row.rate)) * qty
		out["rows"][key] = {"rule": rule.name, "units": cnt, "pct": flt(row.discount_percentage)}
	return out


# ---------------------------------------------------------------------------- line split
LINE_KEY = ("item_code", "uom", "conversion_factor", "warehouse", "batch_no", "price_list_rate", "description",
	"quotation_item", "prevdoc_docname", "so_detail", "dn_detail", "against_sales_order", "sales_order", "delivery_note")
LOCATION_FIELD = "custom_location_allocation"


def _splittable(row):
	"""Lines that can be cut in two without breaking what hangs off them."""
	if row.get("serial_no") or cint(row.get("is_free_item")):
		return False
	if row.get("item_code") and frappe.db.exists("Product Bundle", {"new_item_code": row.item_code}):
		return False  # packed items hang off the line by its name
	return True


def _line_key(row):
	return tuple(flt(row.get(f)) if f in ("conversion_factor", "price_list_rate") else (row.get(f) or "") for f in LINE_KEY)


def _merge_split_rows(doc):
	"""Lines this engine split are put back together before the offer is worked out again."""
	keep = {}
	for row in list(doc.items):
		if not row.get("isoft_multibuy_rule") or not row.get("item_code") or not _splittable(row) or _carried(doc, row):
			continue
		key = _line_key(row)
		first = keep.get(key)
		if first is None:
			keep[key] = row
			continue
		first.qty = flt(first.qty) + flt(row.qty)
		first.stock_qty = flt(first.qty) * (flt(first.conversion_factor) or 1)
		first.isoft_multibuy_units = flt(first.isoft_multibuy_units) + flt(row.isoft_multibuy_units)
		_merge_location(first, row)
		doc.remove(row)
	_reindex(doc)


def _split_row(doc, row, part_qty, units, pct, rule_name):
	"""`units` discounted stock units of `row` move to a new line just above it, at the full
	discount; the row keeps the rest at full price. The earlier line wins ties, so the next
	run (merge, then split again) lands on the same two lines."""
	cf = flt(row.conversion_factor) or 1
	data = {k: v for k, v in row.as_dict().items()
		if k not in ("name", "idx", "creation", "modified", "modified_by", "owner", "docstatus") and not isinstance(v, (list, tuple))}
	part = doc.append("items", data)
	doc.items.remove(part)
	doc.items.insert(doc.items.index(row), part)
	part.qty, part.stock_qty = part_qty, units
	row.qty = flt(row.qty) - part_qty
	row.stock_qty = flt(row.qty) * cf
	_split_location(row, part, units)
	_set_row(part, pct, rule_name, units)
	_set_row(row, 0, rule_name, 0)
	_reindex(doc)


def _reindex(doc):
	for i, r in enumerate(doc.items, 1):
		r.idx = i


def _plan(row):
	try:
		return json.loads(row.get(LOCATION_FIELD) or "[]") or []
	except ValueError:
		return []


def _set_plan(row, plan):
	plan = [x for x in plan if flt(x.get("qty")) > 0]
	row.set(LOCATION_FIELD, json.dumps(plan) if plan else "")
	if plan and row.meta.has_field("custom_from_location"):
		row.custom_from_location = sorted(plan, key=lambda x: -flt(x.get("qty")))[0].get("location")


def _split_location(row, part, units):
	"""Isoft Location Manager: each line's pick plan must add up to that line."""
	if not row.meta.has_field(LOCATION_FIELD):
		return
	plan = _plan(row)
	if not plan:
		return
	need, mine, rest = flt(units), [], []
	for x in plan:
		take = min(flt(x.get("qty")), need)
		if take > 0:
			mine.append(dict(x, qty=take))
		if flt(x.get("qty")) - take > 0:
			rest.append(dict(x, qty=flt(x.get("qty")) - take))
		need -= take
	_set_plan(part, mine)
	_set_plan(row, rest)


def _merge_location(into, other):
	if not into.meta.has_field(LOCATION_FIELD):
		return
	a, b = _plan(into), _plan(other)
	if not a or not b:
		into.set(LOCATION_FIELD, "")  # the Location Manager plans the line again
		return
	by = {}
	for x in a + b:
		cur = by.setdefault(x.get("location"), dict(x, qty=0))
		cur["qty"] = flt(cur["qty"]) + flt(x.get("qty"))
	_set_plan(into, list(by.values()))


def _effective_rate(row):
	"""The row's rate, or what ERPNext will make of its discount when the rate is still empty."""
	if flt(row.rate):
		return flt(row.rate)
	plr = flt(row.price_list_rate)
	if flt(row.discount_percentage):
		return flt(plr * (1 - flt(row.discount_percentage) / 100.0), row.precision("rate"))
	return flt(plr - flt(row.discount_amount), row.precision("rate"))


def _set_row(row, pct, rule_name, units):
	plr = flt(row.price_list_rate)
	row.rate = flt(plr * (1 - flt(pct) / 100.0), row.precision("rate")) if plr else flt(row.rate)
	row.discount_percentage = flt(100.0 * (plr - row.rate) / plr, row.precision("discount_percentage")) if plr else 0
	row.discount_amount = flt(plr - row.rate, row.precision("discount_amount")) if plr else 0
	row.margin_type, row.margin_rate_or_amount, row.rate_with_margin = "", 0, 0
	row.pricing_rules = ""
	row.isoft_multibuy_rule = rule_name or None
	row.isoft_multibuy_units = flt(units)
	row.isoft_multibuy_pct = flt(pct)


def _set_normal(row, normal):
	row.isoft_multibuy_rule, row.isoft_multibuy_units, row.isoft_multibuy_pct = None, 0, 0
	row.rate = normal["rate"]
	plr = flt(row.price_list_rate)
	row.discount_percentage = flt(100.0 * (plr - row.rate) / plr, row.precision("discount_percentage")) if plr else 0
	row.discount_amount = flt(plr - row.rate, row.precision("discount_amount")) if plr else 0
	row.pricing_rules = normal["pricing_rules"] or ""


def _carried(doc, row):
	"""A row made from a source document that had a multi-buy result keeps it."""
	if doc.doctype == "Quotation" or not row.get("isoft_multibuy_rule"):
		return False
	for field, source_dt in SOURCE_LINKS:
		ref = row.get(field)
		if ref and frappe.db.get_value(source_dt, ref, "isoft_multibuy_rule") == row.isoft_multibuy_rule:
			return True
	# Sales Order from a Quotation: v13 links the row only by the quotation's name
	if doc.doctype == "Sales Order" and row.get("prevdoc_docname"):
		return bool(frappe.db.exists("Quotation Item", {
			"parent": row.prevdoc_docname, "item_code": row.item_code, "isoft_multibuy_rule": row.isoft_multibuy_rule}))
	return False


def _kept_by_switch(doc, row):
	if doc.doctype != "Sales Invoice" or not row.get("dn_detail"):
		return False
	from isoft_customization.linked_document_prices import LINKS, is_enabled

	link = LINKS["Sales Invoice"]
	return bool(is_enabled(link, link.keep) or is_enabled(link, link.no_rules))


def _context(doc):
	customer = doc.get("customer") or (doc.get("party_name") if doc.get("quotation_to") == "Customer" else None)
	group = doc.get("customer_group") or (frappe.get_cached_value("Customer", customer, "customer_group") if customer else None)
	territory = doc.get("territory") or (frappe.get_cached_value("Customer", customer, "territory") if customer else None)
	return frappe._dict(
		customer=customer,
		customer_group=group or _root("Customer Group"),
		territory=territory or _root("Territory"),
		date=doc.get("posting_date") or doc.get("transaction_date") or nowdate(),
	)


def _root(doctype):
	field = "parent_" + frappe.scrub(doctype)
	r = frappe.db.sql("select name from `tab{0}` where is_group=1 and ifnull(`{1}`,'')='' order by lft limit 1".format(doctype, field))
	return r[0][0] if r else None


def _normal_effect(doc, row, cache):
	"""The row's price under its normal pricing rule (multi-buy rules are invisible here)."""
	from erpnext.stock.get_item_details import get_item_details

	ctx = _context(doc)
	key = ("normal", row.item_code, flt(row.qty), row.uom, flt(row.conversion_factor), flt(row.price_list_rate),
		row.get("warehouse"), ctx.customer, ctx.customer_group, str(ctx.date), doc.get("selling_price_list"), doc.get("currency"))
	if key in cache:
		return cache[key]
	parent = {k: v for k, v in doc.as_dict().items() if not isinstance(v, (list, tuple))}
	args = frappe._dict(parent)
	args.update({k: v for k, v in row.as_dict().items() if not isinstance(v, (list, tuple))})
	args.update({
		"doctype": doc.doctype, "name": doc.name, "child_docname": row.name, "parenttype": doc.doctype,
		"ignore_pricing_rule": 0, "is_pos": 0, "customer": ctx.customer, "customer_group": ctx.customer_group,
		"territory": ctx.territory, "transaction_date": ctx.date, "posting_date": ctx.date,
		"price_list": doc.get("selling_price_list"), "selling_price_list": doc.get("selling_price_list"),
		# the row's current discount must not be echoed back as if a rule gave it
		"pricing_rules": None, "rate": None, "discount_percentage": 0, "discount_amount": 0,
		"margin_type": None, "margin_rate_or_amount": 0, "rate_with_margin": 0,
	})
	log_len = len(frappe.local.message_log or [])
	try:
		out = frappe._dict(get_item_details(args, None, for_validate=True, overwrite_warehouse=False) or {})
	except Exception:  # noqa: BLE001 - a row ERPNext can't price has no normal rule
		del frappe.local.message_log[log_len:]
		out = frappe._dict()
	plr = flt(row.price_list_rate)
	rules = [n for n in _rule_names(out.get("pricing_rules")) if not cint(frappe.db.get_value("Pricing Rule", n, "isoft_multibuy"))]
	pct, amt = flt(out.get("discount_percentage")), flt(out.get("discount_amount"))
	if rules and frappe.db.get_value("Pricing Rule", rules[0], "rate_or_discount") == "Rate" and flt(out.get("price_list_rate")):
		rate = flt(out.price_list_rate)
	else:
		rate = plr * (1 - pct / 100.0) - (amt if not pct else 0)
	priority = max([cint(frappe.db.get_value("Pricing Rule", n, "priority")) for n in rules] or [0]) if rules else None
	res = {"rate": flt(rate, row.precision("rate")), "priority": priority,
		"pricing_rules": out.get("pricing_rules") if rules else ""}
	cache[key] = res
	return res


def _has_multibuy_rule(value):
	names = _rule_names(value)
	return bool(names) and bool(frappe.get_all("Pricing Rule", filters={"name": ["in", names], "isoft_multibuy": 1}, limit=1))


def _rule_names(value):
	if not value:
		return []
	if isinstance(value, (list, tuple)):
		return [v for v in value if v]
	try:
		names = json.loads(value)
	except ValueError:
		names = [x.strip() for x in str(value).split(",")]
	return [n for n in (names if isinstance(names, list) else [names]) if n]


def _multibuy_rules(doc, row, cache):
	from erpnext.accounts.doctype.pricing_rule import utils as prutils

	ctx = _context(doc)
	item = frappe.get_cached_value("Item", row.item_code, ["item_group", "brand", "variant_of"], as_dict=True) or {}
	warehouse = row.get("warehouse") or doc.get("set_warehouse")
	key = ("mb", row.item_code, warehouse, ctx.customer, ctx.customer_group, ctx.territory, str(ctx.date),
		doc.get("selling_price_list"), doc.get("currency"), doc.company)
	if key in cache:
		return cache[key]
	args = frappe._dict(
		item_code=row.item_code, item_group=item.get("item_group"), brand=item.get("brand"), variant_of=item.get("variant_of"),
		company=doc.company, transaction_type="selling", customer=ctx.customer, customer_group=ctx.customer_group,
		territory=ctx.territory, currency=doc.get("currency"), price_list=doc.get("selling_price_list"),
		transaction_date=ctx.date, warehouse=warehouse, uom=row.uom, stock_uom=row.stock_uom,
		conversion_factor=row.conversion_factor, qty=row.qty, stock_qty=row.stock_qty,
	)
	found = {}
	with multibuy_lookup():
		for apply_on in ("Item Code", "Item Group", "Brand"):
			for r in prutils._get_pricing_rules(apply_on, args, {}) or []:
				if cint(r.get("isoft_multibuy")):  # explicit, whatever the lookup returned
					found.setdefault(r.name, frappe._dict(r))
	date = getdate(ctx.date)
	rules = [r for r in found.values()
		if (not r.valid_from or getdate(r.valid_from) <= date) and (not r.valid_upto or getdate(r.valid_upto) >= date)]
	cache[key] = rules
	return rules


@frappe.whitelist()
def preview(doc):
	"""What the engine would do to an unsaved document: per-row results and totals."""
	data = frappe.parse_json(doc) if isinstance(doc, str) else doc
	data = dict(data or {})
	if data.get("doctype") not in DOCTYPES:
		frappe.throw(_("Multi-buy preview is for Quotation, Sales Order, Delivery Note and Sales Invoice"))
	if not frappe.has_permission(data["doctype"], "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not frappe.db.exists("Pricing Rule", {"isoft_multibuy": 1, "disable": 0, "selling": 1}):
		return {"rows": [], "rules": {}, "none": 1}  # nothing to preview: callers can stop asking
	for k in ("name", "__islocal", "__unsaved", "docstatus", "amended_from"):
		data.pop(k, None)
	_ensure_lookup_wrapper()
	d = frappe.get_doc(data)
	log_len = len(frappe.local.message_log or [])
	try:
		d.set_missing_values()
	except Exception:  # noqa: BLE001 - a preview never raises over incomplete header data
		del frappe.local.message_log[log_len:]
	before_validate(d)
	d.calculate_taxes_and_totals()
	release(d)
	return {
		"rows": [
			{"idx": r.idx, "name": r.name, "item_code": r.item_code, "qty": flt(r.qty), "stock_qty": flt(r.stock_qty),
				"isoft_multibuy_rule": r.get("isoft_multibuy_rule"),
				# a line the engine split off has no name yet: the form copies it whole
				"doc": None if r.name else {k: v for k, v in r.as_dict(convert_dates_to_str=True).items() if not isinstance(v, (list, tuple))},
				"custom_location_allocation": r.get("custom_location_allocation"), "custom_from_location": r.get("custom_from_location"),
				"isoft_multibuy_units": flt(r.get("isoft_multibuy_units")), "isoft_multibuy_pct": flt(r.get("isoft_multibuy_pct")),
				"discount_percentage": flt(r.discount_percentage), "discount_amount": flt(r.discount_amount),
				"rate": flt(r.rate), "price_list_rate": flt(r.price_list_rate), "pricing_rules": r.get("pricing_rules")}
			for r in d.items
		],
		"rules": {
			n: frappe.db.get_value("Pricing Rule", n, ["title", "isoft_buy_qty", "isoft_get_qty", "isoft_multibuy_discount"], as_dict=True)
			for n in {r.get("isoft_multibuy_rule") for r in d.items if r.get("isoft_multibuy_rule")}
		},
		"multibuy_discount": flt(sum((flt(r.price_list_rate) - flt(r.rate)) * flt(r.qty) for r in d.items if r.get("isoft_multibuy_rule")), 2),
		"net_total": flt(d.net_total), "grand_total": flt(d.grand_total),
	}
