"""Browsers cache the Stock Reconciliation form script by DocType.modified."""
from __future__ import unicode_literals

import frappe
from frappe.utils import now


def execute():
	frappe.db.set_value("DocType", "Stock Reconciliation", "modified", now(), update_modified=False)
	frappe.clear_cache(doctype="Stock Reconciliation")
