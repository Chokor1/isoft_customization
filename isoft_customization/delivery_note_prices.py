"""Keep Delivery Note prices on the Sales Invoice made from it.

Two switches on Selling Settings, both off by default:

* Keep Delivery Note Prices on Sales Invoice -- rows made from a Delivery Note are
  priced from the Delivery Note Item, full stop: no price list, no pricing rules, no
  manual edits.
* Do Not Apply Pricing Rules on Rows from a Delivery Note -- the lighter one: the
  rows keep whatever price they arrive with (the Delivery Note's, or what the user
  typed), and pricing rules leave them alone. Redundant while the first is on.

ERPNext copies the Delivery Note's rates onto the invoice, then re-prices it from the
current price list / pricing rules whenever something "pricing relevant" changes. The
only thing stopping that is a transient `__onload.ignore_price_list` flag which is
gone after the first save, so a saved draft is re-priced by editing its posting date,
customer, currency or quantities, and on every save a pricing rule that changed since
the delivery re-applies itself in set_missing_item_details.

With the switch on, every draft Sales Invoice row that carries `dn_detail` is priced
from its Delivery Note Item:

* desk -- public/js/sales_invoice.js keeps `ignore_price_list` alive on such drafts
  and stops the two triggers core does not guard (price list, UOM).
* server -- make_sales_invoice runs set_missing_values on the new invoice, which is
  where today's pricing rules first land on the Delivery Note rows, so the Delivery
  Note prices are put back right after it (on_map). Then before_validate puts the Delivery Note prices back (first switch) or
  notes the prices the rows arrived with (second), and wraps the document's
  calculate_taxes_and_totals so they are put back again right before the totals are
  computed, i.e. after set_missing_item_details has had its go. Restoring from a
  plain `validate` hook would be too late: totals, the payment schedule and the
  Angola withholdings are all computed inside the controller's validate.

A row is left alone when the invoice is in another currency than the Delivery Note
(the rate cannot be carried over) or its item no longer matches.
"""
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt, now

SETTINGS = "Selling Settings"
FLAG = "isoft_keep_delivery_note_prices"
NO_RULES_FLAG = "isoft_no_pricing_rules_from_delivery_note"

# Order matters only for readability; `rate` is what the totals are built from.
PRICE_FIELDS = (
	"price_list_rate",
	"discount_percentage",
	"discount_amount",
	"margin_type",
	"margin_rate_or_amount",
	"rate_with_margin",
	"rate",
	"pricing_rules",
)


def get_custom_fields():
	return {
		SETTINGS: [
			{
				"fieldname": "isoft_delivery_note_prices_section",
				"fieldtype": "Section Break",
				"label": "Delivery Note Prices",
				"insert_after": "isoft_require_credit_note_reason",
			},
			{
				"fieldname": FLAG,
				"fieldtype": "Check",
				"label": "Keep Delivery Note Prices on Sales Invoice",
				"description": "Sales Invoice rows made from a Delivery Note keep the Delivery Note's price and discount. They are not re-priced from the current price list or pricing rules, and cannot be changed on the invoice.",
				"insert_after": "isoft_delivery_note_prices_section",
			},
			{
				"fieldname": NO_RULES_FLAG,
				"fieldtype": "Check",
				"label": "Do Not Apply Pricing Rules on Rows from a Delivery Note",
				"description": "Sales Invoice rows made from a Delivery Note keep the price they arrive with; pricing rules are not applied to them. The price can still be changed on the invoice. Not needed when the option above is on.",
				"insert_after": FLAG,
			},
		],
	}


def setup_custom_fields():
	"""Idempotent; runs from after_migrate."""
	missing = not all(
		frappe.db.exists("Custom Field", {"dt": SETTINGS, "fieldname": flag}) for flag in (FLAG, NO_RULES_FLAG)
	)
	create_custom_fields(get_custom_fields(), update=True)

	# Browsers cache form meta in localStorage keyed on DocType.modified, which adding a
	# Custom Field does not touch; without this the new field never shows up.
	if missing:
		frappe.db.set_value("DocType", SETTINGS, "modified", now(), update_modified=False)
		frappe.clear_cache(doctype=SETTINGS)


def is_enabled(flag=FLAG):
	return cint(frappe.get_cached_doc(SETTINGS, SETTINGS).get(flag))


def boot_session(bootinfo):
	bootinfo.isoft_keep_delivery_note_prices = is_enabled()
	bootinfo.isoft_no_pricing_rules_from_delivery_note = is_enabled(NO_RULES_FLAG)


def clear_boot_cache(doc=None, method=None):
	"""Selling Settings on_update: the switch travels to the desk in bootinfo."""
	frappe.cache().delete_key("bootinfo")


def on_map(doc, method=None):
	"""Sales Invoice set_missing_values: during make_sales_invoice this is the moment the
	rows get today's pricing rules; during validate keep_prices has already taken over."""
	if doc.flags.isoft_dn_prices_validating or doc.docstatus != 0 or not doc.get("__islocal"):
		return
	if not (is_enabled() or is_enabled(NO_RULES_FLAG)):
		return
	prices = _delivery_note_prices(doc)
	if prices:
		_restore(doc, prices)


def keep_prices(doc, method=None):
	"""Sales Invoice before_validate."""
	if doc.docstatus != 0:
		return
	doc.flags.isoft_dn_prices_validating = True

	edited = []
	if is_enabled():
		prices = _delivery_note_prices(doc)
		edited = [
			d.idx
			for d in doc.get("items")
			if d.get("dn_detail") in prices
			and abs(flt(d.rate) - flt(prices[d.dn_detail]["rate"])) >= 1.0 / (10 ** d.precision("rate"))
		]
	elif is_enabled(NO_RULES_FLAG):
		# As the rows arrived: the Delivery Note's prices, or whatever the user typed.
		prices = {
			d.dn_detail: {fieldname: d.get(fieldname) for fieldname in PRICE_FIELDS}
			for d in doc.get("items")
			if d.get("dn_detail")
		}
	else:
		return

	if not prices:
		return

	def restore():
		_restore(doc, prices)

	restore()

	# set_missing_item_details re-applies pricing rules between here and the totals.
	core = doc.calculate_taxes_and_totals

	def calculate_taxes_and_totals(*args, **kwargs):
		restore()
		return core(*args, **kwargs)

	doc.calculate_taxes_and_totals = calculate_taxes_and_totals

	if edited:
		frappe.msgprint(
			_("Delivery Note prices kept on row(s) {0}.").format(", ".join(str(idx) for idx in edited)),
			indicator="orange",
			alert=True,
		)


def release(doc, method=None):
	"""Sales Invoice validate: runs after the controller's own, drops the wrapper."""
	doc.__dict__.pop("calculate_taxes_and_totals", None)


def _restore(doc, prices):
	for d in doc.get("items"):
		source = prices.get(d.get("dn_detail"))
		if source:
			for fieldname in PRICE_FIELDS:
				d.set(fieldname, source[fieldname])
	_drop_stale_rule_details(doc, prices)


def _drop_stale_rule_details(doc, prices):
	"""set_pricing_rule_details logs every rule set_missing_item_details applied, including
	the ones just undone on the restored rows."""
	restored = {d.name: d for d in doc.get("items") if d.get("dn_detail") in prices}
	kept = []
	for detail in doc.get("pricing_rules") or []:
		row = restored.get(detail.child_docname)
		if row is None or detail.pricing_rule in (row.get("pricing_rules") or ""):
			kept.append(detail)
	if len(kept) != len(doc.get("pricing_rules") or []):
		doc.set("pricing_rules", kept)
		for idx, detail in enumerate(kept, 1):
			detail.idx = idx


def _delivery_note_prices(doc):
	names = [d.dn_detail for d in doc.get("items") if d.get("dn_detail")]
	if not names:
		return {}

	rows = frappe.get_all(
		"Delivery Note Item",
		filters={"name": ("in", names), "docstatus": 1},
		fields=["name", "parent", "item_code"] + list(PRICE_FIELDS),
	)
	currencies = dict(
		frappe.get_all(
			"Delivery Note",
			filters={"name": ("in", list({r.parent for r in rows}))},
			fields=["name", "currency"],
			as_list=True,
		)
	)
	item_codes = {d.dn_detail: d.item_code for d in doc.get("items") if d.get("dn_detail")}

	return {
		r.name: r
		for r in rows
		if currencies.get(r.parent) == doc.currency and item_codes.get(r.name) == r.item_code
	}
