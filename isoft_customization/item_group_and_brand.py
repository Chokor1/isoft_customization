# Copyright (c) 2026, ISOFT LDA
"""Pricing Rule "Apply On: Item Group and Brand".

A fifth Apply On choice: the rule matches an item only when its item group is in
(or under) one of the rule's Item Groups AND its brand is one of the rule's Brands.
No ERPNext file is edited; four pieces make it work:

1. setup_property_setters (after_migrate) adds the option to `apply_on` and shows
   both the Item Groups and the Brands tables for it.
2. overrides/pricing_rule.py keeps both tables on save (ERPNext's
   cleanup_fields_value empties every table but the Apply On one) and requires a
   row in each.
3. apply() wraps three ERPNext functions:
   - utils._get_pricing_rules. ERPNext looks for rules in stages, Item Code, then
     Item Group, then Brand, and stops at the first stage that finds any. Its query
     joins the stage's child table without checking apply_on, so a rule of this
     kind, holding both tables, comes back at the Item Group stage whenever the
     item's group matches and again at the Brand stage whenever its brand matches.
     The wrapper keeps it at the Item Group stage only when the brand matches too,
     and drops it at the Brand stage, so it is applied once and ranks with the Item
     Group rules, ahead of brand-only ones. It also keeps one row per rule: a rule
     listing a group and its own subgroup otherwise comes back twice and ERPNext
     refuses the line as a conflict with itself.
   - pricing_rule.update_pricing_rule_uom and utils.get_pricing_rule_items look up
     the rule's table by Apply On in a fixed list and crash on any other value
     (on invoice validate). For this kind they read the Item Groups table.
   ERPNext looks all three up as module globals at call time (the last two through
   function-local imports), so reassigning them on the modules takes effect.
4. pricing_rule_conflicts.py treats it as meeting Item Group rules on shared groups.

Mixed Conditions, Is Cumulative and Apply Rule On Other are refused for this kind:
ERPNext's code for them reads the item field named after Apply On, which does not
exist here.

apply() runs from before_request and before_job (hooks.py) and from the package
__init__, the same as the Stock Analytics backport.
"""
import frappe
from frappe import _
from frappe.utils import now

ITEM_GROUP_AND_BRAND = "Item Group and Brand"

UTILS = "erpnext.accounts.doctype.pricing_rule.utils"
PRICING_RULE = "erpnext.accounts.doctype.pricing_rule.pricing_rule"

_original = {}


# ---------------------------------------------------------------------------
# runtime patches
# ---------------------------------------------------------------------------

def _get_pricing_rules(apply_on, args, values):
	rules = _original["_get_pricing_rules"](apply_on, args, values)
	if apply_on == "Item Group":
		rules = [r for r in rules if r.get("apply_on") != ITEM_GROUP_AND_BRAND or _brand_matches(r, args)]
	elif apply_on == "Brand":
		rules = [r for r in rules if r.get("apply_on") != ITEM_GROUP_AND_BRAND]
	return _one_row_per_rule(rules, apply_on)


def _one_row_per_rule(rules, apply_on):
	"""ERPNext's query returns a rule once per child row that matches. A rule listing
	a group and one of its subgroups (ACCESSORIOS and ACCESSORIOS HP) therefore comes
	back twice for an item of the subgroup, and filter_pricing_rules refuses the line:
	"Multiple Price Rules exists with same criteria ... PRLE-0245 PRLE-0245". Keep one
	row per rule; at the Item Group stage the row of the deepest (most specific) group,
	since its UOM is the one meant for the item."""
	kept = {}
	for r in rules:
		seen = kept.get(r.name)
		if seen is None or (apply_on == "Item Group" and _depth(r) > _depth(seen)):
			kept[r.name] = r
	if len(kept) == len(rules):
		return rules
	return [r for r in rules if kept.get(r.name) is r]


def _depth(row):
	if not row.get("item_group"):
		return 0
	return frappe.get_cached_value("Item Group", row.get("item_group"), "lft") or 0


def _brand_matches(rule, args):
	brand = args.get("brand")
	if not brand:
		return False
	# Cached doc: ERPNext reads the same one right after (filter_pricing_rules), and
	# saving the rule clears it.
	return brand in {d.brand for d in frappe.get_cached_doc("Pricing Rule", rule.name).brands}


def update_pricing_rule_uom(pricing_rule, args):
	if pricing_rule.get("apply_on") != ITEM_GROUP_AND_BRAND:
		return _original["update_pricing_rule_uom"](pricing_rule, args)
	for row in pricing_rule.get("item_groups") or []:
		if row.get("item_group") == args.get("item_group"):
			pricing_rule.uom = row.uom


def get_pricing_rule_items(pr_doc):
	if pr_doc.get("apply_on") != ITEM_GROUP_AND_BRAND:
		return _original["get_pricing_rule_items"](pr_doc)
	from erpnext.setup.doctype.item_group.item_group import get_child_item_groups

	groups = []
	for row in pr_doc.get("item_groups") or []:
		groups.extend(get_child_item_groups(row.get("item_group")))
	return list(set(groups))


PATCHES = {
	UTILS: ("_get_pricing_rules", "get_pricing_rule_items"),
	PRICING_RULE: ("update_pricing_rule_uom",),
}


def apply(*args, **kwargs):
	"""Point ERPNext at the wrappers above. Idempotent and cheap.

	Takes *args/**kwargs because before_job passes method/kwargs/transaction_type.
	"""
	import importlib

	for module_name, names in PATCHES.items():
		module = importlib.import_module(module_name)
		for name in names:
			current = getattr(module, name)
			mine = globals()[name]
			if current is not mine:
				_original.setdefault(name, current)
				setattr(module, name, mine)


# ---------------------------------------------------------------------------
# validation (overrides/pricing_rule.py)
# ---------------------------------------------------------------------------

def validate_rule(doc):
	if doc.apply_on != ITEM_GROUP_AND_BRAND:
		return
	for table, label in (("item_groups", _("Item Group")), ("brands", _("Brand"))):
		field = table[:-1]
		values = [d.get(field) for d in doc.get(table) or [] if d.get(field)]
		if not values:
			frappe.throw(_("{0} is not added in the table").format(label), frappe.MandatoryError)
		if len(values) != len(set(values)):
			frappe.throw(_("Duplicate {0} found in the table").format(label))
	for field in ("mixed_conditions", "is_cumulative", "apply_rule_on_other"):
		if doc.get(field):
			frappe.throw(_("{0} cannot be used with Apply On {1}.").format(
				_(doc.meta.get_label(field)), _(ITEM_GROUP_AND_BRAND)))


# ---------------------------------------------------------------------------
# meta (after_migrate)
# ---------------------------------------------------------------------------

def _apply_on_options():
	options = (frappe.db.get_value(
		"DocField", {"parent": "Pricing Rule", "fieldname": "apply_on"}, "options") or "").split("\n")
	if ITEM_GROUP_AND_BRAND not in options:
		at = options.index("Transaction") if "Transaction" in options else len(options)
		options.insert(at, ITEM_GROUP_AND_BRAND)
	return "\n".join(options)


def setup_property_setters():
	"""Idempotent; runs from after_migrate."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	wanted = [
		("apply_on", "options", _apply_on_options(), "Text"),
		("item_groups", "depends_on", "eval:in_list(['Item Group', '{0}'], doc.apply_on)".format(ITEM_GROUP_AND_BRAND), "Code"),
		("brands", "depends_on", "eval:in_list(['Brand', '{0}'], doc.apply_on)".format(ITEM_GROUP_AND_BRAND), "Code"),
	]
	changed = False
	for fieldname, prop, value, prop_type in wanted:
		current = frappe.db.get_value(
			"Property Setter", {"doc_type": "Pricing Rule", "field_name": fieldname, "property": prop}, "value")
		if current != value:
			make_property_setter("Pricing Rule", fieldname, prop, value, prop_type)
			changed = True

	# Browsers cache form meta in localStorage keyed on DocType.modified, which a
	# Property Setter does not touch; without this the option never shows up.
	if changed:
		frappe.db.set_value("DocType", "Pricing Rule", "modified", now(), update_modified=False)
		frappe.clear_cache(doctype="Pricing Rule")
