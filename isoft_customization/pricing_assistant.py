"""Server side of the Pricing Assistant (public/js/target_total_assistant.js):
read and save Pricing Assistant Settings from the dialog's gear icon.

Defaults when nothing was ever saved: block 100, below 20 -> 0, below 70 -> 50,
which is the rule the user described (1 030 -> 1 050, 22 390 -> 22 400).
"""
from __future__ import unicode_literals

import frappe
from frappe import _
from frappe.utils import cint, flt

DOCTYPE = "Pricing Assistant Settings"
DEFAULT_BASE = 100
DEFAULT_RULES = [(20, 0), (70, 50)]


@frappe.whitelist()
def get_settings():
	doc = frappe.get_cached_doc(DOCTYPE, DOCTYPE)  # name twice: one arg never reads the cache in v13
	base = flt(doc.rounding_base)
	rules = [{"upto": flt(r.upto), "to": flt(r.round_to)} for r in (doc.get("rounding_rules") or [])]
	# Never saved (no row in tabSingles yet): ship the documented default rule. Once
	# saved, an empty threshold list is a real choice (always up to the next block).
	if not frappe.db.sql("select 1 from tabSingles where doctype=%s limit 1", DOCTYPE):
		base = base or DEFAULT_BASE
		rules = [{"upto": u, "to": t} for u, t in DEFAULT_RULES]
	return {
		"base": base,
		"rules": sorted(rules, key=lambda r: r["upto"]),
		"default_target_kind": doc.default_target_kind or "Grand Total",
		"default_line_mode": doc.default_line_mode or "Price List Rate",
		"apply_rounding_by_default": cint(doc.apply_rounding_by_default),
		"can_write": frappe.has_permission(DOCTYPE, "write"),
	}


@frappe.whitelist()
def save_settings(settings):
	if not frappe.has_permission(DOCTYPE, "write"):
		frappe.throw(_("Not permitted to change Pricing Assistant Settings"), frappe.PermissionError)
	settings = frappe.parse_json(settings) or {}
	doc = frappe.get_doc(DOCTYPE)
	doc.rounding_base = flt(settings.get("base"))
	doc.set("rounding_rules", [])
	for r in settings.get("rules") or []:
		doc.append("rounding_rules", {"upto": flt(r.get("upto")), "round_to": flt(r.get("to"))})
	doc.default_target_kind = settings.get("default_target_kind") or "Grand Total"
	doc.default_line_mode = settings.get("default_line_mode") or "Price List Rate"
	doc.apply_rounding_by_default = cint(settings.get("apply_rounding_by_default"))
	doc.save()
	frappe.clear_cache(doctype=DOCTYPE)
	return get_settings()
