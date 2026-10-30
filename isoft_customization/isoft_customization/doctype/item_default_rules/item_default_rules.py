from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.model.document import Document


class ItemDefaultRules(Document):
	def validate(self):
		for row in self.get("rules") or []:
			if row.condition == "Item Group" and not row.item_group:
				frappe.throw(_("Row {0}: choose the Item Group.").format(row.idx))
			if row.condition == "Brand" and not row.brand:
				frappe.throw(_("Row {0}: choose the Brand.").format(row.idx))
			if not (row.income_account or row.expense_account or row.default_warehouse or row.selling_cost_center):
				frappe.throw(_("Row {0}: set at least one default.").format(row.idx))
			for f in ("income_account", "expense_account"):
				if row.get(f) and frappe.db.get_value("Account", row.get(f), "company") != row.company:
					frappe.throw(_("Row {0}: {1} does not belong to {2}.").format(row.idx, row.get(f), row.company))
