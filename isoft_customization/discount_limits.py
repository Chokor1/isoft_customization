"""Per-user maximum line discounts on selling documents.

Standard replacement for the site-level "User Sales Discount" custom DocType and
its Server Script on Sales Invoice. Configuration:

* Sales Discount Limit (one per user): rows per document type (or "All") with a
  max discount % for stock items and for services.
* Sales Discount Limit Settings (Single): on/off, which document types are
  checked, POS / return exemptions, pricing-rule exemption, whose limit applies
  (the user saving, or the document owner as the old script did), role-based
  limits for users without a record, and the fallback for users with nothing
  at all ("No limit (100%)" or "No discount allowed (0%)").

Resolution, per document: user row for the doctype > user "All" row > highest
role row for the doctype > highest role "All" row > fallback setting.

Each line's discount % (discount_percentage, or discount_amount over the price
list rate when only an amount was typed) must not exceed the limit for the
item's kind (Item.is_stock_item). A discount granted by an applied Pricing Rule
is allowed when that setting is on. Over-limit saves are blocked with the line,
the discount and the limit named.

Hooked on validate of Quotation, Sales Order, Delivery Note and Sales Invoice.
Hook signature takes *args/**kwargs (see party_tax_id.py for why).
"""
from __future__ import unicode_literals

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

SETTINGS = "Sales Discount Limit Settings"
CHECK_FLAG = {
	"Quotation": "check_quotation",
	"Sales Order": "check_sales_order",
	"Delivery Note": "check_delivery_note",
	"Sales Invoice": "check_sales_invoice",
}
NO_LIMIT = "No limit (100%)"
NO_DISCOUNT = "No discount allowed (0%)"
TOL = 0.005


def get_settings():
	return frappe.get_cached_doc(SETTINGS, SETTINGS)


def resolve_limit(doctype, settings, user_rows, role_rows, user_roles):
	"""(max_stock, max_service) for one document type. Pure: all inputs passed in."""
	def pick(rows, dt):
		return [r for r in rows if r.document_type == dt]

	for dt in (doctype, "All"):
		rows = pick(user_rows, dt)
		if rows:
			r = rows[0]
			return (flt(r.max_discount_stock), flt(r.max_discount_service))

	for dt in (doctype, "All"):
		rows = [r for r in pick(role_rows, dt) if r.role in user_roles]
		if rows:
			return (max(flt(r.max_discount_stock) for r in rows), max(flt(r.max_discount_service) for r in rows))

	fallback = 0.0 if settings.get("users_without_limit") == NO_DISCOUNT else 100.0
	return (fallback, fallback)


def user_limit_rows(user):
	if not frappe.db.exists("Sales Discount Limit", {"user": user, "enabled": 1}):
		return []
	return frappe.get_all("Sales Discount Limit Line", filters={"parent": user, "parenttype": "Sales Discount Limit"},
		fields=["document_type", "max_discount_stock", "max_discount_service"])


def pricing_rule_discount(item):
	"""Highest discount % granted by the Pricing Rules applied on the line."""
	raw = item.get("pricing_rules")
	if not raw:
		return 0.0
	try:
		names = json.loads(raw) if isinstance(raw, str) else list(raw)
	except ValueError:
		names = [raw]
	best = 0.0
	for name in names:
		pct = frappe.db.get_value("Pricing Rule", name, "discount_percentage")
		best = max(best, flt(pct))
	return best


def line_discount(item):
	pct = flt(item.get("discount_percentage"))
	if not pct and flt(item.get("discount_amount")) and flt(item.get("price_list_rate")):
		pct = flt(item.discount_amount) / flt(item.price_list_rate) * 100.0
	return pct


def validate_discounts(doc, method=None, *args, **kwargs):
	settings = get_settings()
	if not cint(settings.enabled) or not cint(settings.get(CHECK_FLAG.get(doc.doctype, ""))):
		return
	if cint(settings.skip_pos) and cint(doc.get("is_pos")):
		return
	if cint(settings.skip_returns) and cint(doc.get("is_return")):
		return

	user = doc.owner if settings.limit_user == "Document owner" and doc.owner else frappe.session.user
	user_rows = user_limit_rows(user)
	role_rows = settings.get("role_limits") or []
	roles = set(frappe.get_roles(user)) if role_rows else set()
	max_stock, max_service = resolve_limit(doc.doctype, settings, user_rows, role_rows, roles)
	if max_stock >= 100 and max_service >= 100:
		return

	allow_rules = cint(settings.allow_pricing_rule_discounts)
	for item in doc.get("items") or []:
		pct = line_discount(item)
		if pct <= TOL:
			continue
		is_stock = cint(frappe.get_cached_value("Item", item.item_code, "is_stock_item")) if item.get("item_code") else 0
		limit = max_stock if is_stock else max_service
		if pct <= limit + TOL:
			continue
		if allow_rules and item.get("pricing_rules") and pct <= pricing_rule_discount(item) + TOL:
			continue
		frappe.throw(
			_("Row {0} ({1}): a discount of {2} is above the {3} allowed to {6} for {4} on a {5}.").format(
				item.idx, item.item_code, frappe.format(pct, {"fieldtype": "Percent"}), frappe.format(limit, {"fieldtype": "Percent"}),
				_("stock items") if is_stock else _("services"), _(doc.doctype), user),
			title=_("Discount above your limit"),
		)


@frappe.whitelist()
def get_form_limits(doctype, owner=None, item_codes=None):
	"""What the form needs to lock discount fields: the effective limits of the user
	whose limit applies (session user, or the document owner per settings) and
	which of the given items are stock items. `applies` is False when the
	settings do not check this document type at all (the form then locks nothing;
	POS / return exemptions are decided on the form from the document flags)."""
	settings = get_settings()
	out = {"applies": False, "max_stock": 100.0, "max_service": 100.0, "stock_items": {},
		"skip_pos": cint(settings.skip_pos), "skip_returns": cint(settings.skip_returns)}
	if not cint(settings.enabled) or not cint(settings.get(CHECK_FLAG.get(doctype, ""))):
		return out
	user = owner if settings.limit_user == "Document owner" and owner else frappe.session.user
	user_rows = user_limit_rows(user)
	role_rows = settings.get("role_limits") or []
	roles = set(frappe.get_roles(user)) if role_rows else set()
	max_stock, max_service = resolve_limit(doctype, settings, user_rows, role_rows, roles)
	codes = frappe.parse_json(item_codes) if isinstance(item_codes, str) else (item_codes or [])
	codes = [c for c in set(codes) if c]
	stock = {}
	if codes:
		for r in frappe.get_all("Item", filters={"name": ["in", codes]}, fields=["name", "is_stock_item"]):
			stock[r.name] = cint(r.is_stock_item)
	out.update({"applies": True, "max_stock": max_stock, "max_service": max_service, "stock_items": stock, "user": user})
	return out
