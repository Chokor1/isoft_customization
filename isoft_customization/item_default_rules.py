"""Item Default Rules: default accounts (and warehouse / cost centre) for items by
condition, e.g. "items that do not maintain stock -> services income account".

ERPNext only knows defaults per Item, Item Group, Brand and Company; nothing can
hang off a field of the item. The Single "Item Default Rules" holds rows
(company, condition, defaults); per company the rows are checked top to bottom
and the first match wins.

Applied in three places:
* Item validate: for each company with a matching rule, the item's Item Defaults
  row (created if missing) gets the rule's values where it has none. Hand-set
  values are never overwritten.
* Sales Invoice validate / set_missing_values (optional switch): a line whose
  item has no income account of its own and still carries the company default
  gets the rule's income account.
* apply_to_existing_items(): one-off backfill from the settings form.
"""
from __future__ import unicode_literals

import frappe
from frappe.utils import cint

SETTINGS = "Item Default Rules"
FIELDS = ("income_account", "expense_account", "default_warehouse", "selling_cost_center")


def get_settings():
	return frappe.get_single(SETTINGS)  # not get_cached_doc: db.set_value leaves Singles stale


def rule_matches(rule, item):
	c = rule.condition
	if c == "Always":
		return True
	if c == "Maintain Stock is No":
		return not cint(item.get("is_stock_item"))
	if c == "Maintain Stock is Yes":
		return bool(cint(item.get("is_stock_item")))
	if c == "Item Group":
		return bool(rule.item_group) and item.get("item_group") == rule.item_group
	if c == "Brand":
		return bool(rule.brand) and item.get("brand") == rule.brand
	return False


def matching_rules(item, settings=None):
	"""{company: first matching rule} for this item."""
	settings = settings or get_settings()
	if not cint(settings.enabled):
		return {}
	out = {}
	for rule in settings.get("rules") or []:
		if rule.company in out:
			continue
		if rule_matches(rule, item):
			out[rule.company] = rule
	return out


def apply_to_item(doc, method=None, *args, **kwargs):
	"""Item validate hook: fill empty Item Defaults from the matching rules."""
	rules = matching_rules(doc)
	if not rules:
		return
	rows = {r.company: r for r in doc.get("item_defaults") or []}
	for company, rule in rules.items():
		values = {f: rule.get(f) for f in FIELDS if rule.get(f)}
		if not values:
			continue
		row = rows.get(company)
		if not row:
			row = doc.append("item_defaults", {"company": company})
			rows[company] = row
		for f, v in values.items():
			if not row.get(f):
				row.set(f, v)


def apply_on_transaction(doc, method=None, *args, **kwargs):
	"""Sales Invoice: swap the company-default income account for the rule's on
	lines whose item has no income account of its own."""
	settings = get_settings()
	if not cint(settings.enabled) or not cint(settings.apply_on_sales_invoice) or not doc.get("company"):
		return
	company_default = frappe.get_cached_value("Company", doc.company, "default_income_account")
	cache = {}
	for line in doc.get("items") or []:
		if not line.get("item_code"):
			continue
		if line.get("income_account") and line.income_account != company_default:
			continue  # chosen by hand, or already specific
		if line.item_code not in cache:
			item = frappe.db.get_value("Item", line.item_code, ["is_stock_item", "item_group", "brand"], as_dict=True) or {}
			own = frappe.db.get_value("Item Default", {"parent": line.item_code, "company": doc.company}, "income_account")
			rule = matching_rules(item, settings).get(doc.company) if not own else None
			cache[line.item_code] = rule.income_account if rule and rule.income_account else None
		if cache[line.item_code]:
			line.income_account = cache[line.item_code]


@frappe.whitelist()
def apply_to_existing_items(dry_run=1):
	"""Backfill: items whose Item Defaults row (per rule company) lacks a value the
	matching rule provides. dry_run counts; otherwise writes directly to the rows."""
	frappe.only_for(("System Manager", "Accounts Manager", "Stock Manager"))
	settings = get_settings()
	dry_run = cint(dry_run)
	if not cint(settings.enabled) or not settings.get("rules"):
		return {"would_update": 0, "updated": 0}
	items = frappe.get_all("Item", filters={"disabled": 0}, fields=["name", "is_stock_item", "item_group", "brand"])
	would, updated = 0, 0
	for item in items:
		rules = matching_rules(item, settings)
		for company, rule in rules.items():
			values = {f: rule.get(f) for f in FIELDS if rule.get(f)}
			if not values:
				continue
			row = frappe.db.get_value("Item Default", {"parent": item.name, "parenttype": "Item", "company": company},
				["name"] + list(FIELDS), as_dict=True)
			missing = {f: v for f, v in values.items() if not (row and row.get(f))}
			if not missing:
				continue
			would += 1
			if dry_run:
				continue
			if row:
				frappe.db.set_value("Item Default", row.name, missing, update_modified=False)
			else:
				d = frappe.get_doc({"doctype": "Item Default", "parenttype": "Item", "parentfield": "item_defaults", "parent": item.name, "company": company})
				d.update(missing)
				d.insert(ignore_permissions=True)
			updated += 1
	if updated:
		frappe.clear_cache(doctype="Item")
	return {"would_update": would, "updated": updated}
