"""Fill a sales document's Tax Id from its Customer when it arrives empty.

Why: Quotation.tax_id is a no_copy Custom Field (saft_xml owns it so a duplicated
quotation never carries an old NIF), and frappe's mapper skips no_copy fields on
EITHER side -- it even skips fetch_from targets of the same name. So a Sales
Invoice or Sales Order made from a Quotation reached the form with tax_id None,
and nothing refilled it: the fork's Sales Invoice.tax_id has no fetch_from and
the desk only fetches it when the customer field changes.

Hooked on set_missing_values (which the mapper's postprocess runs through
run_method, so hooks fire) and on validate, for Sales Invoice and Sales Order.
Only an EMPTY tax_id is filled: an invoice may legitimately carry a different
NIF than its customer (consumer invoices), and FE Angola reads
`doc.tax_id or customer NIF`.
"""
from __future__ import unicode_literals

# Hook signatures take *args/**kwargs: Frappe forwards the hooked method's own
# arguments to every hook, and the desk's run_doc_method always passes one
# positional `args` (ERPNext's sales_invoice.js calls set_missing_values that way
# when a POS return loads), so a plain (doc, method) hook raises TypeError.
import frappe


def fill_from_customer(doc, method=None, *args, **kwargs):
	if doc.get("tax_id") or not doc.get("customer"):
		return
	if not doc.meta.has_field("tax_id"):
		return
	tax_id = frappe.db.get_value("Customer", doc.customer, "tax_id")
	if tax_id:
		doc.tax_id = tax_id
