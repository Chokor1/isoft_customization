# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, nowdate


class ItemResumption(Document):
	def validate(self):
		self.validate_invoices()
		self.update_outstanding_amounts()

	def validate_invoices(self):
		"""Validate that original invoice has outstanding > 0 and return/credit note has outstanding < 0"""
		if self.positive_invoice:
			pos_outstanding = flt(frappe.db.get_value("Sales Invoice", self.positive_invoice, "outstanding_amount"))
			if pos_outstanding <= 0:
				frappe.throw(_("Original Invoice {0} must have outstanding amount greater than 0").format(self.positive_invoice))
		
		if self.negative_invoice:
			neg_outstanding = flt(frappe.db.get_value("Sales Invoice", self.negative_invoice, "outstanding_amount"))
			if neg_outstanding >= 0:
				frappe.throw(_("Return/Credit Note {0} must have outstanding amount less than 0").format(self.negative_invoice))
		
		if self.positive_invoice == self.negative_invoice:
			frappe.throw(_("Original Invoice and Return/Credit Note cannot be the same"))

	def update_outstanding_amounts(self):
		"""Update outstanding amount fields"""
		if self.positive_invoice:
			self.positive_invoice_outstanding = flt(
				frappe.db.get_value("Sales Invoice", self.positive_invoice, "outstanding_amount")
			)
		
		if self.negative_invoice:
			self.negative_invoice_outstanding = flt(
				frappe.db.get_value("Sales Invoice", self.negative_invoice, "outstanding_amount")
			)

	def on_submit(self):
		"""Create Journal Entry on submit"""
		self.create_journal_entry()

	def on_cancel(self):
		"""Cancel Journal Entry on cancel"""
		if self.journal_entry:
			je = frappe.get_doc("Journal Entry", self.journal_entry)
			if je.docstatus == 1:
				je.cancel()

	def create_journal_entry(self):
		"""Create Journal Entry for item replacement reconciliation"""
		if not self.positive_invoice or not self.negative_invoice:
			frappe.throw(_("Both Original Invoice and Return/Credit Note are required"))

		pos_outstanding = flt(self.positive_invoice_outstanding)
		neg_outstanding = flt(self.negative_invoice_outstanding)
		
		# Calculate reconciliation amount for item replacement (minimum of original invoice outstanding and absolute return amount)
		recon_amount = min(pos_outstanding, abs(neg_outstanding))
		
		if recon_amount <= 0:
			frappe.throw(_("Reconciliation amount must be greater than 0"))

		# Create Journal Entry for item replacement
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Journal Entry"
		je.posting_date = self.posting_date or nowdate()
		je.company = self.company
		je.is_invoice_outstanding_reconciliation = 1
		je.remark = f"Item Replacement Reconciliation for {self.customer} - Original Invoice: {self.positive_invoice}, Replacement Invoice: {self.negative_invoice}"

		# Credit entry for original invoice (reducing receivable for old items)
		je.append("accounts", {
			"account": self.receivable_account,
			"party_type": "Customer",
			"party": self.customer,
			"reference_type": "Sales Invoice",
			"reference_name": self.positive_invoice,
			"credit_in_account_currency": recon_amount,
		})

		# Debit entry for return/credit note (settling credit for replacement items)
		je.append("accounts", {
			"account": self.receivable_account,
			"party_type": "Customer",
			"party": self.customer,
			"reference_type": "Sales Invoice",
			"reference_name": self.negative_invoice,
			"debit_in_account_currency": recon_amount,
		})

		je.insert()
		je.submit()

		# Update the journal entry link
		frappe.db.set_value("Item Resumption", self.name, "journal_entry", je.name)
		self.journal_entry = je.name

		frappe.msgprint(_("Item Replacement Reconciliation Journal Entry {0} created successfully").format(je.name))

	@frappe.whitelist()
	def get_invoice_items(self, invoice_name, item_table):
		"""Fetch items from selected invoice (for item replacement reference)"""
		if not invoice_name:
			return

		items = frappe.get_all(
			"Sales Invoice Item",
			filters={"parent": invoice_name},
			fields=["item_code", "item_name", "description"]
		)

		self.set(item_table, [])
		for item in items:
			self.append(item_table, {
				"item_code": item.item_code,
				"item_name": item.item_name,
				"description": item.description
			})


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_items_from_invoice(doctype, txt, searchfield, start, page_len, filters):
	"""
	Query method to get items from a specific sales invoice
	Used to filter item selection in child tables
	"""
	invoice_name = filters.get("invoice_name")
	
	if not invoice_name:
		return []
	
	return frappe.db.sql("""
		SELECT DISTINCT
			sii.item_code,
			sii.item_name,
			sii.description
		FROM `tabSales Invoice Item` sii
		WHERE sii.parent = %(invoice_name)s
			AND (sii.item_code LIKE %(txt)s OR sii.item_name LIKE %(txt)s)
		ORDER BY sii.item_code
		LIMIT %(start)s, %(page_len)s
	""", {
		"invoice_name": invoice_name,
		"txt": "%" + txt + "%",
		"start": start,
		"page_len": page_len
	})
