from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class SalesDiscountLimitSettings(Document):
	def validate(self):
		for row in self.get("role_limits") or []:
			for f in ("max_discount_stock", "max_discount_service"):
				if not (0 <= flt(row.get(f)) <= 100):
					frappe.throw(_("Role limits row {0}: discounts must be between 0 and 100%.").format(row.idx))
		frappe.cache().delete_value("isoft_discount_limits")
