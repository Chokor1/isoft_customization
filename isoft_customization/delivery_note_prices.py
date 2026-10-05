"""Keep Delivery Note prices on the Sales Invoice made from it.

One switch on Selling Settings, off by default: Keep Delivery Note Prices on Sales
Invoice.

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
* server -- before_validate puts the Delivery Note prices back and wraps the
  document's calculate_taxes_and_totals so they are put back again right before the
  totals are computed, i.e. after set_missing_item_details has had its go. Restoring
  from a plain `validate` hook would be too late: totals, the payment schedule and
  the Angola withholdings are all computed inside the controller's validate.

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

# Order matters only for readability; `rate` is what the totals are built from.
PRICE_FIELDS = (
	"price_list_rate",
	"discount_percentage",
	"discount_amount",
	"margin_type",
	"margin_rate_or_amount",
	"rate_with_margin",
	"rate",
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
		],
	}


def setup_custom_fields():
	"""Idempotent; runs from after_migrate."""
	missing = not frappe.db.exists("Custom Field", {"dt": SETTINGS, "fieldname": FLAG})
	create_custom_fields(get_custom_fields(), update=True)

	# Browsers cache form meta in localStorage keyed on DocType.modified, which adding a
	# Custom Field does not touch; without this the new field never shows up.
	if missing:
		frappe.db.set_value("DocType", SETTINGS, "modified", now(), update_modified=False)
		frappe.clear_cache(doctype=SETTINGS)


def is_enabled():
	return cint(frappe.get_cached_doc(SETTINGS, SETTINGS).get(FLAG))


def boot_session(bootinfo):
	bootinfo.isoft_keep_delivery_note_prices = is_enabled()


def clear_boot_cache(doc=None, method=None):
	"""Selling Settings on_update: the switch travels to the desk in bootinfo."""
	frappe.cache().delete_key("bootinfo")


def keep_prices(doc, method=None):
	"""Sales Invoice before_validate."""
	if doc.docstatus != 0 or not is_enabled():
		return

	prices = _delivery_note_prices(doc)
	if not prices:
		return

	edited = [
		d.idx
		for d in doc.get("items")
		if d.get("dn_detail") in prices
		and abs(flt(d.rate) - flt(prices[d.dn_detail]["rate"])) >= 1.0 / (10 ** d.precision("rate"))
	]

	def restore():
		for d in doc.get("items"):
			source = prices.get(d.get("dn_detail"))
			if source:
				for fieldname in PRICE_FIELDS:
					d.set(fieldname, source[fieldname])

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
