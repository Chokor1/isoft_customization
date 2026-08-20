# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import format_datetime, getdate, now_datetime

# Per voucher type: which stored field on the master holds the party account.
# For Payment Entry the field depends on payment_type, so it is resolved per row.
PARTY_ACCOUNT_FIELD = {
	"Sales Invoice": "debit_to",
	"Purchase Invoice": "credit_to",
}

# Expected account type for each party type (strict guardrail). ERPNext party
# accounts are identified by account_type, not root_type (localized charts keep
# Receivable/Payable accounts under root_type Asset/Liability).
EXPECTED_ACCOUNT_TYPE = {
	"Customer": "Receivable",
	"Supplier": "Payable",
}


class PartyAccountReplacementTool(Document):
	@frappe.whitelist()
	def fetch_transactions(self):
		"""Populate the `transactions` table with submitted vouchers for the party."""
		self.set("transactions", [])

		if not (self.company and self.party_type and self.party):
			frappe.throw(_("Please set Company, Party Type and Party first."))

		currency_cache = {}

		def account_currency(account):
			if account not in currency_cache:
				currency_cache[account] = frappe.db.get_value("Account", account, "account_currency")
			return currency_cache[account]

		rows = []
		rows.extend(self._fetch_invoices(account_currency))
		rows.extend(self._fetch_payment_entries(account_currency))

		rows.sort(key=lambda r: (r["posting_date"] or getdate("1900-01-01")))

		for row in rows:
			# Nothing to do if the voucher already sits on the target account.
			if self.new_account and row["current_account"] == self.new_account:
				continue
			self.append("transactions", row)

		if not self.get("transactions"):
			frappe.msgprint(_("No matching submitted vouchers were found for this party."))

		self.save(ignore_permissions=True)
		return self.get("transactions")

	def _date_filters(self):
		date_filter = {}
		if self.from_date and self.to_date:
			date_filter["posting_date"] = ["between", [self.from_date, self.to_date]]
		elif self.from_date:
			date_filter["posting_date"] = [">=", self.from_date]
		elif self.to_date:
			date_filter["posting_date"] = ["<=", self.to_date]
		return date_filter

	def _fetch_invoices(self, account_currency):
		"""Sales Invoice (Customer) or Purchase Invoice (Supplier) party-account vouchers."""
		if self.party_type == "Customer":
			doctype, party_field, account_field = "Sales Invoice", "customer", "debit_to"
		else:
			doctype, party_field, account_field = "Purchase Invoice", "supplier", "credit_to"

		filters = {
			"docstatus": 1,
			"company": self.company,
			party_field: self.party,
		}
		if self.old_account:
			filters[account_field] = self.old_account
		filters.update(self._date_filters())

		records = frappe.get_all(
			doctype,
			filters=filters,
			fields=["name", "posting_date", account_field + " as current_account", "grand_total as amount"],
		)

		return [
			{
				"voucher_type": doctype,
				"voucher_no": r.name,
				"posting_date": r.posting_date,
				"current_account": r.current_account,
				"account_currency": account_currency(r.current_account),
				"amount": r.amount,
				"select": 1,
			}
			for r in records
		]

	def _fetch_payment_entries(self, account_currency):
		"""Payment Entry party-account vouchers (paid_from for Receive, paid_to for Pay)."""
		filters = {
			"docstatus": 1,
			"company": self.company,
			"party_type": self.party_type,
			"party": self.party,
		}
		filters.update(self._date_filters())

		records = frappe.get_all(
			"Payment Entry",
			filters=filters,
			fields=[
				"name",
				"posting_date",
				"payment_type",
				"paid_from",
				"paid_to",
				"paid_amount",
			],
		)

		rows = []
		for r in records:
			current_account = r.paid_from if r.payment_type == "Receive" else r.paid_to
			if not current_account:
				continue
			if self.old_account and current_account != self.old_account:
				continue
			rows.append(
				{
					"voucher_type": "Payment Entry",
					"voucher_no": r.name,
					"posting_date": r.posting_date,
					"current_account": current_account,
					"account_currency": account_currency(current_account),
					"amount": r.paid_amount,
					"select": 1,
				}
			)
		return rows

	@frappe.whitelist()
	def replace_accounts(self):
		"""Re-point the party account on each selected voucher and its GL entries."""
		if not self.new_account:
			frappe.throw(_("Please select a New Account."))

		new_meta = frappe.db.get_value(
			"Account",
			self.new_account,
			["company", "account_type", "is_group", "account_currency"],
			as_dict=True,
		)
		if not new_meta:
			frappe.throw(_("New Account {0} does not exist.").format(self.new_account))

		# --- strict guardrails on the target account ---
		if new_meta.is_group:
			frappe.throw(_("New Account {0} is a group account.").format(self.new_account))
		if new_meta.company != self.company:
			frappe.throw(
				_("New Account {0} does not belong to company {1}.").format(self.new_account, self.company)
			)
		expected_type = EXPECTED_ACCOUNT_TYPE.get(self.party_type)
		if new_meta.account_type != expected_type:
			frappe.throw(
				_("New Account {0} must be of account type {1} for a {2}.").format(
					self.new_account, expected_type, self.party_type
				)
			)

		selected = [d for d in self.get("transactions") if d.select]
		if not selected:
			frappe.throw(_("No rows are selected for replacement."))

		replaced, skipped = 0, 0
		for idx, row in enumerate(selected):
			if row.current_account == self.new_account:
				row.status = _("Already on target account")
				skipped += 1
				continue
			# Currency must match so account-currency GL amounts stay valid.
			if row.account_currency and row.account_currency != new_meta.account_currency:
				row.status = _("Skipped: currency {0} != {1}").format(
					row.account_currency, new_meta.account_currency
				)
				skipped += 1
				continue

			# Per-row savepoint: a failure rolls back only this voucher, not the batch.
			savepoint = "par_row_{0}".format(idx)
			frappe.db.savepoint(savepoint)
			try:
				self._replace_for_voucher(row)
				row.status = _("Replaced")
				replaced += 1
			except Exception as e:
				frappe.db.rollback(save_point=savepoint)
				row.status = _("Error: {0}").format(str(e))[:140]
				skipped += 1

		# Audit trail on this tool itself.
		self.add_comment(
			"Info",
			text=_("Replaced party account to {0}: {1} voucher(s) updated, {2} skipped.").format(
				self.new_account, replaced, skipped
			),
		)
		self.save(ignore_permissions=True)
		frappe.db.commit()

		frappe.msgprint(
			_("{0} voucher(s) updated to account {1}. {2} skipped.").format(
				replaced, self.new_account, skipped
			)
		)
		return {"replaced": replaced, "skipped": skipped}

	def _replace_for_voucher(self, row):
		"""Update the master party-account field, its GL entries, and log on the document."""
		voucher_type = row.voucher_type
		voucher_no = row.voucher_no
		old_account = row.current_account

		# Resolve the master field holding the party account.
		field = PARTY_ACCOUNT_FIELD.get(voucher_type)
		if voucher_type == "Payment Entry":
			payment_type = frappe.db.get_value("Payment Entry", voucher_no, "payment_type")
			field = "paid_from" if payment_type == "Receive" else "paid_to"
		if not field:
			frappe.throw(_("Unsupported voucher type {0}.").format(voucher_type))

		# 1) Master field (submitted doc, updated directly without amend).
		frappe.db.set_value(voucher_type, voucher_no, field, self.new_account, update_modified=False)

		# 2) GL Entries: only the party line(s) on the old account are touched.
		gl_entries = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": voucher_type,
				"voucher_no": voucher_no,
				"account": old_account,
				"party_type": self.party_type,
				"party": self.party,
				"is_cancelled": 0,
			},
			pluck="name",
		)
		if not gl_entries:
			frappe.throw(_("No matching GL Entry found on {0} for account {1}.").format(voucher_no, old_account))

		for gle in gl_entries:
			frappe.db.set_value("GL Entry", gle, "account", self.new_account, update_modified=False)

		# 3) Audit comment on the source document.
		frappe.get_doc(voucher_type, voucher_no).add_comment(
			"Info",
			text=_("Party account changed from {0} to {1} via Party Account Replacement Tool by {2} on {3}.").format(
				old_account, self.new_account, frappe.session.user, format_datetime(now_datetime())
			),
		)
