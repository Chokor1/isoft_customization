"""Pricing Rule "Multi-buy (Buy X get Y at d%)": fields, validation, lookup flag.

A multi-buy rule is a selling Pricing Rule whose discount is worked out over the whole
basket by isoft_customization.multi_buy (the document engine), never by ERPNext's
per-row pricing. Two guards keep ERPNext from applying it to every unit of a row:

* the rule lookup (item_group_and_brand._get_pricing_rules) drops multi-buy rules unless
  the engine asks for them through `multibuy_lookup()`;
* the standard discount / rate / margin fields of a multi-buy rule are forced to 0 on
  save, so any ERPNext path that still matched one would apply nothing.

The multi-buy percentage lives in `isoft_multibuy_discount`. Spec:
docs/superpowers/specs/2026-11-09-multi-buy-pricing-rule-design.md
"""
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt

FIELDS = (
	"isoft_multibuy",
	"isoft_buy_qty",
	"isoft_get_qty",
	"isoft_multibuy_discount",
	"isoft_multibuy_max_units",
	"isoft_allow_partial_return",
)
ROW_DOCTYPES = ("Quotation Item", "Sales Order Item", "Delivery Note Item", "Sales Invoice Item")
AGT_NOTE = "(100%: verify with AGT)"


def get_custom_fields():
	show = "eval:doc.selling && doc.apply_on != 'Transaction'"
	on = "eval:doc.isoft_multibuy"
	rule_fields = [
		{"fieldname": "isoft_multibuy_section", "fieldtype": "Section Break", "label": "Multi-buy (Buy X get Y)",
			"insert_after": "rule_description", "depends_on": show, "collapsible": 0},
		{"fieldname": "isoft_multibuy", "fieldtype": "Check", "label": "Multi-buy (Buy X get Y)",
			"insert_after": "isoft_multibuy_section", "depends_on": show,
			"description": "Pools the eligible units of the whole document: for every Buy + Get units, the Get cheapest units get the discount."},
		{"fieldname": "isoft_buy_qty", "fieldtype": "Int", "label": "Buy", "insert_after": "isoft_multibuy",
			"depends_on": on, "mandatory_depends_on": on},
		{"fieldname": "isoft_get_qty", "fieldtype": "Int", "label": "Get", "insert_after": "isoft_buy_qty",
			"depends_on": on, "mandatory_depends_on": on},
		{"fieldname": "isoft_multibuy_cb", "fieldtype": "Column Break", "insert_after": "isoft_get_qty"},
		{"fieldname": "isoft_multibuy_discount", "fieldtype": "Percent", "label": "Discount on the Get units (%)",
			"insert_after": "isoft_multibuy_cb", "depends_on": on, "mandatory_depends_on": on},
		{"fieldname": "isoft_multibuy_max_units", "fieldtype": "Int", "label": "Max discounted units per document",
			"insert_after": "isoft_multibuy_discount", "depends_on": on, "description": "0 = no limit"},
		{"fieldname": "isoft_allow_partial_return", "fieldtype": "Check", "label": "Allow partial return",
			"insert_after": "isoft_multibuy_max_units", "depends_on": on,
			"description": "Off: a return may not leave the customer with a discount the remaining items no longer earn."},
	]
	row_fields = [
		{"fieldname": "isoft_multibuy_rule", "fieldtype": "Link", "options": "Pricing Rule", "label": "Multi-buy Rule",
			"insert_after": "pricing_rules", "read_only": 1, "print_hide": 1, "report_hide": 1},
		{"fieldname": "isoft_multibuy_units", "fieldtype": "Float", "label": "Multi-buy Discounted Units",
			"insert_after": "isoft_multibuy_rule", "read_only": 1, "print_hide": 1, "report_hide": 1},
		{"fieldname": "isoft_multibuy_pct", "fieldtype": "Percent", "label": "Multi-buy Discount (%)",
			"insert_after": "isoft_multibuy_units", "read_only": 1, "print_hide": 1, "report_hide": 1},
	]
	out = {"Pricing Rule": rule_fields}
	for dt in ROW_DOCTYPES:
		out[dt] = [dict(f) for f in row_fields]
	return out


def setup_custom_fields(*args, **kwargs):
	create_custom_fields(get_custom_fields(), update=True)


def is_multibuy(rule):
	return bool(cint((rule or {}).get("isoft_multibuy")))


@contextmanager
def multibuy_lookup():
	"""Inside: the rule lookup returns only multi-buy rules. Outside: never."""
	previous = frappe.flags.isoft_multibuy_lookup
	frappe.flags.isoft_multibuy_lookup = True
	try:
		yield
	finally:
		frappe.flags.isoft_multibuy_lookup = previous


def filter_lookup(rules):
	"""Applied to every rule list ERPNext's lookup returns (see item_group_and_brand)."""
	want = bool(frappe.flags.isoft_multibuy_lookup)
	return [r for r in rules if is_multibuy(r) == want]


def validate_rule(doc):
	frappe.flags.isoft_multibuy_any = None  # multi_buy._any_multibuy re-reads the rules
	if not cint(doc.get("isoft_multibuy")):
		return
	if doc.apply_on == "Transaction":
		frappe.throw(_("A Multi-buy rule applies to items, item groups or brands, not to the whole transaction."))
	if (doc.get("condition") or "").strip():
		frappe.throw(_("A Multi-buy rule cannot have a Condition: the offer is worked out over the whole document."))
	if cint(doc.get("coupon_code_based")):
		frappe.throw(_("A Multi-buy rule cannot be coupon based."))
	if doc.get("applicable_for") in ("Campaign", "Sales Partner") or doc.get("campaign") or doc.get("sales_partner"):
		frappe.throw(_("A Multi-buy rule applies to customers, customer groups or territories, not to a Campaign or Sales Partner."))
	if cint(doc.isoft_buy_qty) < 1 or cint(doc.isoft_get_qty) < 1:
		frappe.throw(_("Multi-buy: Buy and Get must both be at least 1."))
	pct = flt(doc.isoft_multibuy_discount)
	if pct <= 0 or pct > 100:
		frappe.throw(_("Multi-buy: the discount must be above 0% and at most 100%."))
	if cint(doc.isoft_multibuy_max_units) < 0:
		frappe.throw(_("Multi-buy: the maximum discounted units cannot be negative."))
	# the engine owns the discount: ERPNext's own fields must give nothing
	doc.selling, doc.buying = 1, 0
	doc.price_or_product_discount = "Price"
	doc.rate_or_discount = "Discount Percentage"
	doc.discount_percentage = 0
	doc.discount_amount = 0
	doc.rate = 0
	doc.margin_type = ""
	doc.margin_rate_or_amount = 0
	doc.mixed_conditions = 0
	doc.is_cumulative = 0
	doc.apply_multiple_pricing_rules = 0
	doc.same_item = 0
	doc.free_item = None
	doc.free_qty = 0
	desc = doc.rule_description or ""
	if pct >= 100 and AGT_NOTE not in desc:
		doc.rule_description = (desc + " " + AGT_NOTE).strip()
