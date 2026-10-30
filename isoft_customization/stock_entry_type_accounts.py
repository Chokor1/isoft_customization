"""Default Difference (expense) Account per Stock Entry Type and company.

Like the fork's Stock Reconciliation Type "Default Account", but per company:
Stock Entry Type gets a table (Custom Field `default_accounts`, child
Stock Entry Type Account: company, expense_account). On a Stock Entry of that
type, item rows whose Difference Account is empty or still holds the company
default (Stock Adjustment Account, or Default Expense Account for Material
Issue) get the type's account; an account picked by hand on a row stays.

Hooked on before_validate (ERPNext's own validate refuses an empty Difference
Account, so it has to run earlier) and mirrored in public/js/stock_entry.js so
the form shows it as soon as the type or the rows change.
"""
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import now


def setup_custom_fields():
	"""after_migrate: the table on Stock Entry Type (idempotent)."""
	if frappe.get_meta("Stock Entry Type").get_field("default_accounts"):
		return
	create_custom_fields({
		"Stock Entry Type": [{
			"fieldname": "default_accounts",
			"label": "Default Difference Account by Company",
			"fieldtype": "Table",
			"options": "Stock Entry Type Account",
			"insert_after": "add_to_transit",
			"description": "Item rows of a Stock Entry of this type use this account as Difference Account instead of the company's Stock Adjustment Account. Accounts chosen by hand on a row are kept.",
		}]
	}, update=False)
	frappe.db.set_value("DocType", "Stock Entry Type", "modified", now(), update_modified=False)
	frappe.clear_cache(doctype="Stock Entry Type")


def validate_type_accounts(doc, method=None, *args, **kwargs):
	"""Stock Entry Type validate: one row per company, account of that company, no groups."""
	seen = set()
	for row in doc.get("default_accounts") or []:
		if row.company in seen:
			frappe.throw(_("Row {0}: {1} is listed twice.").format(row.idx, row.company))
		seen.add(row.company)
		acc = frappe.db.get_value("Account", row.expense_account, ["company", "is_group"], as_dict=True)
		if not acc or acc.company != row.company:
			frappe.throw(_("Row {0}: {1} does not belong to {2}.").format(row.idx, row.expense_account, row.company))
		if acc.is_group:
			frappe.throw(_("Row {0}: {1} is a group account.").format(row.idx, row.expense_account))


@frappe.whitelist()
def get_default_expense_account(stock_entry_type, company):
	if not stock_entry_type or not company:
		return None
	return frappe.db.get_value("Stock Entry Type Account",
		{"parent": stock_entry_type, "parenttype": "Stock Entry Type", "company": company}, "expense_account")


@frappe.whitelist()
def get_form_defaults(stock_entry_type, company):
	"""For the form: the type's account and the company defaults it should replace."""
	return {
		"account": get_default_expense_account(stock_entry_type, company),
		"company_defaults": sorted(company_defaults(company)) if company else [],
	}


def company_defaults(company):
	c = frappe.get_cached_value("Company", company, ["stock_adjustment_account", "default_expense_account"], as_dict=True) or {}
	return {a for a in (c.get("stock_adjustment_account"), c.get("default_expense_account")) if a}


def apply_to_stock_entry(doc, method=None, *args, **kwargs):
	account = get_default_expense_account(doc.get("stock_entry_type"), doc.get("company"))
	if not account:
		return
	defaults = company_defaults(doc.company)
	for row in doc.get("items") or []:
		if not row.get("expense_account") or row.expense_account in defaults:
			row.expense_account = account
