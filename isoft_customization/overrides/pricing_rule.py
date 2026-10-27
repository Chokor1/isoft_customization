"""Pricing Rule that understands Apply On "Item Group and Brand".

Registered through ``override_doctype_class`` in hooks.py. The rules and the
matching live in isoft_customization.item_group_and_brand; this class only keeps
ERPNext's validate from wiping the two tables that kind of rule needs.
"""
from __future__ import unicode_literals

from erpnext.accounts.doctype.pricing_rule.pricing_rule import PricingRule

from isoft_customization.item_group_and_brand import ITEM_GROUP_AND_BRAND, validate_rule


class IsoftPricingRule(PricingRule):
	def validate_mandatory(self):
		super(IsoftPricingRule, self).validate_mandatory()
		validate_rule(self)

	def cleanup_fields_value(self):
		# ERPNext empties every item table except the one named by Apply On, and
		# this Apply On names none of them.
		if self.apply_on != ITEM_GROUP_AND_BRAND:
			return super(IsoftPricingRule, self).cleanup_fields_value()
		keep = {table: self.get(table) for table in ("item_groups", "brands")}
		super(IsoftPricingRule, self).cleanup_fields_value()
		for table, rows in keep.items():
			self.set(table, rows)
