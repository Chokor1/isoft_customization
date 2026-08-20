# Copyright (c) 2026, Isoft and Contributors
# MIT License. See license.txt

"""Event-driven Statement of Accounts emails.

Reclaimed from `erpnext/accounts/doctype/process_statement_of_accounts`. Two
defects were fixed on the way out:

  * `filters` was read before it was assigned, so every call raised
    `UnboundLocalError`. The dict is now built first and the per-doctype flag
    set afterwards.
  * Three `frappe.msgprint()` debug calls ("gg1", "gg2", a bare row count) that
    would have popped dialogs at the user on every invoice submit.

The function is not wired to any hook. Enable it by calling
`auto_email_by_event(doc.customer, doc.doctype)` from a `doc_events` handler.
"""

from __future__ import unicode_literals

import frappe

#: Transaction types that can trigger a statement, mapped to the flag on
#: Process Statement Of Accounts that opts a profile in to that trigger.
TRIGGER_FIELD_BY_DOCTYPE = {
	"Sales Invoice": "sales_invoice",
	"Payment Entry": "payment_entry",
}


@frappe.whitelist()
def auto_email_by_event(customer, doctype):
	"""Send the statement to `customer` for every profile that opts in to `doctype`.

	Returns True when at least one statement was queued, False otherwise.
	"""
	trigger_field = TRIGGER_FIELD_BY_DOCTYPE.get(doctype)
	if not trigger_field:
		return False

	customer_group, territory = frappe.db.get_value(
		"Customer", customer, ["customer_group", "territory"]
	) or (None, None)

	filters = {
		"enable_auto_email": 1,
		"auto_email_event_based": 1,
		trigger_field: 1,
	}

	# A profile targets either a Customer Group or a Territory, never both.
	if customer_group:
		filters["customer_collection"] = "Customer Group"
		filters["collection_name"] = customer_group
	elif territory:
		filters["customer_collection"] = "Territory"
		filters["collection_name"] = territory
	else:
		return False

	selected = frappe.get_list("Process Statement Of Accounts", filters=filters)
	if not selected:
		return False

	from erpnext.accounts.doctype.process_statement_of_accounts.process_statement_of_accounts import (
		send_email_to_customer,
	)

	for entry in selected:
		send_email_to_customer(entry.name, customer, from_scheduler=True)

	return True
