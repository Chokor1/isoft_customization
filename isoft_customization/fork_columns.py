# Copyright (c) 2026, Isoft and Contributors
# MIT License. See license.txt

"""Columns the ERPNext fork writes or reads but does not define.

The fork's Quotation.on_submit (add_mapped_identity) runs raw SQL against
`tabQuotation`.mapped_identity and `tabQuotation`.tax_id, and the General Ledger
report filters on `tabDelivery Note`.sales_mapped_identity when a voucher is
picked. None of the three is in the fork's doctype JSON. They arrived as Custom
Fields from woocommerceconnector's fixtures, so a site without that app fails
Quotation submit with "1054 Unknown column 'mapped_identity'".

They carry real data:

* Quotation.mapped_identity is set to the quotation's own name. Making a Sales
  Invoice from the quotation copies it into the invoice's standard
  mapped_identity field, which the invoice print formats show as "Requisicao:".
  It must therefore NOT be no_copy -- the mapper skips no_copy fields on either
  side (frappe/model/mapper.py).
* Quotation.tax_id is a snapshot of the customer's NIF at submit. It is no_copy:
  isoft_angola_tax_compliance validates `doc.tax_id or customer NIF`, and a
  duplicated quotation must not bring an old NIF into that check.
* Delivery Note.sales_mapped_identity receives the Sales Invoice's
  sales_mapped_identity (its own name) when the note is made from the invoice.

Only missing fields are created. Sites that already have them (from
woocommerceconnector or by hand) keep their own definitions untouched.
"""

from __future__ import unicode_literals

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import now

FIELDS = {
	"Quotation": [
		{
			"fieldname": "mapped_identity",
			"label": "Mapped Identity",
			"fieldtype": "Data",
			"insert_after": "note",
			"read_only": 1,
			"hidden": 1,
			"allow_on_submit": 1,
			"translatable": 0,
		},
		{
			"fieldname": "tax_id",
			"label": "Tax Id",
			"fieldtype": "Data",
			"insert_after": "customer_name",
			"read_only": 1,
			"no_copy": 1,
			"translatable": 0,
		},
	],
	"Delivery Note": [
		{
			"fieldname": "sales_mapped_identity",
			"label": "Invoice Reference",
			"fieldtype": "Data",
			"insert_after": "sales_team",
			"read_only": 1,
			"translatable": 0,
		},
	],
}


def ensure_fork_columns():
	"""Idempotent; runs from after_migrate."""
	missing = {}
	for doctype, rows in FIELDS.items():
		rows = [
			row
			for row in rows
			if not frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": row["fieldname"]})
		]
		if rows:
			missing[doctype] = rows
	if not missing:
		return

	create_custom_fields(missing, update=False)

	# Browsers cache form meta in localStorage keyed on DocType.modified, which adding a
	# Custom Field does not touch.
	for doctype in missing:
		frappe.db.set_value("DocType", doctype, "modified", now(), update_modified=False)
		frappe.clear_cache(doctype=doctype)
