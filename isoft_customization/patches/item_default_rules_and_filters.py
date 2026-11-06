"""Item Default Rules: "Item Group" / "Brand" stop being conditions of their own (2026-11-06).

A rule now applies when its maintain-stock condition AND its item group AND its brand all
match. Rows saved with condition "Item Group" or "Brand" become "Always" (their item group /
brand keeps filtering). Rows that had a hidden item group next to a stock condition start
using it, which is what the user meant when they filled it in.
"""
import frappe


def execute():
	if not frappe.db.table_exists("Item Default Rule"):
		return
	frappe.db.sql(
		"update `tabItem Default Rule` set `condition`='Always' where `condition` in ('Item Group', 'Brand')"
	)
