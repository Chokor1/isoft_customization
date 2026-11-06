"""Label prices through ERPNext's own pricing (get_item_details), never re-implemented rules.

Context of a shelf label: qty 1, today, no customer. Customer group and territory default to the
tree roots so rules set to "All Customer Groups" count as rules for everyone (the fork's
get_other_conditions drops them when no group is passed). With no store picked ERPNext ignores
rule warehouses completely, so a discount coming from a warehouse-scoped rule is dropped instead
of printed on every store's labels. A barcode's own discount replaces the rule's, as POS Awesome does.
"""

import json

import frappe
from frappe.utils import cint, flt, nowdate

ROOT_CUSTOMER_GROUP = "All Customer Groups"
ROOT_TERRITORY = "All Territories"


def _root(doctype, fallback):
	field = "parent_" + frappe.scrub(doctype)
	return frappe.db.get_value(doctype, {"is_group": 1, field: ("in", ("", None))}, "name") or fallback


def _barcode_row(barcode, item_code):
	if not barcode:
		return {}
	fields = ["barcode"]
	meta = frappe.get_meta("Item Barcode")
	for f in ("posa_uom", "discount"):
		if meta.has_field(f):
			fields.append(f)
	return frappe.db.get_value("Item Barcode", {"barcode": barcode, "parent": item_code}, fields, as_dict=True) or {}


def _conversion_factor(item_code, uom, stock_uom):
	if not uom or uom == stock_uom:
		return 1.0
	return flt(frappe.db.get_value("UOM Conversion Detail", {"parent": item_code, "uom": uom}, "conversion_factor")) or 1.0


def _rules_have_warehouse(pricing_rules):
	if not pricing_rules:
		return False
	if isinstance(pricing_rules, str):
		try:
			names = json.loads(pricing_rules)
		except ValueError:
			names = [n.strip() for n in pricing_rules.split(",")]
	else:
		names = list(pricing_rules)
	names = [n for n in names if n]
	return bool(names) and bool(frappe.get_all("Pricing Rule", filters={"name": ["in", names], "warehouse": ["is", "set"]}, limit=1))


def _tax_rate(out, opts, company):
	"""IVA % on top: the template rows of the category, each overridden by the item's tax rate."""
	item_rates = out.get("item_tax_rate") or {}
	if isinstance(item_rates, str):
		item_rates = json.loads(item_rates or "{}")
	template = frappe.db.get_value(
		"Sales Taxes and Charges Template",
		{"tax_category": opts.get("tax_category"), "company": company, "disabled": 0},
		"name",
		order_by="is_default desc, modified desc",
	)
	if template:
		rows = frappe.get_all(
			"Sales Taxes and Charges",
			filters={"parent": template, "parenttype": "Sales Taxes and Charges Template", "charge_type": "On Net Total"},
			fields=["account_head", "rate"],
		)
		if rows:
			return sum(flt(item_rates.get(r.account_head, r.rate)) for r in rows)
	# no template, or a template without rows (ITEC's NORMAL IVA on dev): the item's own rates
	return sum(flt(v) for v in item_rates.values())


def price_rows(rows, opts):
	from erpnext.stock.get_item_details import get_item_details

	opts = frappe._dict(opts or {})
	company = opts.company or frappe.defaults.get_user_default("Company") or frappe.db.get_default("company")
	price_list = opts.price_list
	pl_currency = frappe.db.get_value("Price List", price_list, "currency") if price_list else None
	currency = pl_currency or frappe.get_cached_value("Company", company, "default_currency")
	precision = cint(frappe.db.get_default("currency_precision")) or 2
	customer_group = opts.customer_group or _root("Customer Group", ROOT_CUSTOMER_GROUP)
	territory = _root("Territory", ROOT_TERRITORY)
	include_tax = cint(opts.include_tax) and opts.tax_category

	out_rows = []
	for row in rows:
		row = frappe._dict(row)
		item = frappe.get_cached_value("Item", row.item_code, ["item_name", "stock_uom"], as_dict=True)
		if not item:
			continue
		bc = _barcode_row(row.barcode, row.item_code)
		uom = row.uom or bc.get("posa_uom") or item.stock_uom
		cf = _conversion_factor(row.item_code, uom, item.stock_uom)
		args = frappe._dict({
			"doctype": "Sales Invoice",
			"item_code": row.item_code,
			"company": company,
			"selling_price_list": price_list,
			"price_list": price_list,
			"price_list_currency": currency,
			"currency": currency,
			"conversion_rate": 1,
			"plc_conversion_rate": 1,
			"qty": 1,
			"stock_qty": cf,
			"uom": uom,
			"stock_uom": item.stock_uom,
			"conversion_factor": cf,
			"transaction_date": nowdate(),
			"posting_date": nowdate(),
			"customer": None,
			"customer_group": customer_group,
			"territory": territory,
			"warehouse": opts.warehouse or None,
			"tax_category": opts.tax_category if include_tax else None,
			"ignore_pricing_rule": 0,
			"is_pos": 0,
			"update_stock": 0,
		})
		out = frappe._dict(get_item_details(args) or {})
		plr = flt(out.price_list_rate)
		has_price = plr > 0

		base = plr
		if out.margin_type == "Percentage" and flt(out.margin_rate_or_amount):
			base += plr * flt(out.margin_rate_or_amount) / 100
		elif out.margin_type == "Amount" and flt(out.margin_rate_or_amount):
			base += flt(out.margin_rate_or_amount)

		disc_pct, disc_amt, source = flt(out.discount_percentage), flt(out.discount_amount), None
		if (disc_pct or disc_amt) and not opts.warehouse and _rules_have_warehouse(out.pricing_rules):
			disc_pct = disc_amt = 0  # store-only rule, and no store picked
		if disc_pct or disc_amt:
			source = "rule"
		if flt(bc.get("discount")):
			disc_pct, disc_amt, source = flt(bc.get("discount")), 0, "barcode"

		rate = base * (1 - disc_pct / 100) if disc_pct else base - disc_amt
		rate = flt(max(rate, 0), precision)
		shown_pct = flt(100 * (base - rate) / base, 2) if base and rate < base else 0
		tax_rate = flt(_tax_rate(out, opts, company), 4) if include_tax else 0
		final = flt(rate * (1 + tax_rate / 100), precision) if has_price else None

		out_rows.append({
			"item_code": row.item_code,
			"item_name": item.item_name,
			"barcode": row.barcode or None,
			"uom": uom,
			"price_list_rate": flt(base * (1 + tax_rate / 100), precision) if has_price else None,
			"discount_percentage": shown_pct if has_price else 0,
			"rate": rate if has_price else None,
			"tax_rate": tax_rate,
			"final_price": final,
			"currency": currency,
			"has_price": has_price,
			"discount_source": source if has_price and shown_pct else None,
		})
	return out_rows
