"""Purchase Invoice with background submit / cancel for large documents.

Registered through ``override_doctype_class`` in hooks.py. All logic lives in
isoft_customization.background_submit; this class only binds it to ERPNext's
controller so that ``frappe.get_doc("Purchase Invoice", ...)`` returns it.
"""
from __future__ import unicode_literals

from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice

from isoft_customization.background_submit import BackgroundSubmitMixin


class IsoftPurchaseInvoice(BackgroundSubmitMixin, PurchaseInvoice):
	pass
