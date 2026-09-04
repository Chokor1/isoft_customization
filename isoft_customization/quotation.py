"""Quotation -> Quotation mapper: the "Get Items From > Quotation" option.

ERPNext ships a single source under Get Items From on the Quotation form, the
Opportunity. Sales quote the same basket of items over and over, so this adds a
second source: pick one or more existing quotations -- or just some of their item
rows -- and append those items to the quotation being edited.

Unlike a forward mapper the target is a document the user already has open, so the
header is deliberately NOT copied wholesale: every Quotation fieldname goes into
field_no_map, and afterwards only a curated list of header fields is filled in, and
only where the target left them blank. The flow therefore behaves like "duplicate
this quotation" on an empty form and like "just append these items" on one that
already has a customer.

A whitelisted mapper plus a client button is the textbook custom-app pattern, the
same one sales_order.py uses, so ERPNext core stays untouched.
"""
import json

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import cint, flt

# Party and its dependent address / contact fields. Copied as one block, never
# piecemeal: quotation_to and party_name have to agree, and a form always carries a
# default quotation_to, so testing them one by one would leave a Lead in party_name
# under quotation_to = "Customer".
PARTY_FIELDS = (
	"quotation_to",
	"party_name",
	"customer_name",
	"customer_address",
	"address_display",
	"contact_person",
	"contact_display",
	"contact_mobile",
	"contact_email",
	"shipping_address_name",
	"shipping_address",
	"customer_group",
	"territory",
)

# Header fields worth inheriting when the target has nothing in them yet. Anything
# that identifies the target document itself -- transaction_date, valid_till,
# status, naming_series, company -- is left alone on purpose.
HEADER_FIELDS = (
	"order_type",
	"currency",
	"conversion_rate",
	"selling_price_list",
	"price_list_currency",
	"plc_conversion_rate",
	"tax_category",
	"taxes_and_charges",
	"shipping_rule",
	"payment_terms_template",
	"tc_name",
	"terms",
	"letter_head",
	"campaign",
	"source",
	"company_address",
	"company_address_display",
)

# Rates only mean something in the currency they were quoted in. When the source
# quotation is in another one they are converted through the company currency, which
# both conversion rates are expressed against. Refetching from the target's price
# list instead lands on zero for every item that list does not cover, and
# percentages need no conversion, so only the amount fields are touched.
CURRENCY_ITEM_FIELDS = ("price_list_rate", "rate", "discount_amount", "rate_with_margin")


def get_exchange_rate(source, target):
	"""Rate multiplier from the source quotation's currency to the target's.

	None when there is nothing to convert -- same currency -- or when a conversion
	rate is missing, in which case the rates are left exactly as they were quoted
	rather than silently scaled by a guess.
	"""
	if not source.currency or not target.currency or source.currency == target.currency:
		return None

	if not flt(source.conversion_rate) or not flt(target.conversion_rate):
		return None

	return flt(source.conversion_rate) / flt(target.conversion_rate)


@frappe.whitelist()
def make_quotation(source_name, target_doc=None, args=None):
	"""Append the items of Quotation `source_name` to `target_doc`.

	`args` carries {"filtered_children": [...]} when the user ticked individual item
	rows in the selection dialog; map_docs passes it through as the third argument.
	"""
	if args is None:
		args = {}
	elif isinstance(args, str):
		args = json.loads(args)

	if cint(frappe.db.get_value("Quotation", source_name, "docstatus")) == 2:
		frappe.throw(_("Cannot get items from cancelled Quotation {0}").format(source_name))

	def select_item(source_item):
		filtered_items = args.get("filtered_children") or []
		if filtered_items and source_item.name not in filtered_items:
			return False

		return bool(source_item.qty)

	def update_item(source, target, source_parent):
		# no_copy on both fields, so the mapper leaves them alone; they are what
		# tells the user later which quotation a row came from.
		target.prevdoc_doctype = source_parent.doctype
		target.prevdoc_docname = source_parent.name

	def postprocess(source, target):
		if source.name == target.get("name"):
			frappe.throw(_("Cannot get items from the same Quotation"))

		target.flags.ignore_permissions = True

		if not target.get("party_name"):
			for fieldname in PARTY_FIELDS:
				target.set(fieldname, source.get(fieldname))

		for fieldname in HEADER_FIELDS:
			if not target.get(fieldname):
				target.set(fieldname, source.get(fieldname))

		# Currency was taken over from the source above wherever the target had none,
		# so this only fires on a genuine mismatch. calculate_taxes_and_totals below
		# redoes every amount and base_ field off the converted rates.
		exchange_rate = get_exchange_rate(source, target)
		if exchange_rate is not None:
			for row in target.get("items"):
				if row.prevdoc_doctype == source.doctype and row.prevdoc_docname == source.name:
					for fieldname in CURRENCY_ITEM_FIELDS:
						row.set(fieldname, flt(row.get(fieldname)) * exchange_rate)

					if row.margin_type == "Amount":
						row.margin_rate_or_amount = flt(row.margin_rate_or_amount) * exchange_rate

		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	# Nothing from the header is mapped automatically: the target is a document the
	# user is editing, and map_fields would overwrite its every field with the
	# source's. postprocess fills the few that are wanted.
	quotation_fields = [df.fieldname for df in frappe.get_meta("Quotation").get("fields")]

	doclist = get_mapped_doc(
		"Quotation",
		source_name,
		{
			"Quotation": {
				"doctype": "Quotation",
				"field_no_map": quotation_fields,
			},
			"Quotation Item": {
				"doctype": "Quotation Item",
				"field_no_map": ["against_blanket_order", "blanket_order", "blanket_order_rate"],
				"postprocess": update_item,
				"condition": select_item,
			},
			"Sales Taxes and Charges": {"doctype": "Sales Taxes and Charges", "add_if_empty": True},
			# Regenerated on save, or meaningless on the target. A filter that always
			# matches is how get_mapped_doc is told to skip a table it would
			# otherwise copy row for row, same fieldname to same fieldname.
			"Packed Item": {"doctype": "Packed Item", "filter": lambda d: True},
			"Pricing Rule Detail": {"doctype": "Pricing Rule Detail", "filter": lambda d: True},
			"Quotation Lost Reason Detail": {
				"doctype": "Quotation Lost Reason Detail",
				"filter": lambda d: True,
			},
			"Quotation Additional Item Detail": {
				"doctype": "Quotation Additional Item Detail",
				"filter": lambda d: True,
			},
		},
		target_doc,
		postprocess,
	)

	# Stops the client from refetching price list rates over the ones just mapped.
	doclist.set_onload("ignore_price_list", True)

	return doclist
