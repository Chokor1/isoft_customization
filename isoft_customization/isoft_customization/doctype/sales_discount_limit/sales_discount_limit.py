from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class SalesDiscountLimit(Document):
	def validate(self):
		seen = set()
		for row in self.get("limits") or []:
			if row.document_type in seen:
				frappe.throw(_("Row {0}: {1} is listed twice.").format(row.idx, _(row.document_type)))
			seen.add(row.document_type)
			for f in ("max_discount_stock", "max_discount_service"):
				if not (0 <= flt(row.get(f)) <= 100):
					frappe.throw(_("Row {0}: discounts must be between 0 and 100%.").format(row.idx))
		frappe.cache().delete_value("isoft_discount_limits")
