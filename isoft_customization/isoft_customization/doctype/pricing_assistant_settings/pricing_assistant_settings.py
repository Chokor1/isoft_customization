"""Pricing Assistant Settings: the rounding rule and opening defaults of the
Pricing Assistant (public/js/target_total_assistant.js). The desk JS reads and
writes it through isoft_customization.pricing_assistant.
"""
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class PricingAssistantSettings(Document):
	def validate(self):
		base = flt(self.rounding_base)
		rows = self.get("rounding_rules") or []
		if rows and base <= 0:
			frappe.throw(_("Block size must be greater than zero when thresholds are set."))
		for row in rows:
			if not (0 < flt(row.upto) <= base):
				frappe.throw(_("Row {0}: Remainder below must be between 0 and the block size ({1}).").format(row.idx, base))
			if not (0 <= flt(row.round_to) <= base):
				frappe.throw(_("Row {0}: Round to must be between 0 and the block size ({1}).").format(row.idx, base))
		# keep them sorted so the first match wins the way the help text says
		rows.sort(key=lambda r: flt(r.upto))
		for i, row in enumerate(rows, 1):
			row.idx = i
