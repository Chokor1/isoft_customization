"""Keep the prices of the Delivery Note / Purchase Receipt on the invoice made from it.

Two switches per side, all off by default -- on Selling Settings for Delivery Note ->
Sales Invoice, on Buying Settings for Purchase Receipt -> Purchase Invoice:

* Keep <source> Prices on <invoice> -- rows made from the source document are priced
  from its rows, full stop: no price list, no pricing rules, no manual edits.
* Do Not Apply Pricing Rules on Rows from a <source> -- the lighter one: the rows keep
  whatever price they arrive with (the source's, or what the user typed), and pricing
  rules leave them alone. Redundant while the first is on.

ERPNext copies the source rates onto the invoice, then re-prices it from the current
price list / pricing rules whenever something "pricing relevant" changes. The only thing
stopping that is a transient `__onload.ignore_price_list` flag which is gone after the
first save, so a saved draft is re-priced by changing its price list or exchange rate,
and on every save a pricing rule that changed since the delivery re-applies itself in
set_missing_item_details. Worse, the mapper itself runs set_missing_values on the new
invoice, which is where today's pricing rules first land on the rows.

With a switch on, every draft invoice row that carries the source reference
(`dn_detail` / `pr_detail`) is handled in three places:

* mapping -- the `set_missing_values` doc event fires right after the mapper's call
  (run_method fires hooks for any method name), and the source prices go back on.
* desk -- public/js/linked_document_prices.js keeps `ignore_price_list` alive on such
  drafts and stops the triggers core does not guard (price list, UOM, pricing rule).
* save -- before_validate puts the source prices back (first switch) or notes the
  prices the rows arrived with (second), and wraps the document's
  calculate_taxes_and_totals so they are put back again right before the totals are
  computed, i.e. after set_missing_item_details has had its go. Restoring from a
  plain `validate` hook would be too late: totals, the payment schedule and the
  Angola withholdings are all computed inside the controller's validate.

A row is left alone when the invoice is in another currency than the source document
(the rate cannot be carried over) or its item no longer matches.
"""
from __future__ import unicode_literals

# Hook signatures take *args/**kwargs: Frappe forwards the hooked method's own
# arguments to every hook, and the desk's run_doc_method always passes one
# positional `args` (ERPNext's sales_invoice.js calls set_missing_values that way
# when a POS return loads), so a plain (doc, method) hook raises TypeError.
import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint, flt, now

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

LINKS = {
	"Sales Invoice": frappe._dict(
		settings="Selling Settings",
		section="isoft_delivery_note_prices_section",
		section_label="Delivery Note Prices",
		section_after="isoft_require_credit_note_reason",
		keep="isoft_keep_delivery_note_prices",
		keep_label="Keep Delivery Note Prices on Sales Invoice",
		keep_description="Sales Invoice rows made from a Delivery Note keep the Delivery Note's price and discount. They are not re-priced from the current price list or pricing rules, and cannot be changed on the invoice.",
		no_rules="isoft_no_pricing_rules_from_delivery_note",
		no_rules_label="Do Not Apply Pricing Rules on Rows from a Delivery Note",
		no_rules_description="Sales Invoice rows made from a Delivery Note keep the price they arrive with; pricing rules are not applied to them. The price can still be changed on the invoice. Not needed when the option above is on.",
		source="Delivery Note",
		source_item="Delivery Note Item",
		ref="dn_detail",
		message="Delivery Note prices kept on row(s) {0}.",
	),
	"Purchase Invoice": frappe._dict(
		settings="Buying Settings",
		section="isoft_purchase_receipt_prices_section",
		section_label="Purchase Receipt Prices",
		section_after="over_transfer_allowance",
		keep="isoft_keep_purchase_receipt_prices",
		keep_label="Keep Purchase Receipt Prices on Purchase Invoice",
		keep_description="Purchase Invoice rows made from a Purchase Receipt keep the Purchase Receipt's price and discount. They are not re-priced from the current price list or pricing rules, and cannot be changed on the invoice.",
		no_rules="isoft_no_pricing_rules_from_purchase_receipt",
		no_rules_label="Do Not Apply Pricing Rules on Rows from a Purchase Receipt",
		no_rules_description="Purchase Invoice rows made from a Purchase Receipt keep the price they arrive with; pricing rules are not applied to them. The price can still be changed on the invoice. Not needed when the option above is on.",
		source="Purchase Receipt",
		source_item="Purchase Receipt Item",
		ref="pr_detail",
		message="Purchase Receipt prices kept on row(s) {0}.",
	),
}


def get_custom_fields():
	fields = {}
	for link in LINKS.values():
		fields[link.settings] = [
			{
				"fieldname": link.section,
				"fieldtype": "Section Break",
				"label": link.section_label,
				"insert_after": link.section_after,
			},
			{
				"fieldname": link.keep,
				"fieldtype": "Check",
				"label": link.keep_label,
				"description": link.keep_description,
				"insert_after": link.section,
			},
			{
				"fieldname": link.no_rules,
				"fieldtype": "Check",
				"label": link.no_rules_label,
				"description": link.no_rules_description,
				"insert_after": link.keep,
			},
		]
	return fields


def setup_custom_fields():
	"""Idempotent; runs from after_migrate."""
	fields = get_custom_fields()
	missing = {
		doctype
		for doctype, rows in fields.items()
		for row in rows
		if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": row["fieldname"]})
	}
	create_custom_fields(fields, update=True)

	# Browsers cache form meta in localStorage keyed on DocType.modified, which adding a
	# Custom Field does not touch; without this the new fields never show up.
	for doctype in missing:
		frappe.db.set_value("DocType", doctype, "modified", now(), update_modified=False)
		frappe.clear_cache(doctype=doctype)


def is_enabled(link, flag):
	return cint(frappe.get_cached_doc(link.settings, link.settings).get(flag))


def boot_session(bootinfo):
	for link in LINKS.values():
		bootinfo[link.keep] = is_enabled(link, link.keep)
		bootinfo[link.no_rules] = is_enabled(link, link.no_rules)


def clear_boot_cache(doc=None, method=None):
	"""Selling / Buying Settings on_update: the switches travel to the desk in bootinfo."""
	frappe.cache().delete_key("bootinfo")


def on_map(doc, method=None, *args, **kwargs):
	"""Invoice set_missing_values: during the mapper this is the moment the rows get
	today's pricing rules; during validate keep_prices has already taken over."""
	link = LINKS.get(doc.doctype)
	if not link or doc.flags.isoft_linked_prices_validating or doc.docstatus != 0 or not doc.get("__islocal"):
		return
	if not (is_enabled(link, link.keep) or is_enabled(link, link.no_rules)):
		return
	prices = _source_prices(doc, link)
	if prices:
		_restore(doc, link, prices)


def keep_prices(doc, method=None, *args, **kwargs):
	"""Invoice before_validate."""
	link = LINKS.get(doc.doctype)
	if not link or doc.docstatus != 0:
		return
	doc.flags.isoft_linked_prices_validating = True

	edited = []
	if is_enabled(link, link.keep):
		prices = _source_prices(doc, link)
		edited = [
			d.idx
			for d in doc.get("items")
			if d.get(link.ref) in prices
			and abs(flt(d.rate) - flt(prices[d.get(link.ref)]["rate"])) >= 1.0 / (10 ** d.precision("rate"))
		]
	elif is_enabled(link, link.no_rules):
		# As the rows arrived: the source document's prices, or whatever the user typed.
		prices = {
			d.get(link.ref): {fieldname: d.get(fieldname) for fieldname in PRICE_FIELDS}
			for d in doc.get("items")
			if d.get(link.ref)
		}
	else:
		return

	if not prices:
		return

	_restore(doc, link, prices)

	# set_missing_item_details re-applies pricing rules between here and the totals.
	core = doc.calculate_taxes_and_totals

	def calculate_taxes_and_totals(*args, **kwargs):
		_restore(doc, link, prices)
		return core(*args, **kwargs)

	doc.calculate_taxes_and_totals = calculate_taxes_and_totals

	if edited:
		frappe.msgprint(
			_(link.message).format(", ".join(str(idx) for idx in edited)),
			indicator="orange",
			alert=True,
		)


def release(doc, method=None, *args, **kwargs):
	"""Invoice validate: runs after the controller's own, drops the wrapper."""
	doc.__dict__.pop("calculate_taxes_and_totals", None)


def _restore(doc, link, prices):
	for d in doc.get("items"):
		source = prices.get(d.get(link.ref))
		if source:
			for fieldname in PRICE_FIELDS:
				d.set(fieldname, source[fieldname])
	_drop_stale_rule_details(doc, link, prices)


def _drop_stale_rule_details(doc, link, prices):
	"""set_pricing_rule_details logs every rule set_missing_item_details applied, including
	the ones just undone on the restored rows."""
	restored = {d.name: d for d in doc.get("items") if d.get(link.ref) in prices}
	kept = []
	for detail in doc.get("pricing_rules") or []:
		row = restored.get(detail.child_docname)
		if row is None or detail.pricing_rule in (row.get("pricing_rules") or ""):
			kept.append(detail)
	if len(kept) != len(doc.get("pricing_rules") or []):
		doc.set("pricing_rules", kept)
		for idx, detail in enumerate(kept, 1):
			detail.idx = idx


def _source_prices(doc, link):
	names = [d.get(link.ref) for d in doc.get("items") if d.get(link.ref)]
	if not names:
		return {}

	rows = frappe.get_all(
		link.source_item,
		filters={"name": ("in", names), "docstatus": 1},
		fields=["name", "parent", "item_code"] + list(PRICE_FIELDS),
	)
	currencies = dict(
		frappe.get_all(
			link.source,
			filters={"name": ("in", list({r.parent for r in rows}))},
			fields=["name", "currency"],
			as_list=True,
		)
	)
	item_codes = {d.get(link.ref): d.item_code for d in doc.get("items") if d.get(link.ref)}

	return {
		r.name: r
		for r in rows
		if currencies.get(r.parent) == doc.currency and item_codes.get(r.name) == r.item_code
	}
