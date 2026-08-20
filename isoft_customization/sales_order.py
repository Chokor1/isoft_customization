"""Sales Order -> Quotation mapper, moved here from ERPNext core.

ERPNext maps a Sales Order forward (to Delivery Note, Sales Invoice, and so on) but
has no mapper back to a Quotation. This one mirrors the standard invoice mapper's
item and payment-terms handling, and is surfaced as Create > Quotation on the Sales
Order form by public/js/sales_order.js.

A whitelisted mapper plus a client button is the textbook custom-app pattern -- it
needed no core change at all, and erpnext/selling/doctype/sales_order/sales_order.py
and .js are byte-identical to upstream again.

The helper imports below are the ones the function actually uses; they come from
ERPNext, which is a dependency of this app rather than the other way round.
"""
import frappe
from frappe.contacts.doctype.address.address import get_company_address
from frappe.model.mapper import get_mapped_doc
from frappe.model.utils import get_fetch_values
from frappe.utils import cint, flt

from erpnext.accounts.party import get_party_account
from erpnext.setup.doctype.item_group.item_group import get_item_group_defaults
from erpnext.stock.doctype.item.item import get_item_defaults


@frappe.whitelist()
def make_quotation(source_name, target_doc=None, ignore_permissions=False):
	def postprocess(source, target):
		set_missing_values(source, target)

	def set_missing_values(source, target):
		target.flags.ignore_permissions = True
		target.run_method("set_missing_values")
		target.run_method("set_po_nos")
		target.run_method("calculate_taxes_and_totals")

		if source.company_address:
			target.update({"company_address": source.company_address})
		else:
			# set company address
			target.update(get_company_address(target.company))

		if target.company_address:
			target.update(get_fetch_values("Quotation", "company_address", target.company_address))

		# set the redeem loyalty points if provided via shopping cart
		if source.loyalty_points and source.order_type == "Shopping Cart":
			target.redeem_loyalty_points = 1

		target.debit_to = get_party_account("Customer", source.customer, source.company)

	def update_item(source, target, source_parent):
		target.amount = flt(source.amount) - flt(source.billed_amt)
		target.base_amount = target.amount * flt(source_parent.conversion_rate)
		target.qty = (
			target.amount / flt(source.rate)
			if (source.rate and source.billed_amt)
			else source.qty - source.returned_qty
		)

		if source_parent.project:
			target.cost_center = frappe.db.get_value("Project", source_parent.project, "cost_center")
		if target.item_code:
			item = get_item_defaults(target.item_code, source_parent.company)
			item_group = get_item_group_defaults(target.item_code, source_parent.company)
			cost_center = item.get("selling_cost_center") or item_group.get("selling_cost_center")

			if cost_center:
				target.cost_center = cost_center

	doclist = get_mapped_doc(
		"Sales Order",
		source_name,
		{
			"Sales Order": {
				"doctype": "Quotation",
				"field_map": {
					"party_account_currency": "party_account_currency",
					"payment_terms_template": "payment_terms_template",
				},
				"field_no_map": ["payment_terms_template"],
				"validation": {"docstatus": ["=", 1]},
			},
			"Sales Order Item": {
				"doctype": "Quotation Item",
				"field_map": {
					"name": "so_detail",
					"parent": "sales_order",
				},
				"postprocess": update_item,
				"condition": lambda doc: doc.qty
				and (doc.base_amount == 0 or abs(doc.billed_amt) < abs(doc.amount)),
			},
			"Sales Taxes and Charges": {"doctype": "Sales Taxes and Charges", "add_if_empty": True},
			"Sales Team": {"doctype": "Sales Team", "add_if_empty": True},
		},
		target_doc,
		postprocess,
		ignore_permissions=ignore_permissions,
	)

	automatically_fetch_payment_terms = cint(
		frappe.db.get_single_value("Accounts Settings", "automatically_fetch_payment_terms")
	)
	if automatically_fetch_payment_terms:
		doclist.set_payment_schedule()

	doclist.set_onload("ignore_price_list", True)

	return doclist
