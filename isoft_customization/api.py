# Copyright (c) 2026, Isoft and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals

import json

import frappe
from frappe import _
from frappe.utils import cint

from isoft_customization.excel import build_workbook, safe_filename

# `idx` is not a docfield but every child row has one
IDX_FIELD = {"fieldname": "idx", "label": "No.", "fieldtype": "Int", "precision": 0}


def parse(value, default):
	if isinstance(value, str):
		return json.loads(value or "null") or default
	return value if value is not None else default


@frappe.whitelist()
def export_grid(
	doctype,
	fieldnames,
	data,
	title=None,
	parent_doctype=None,
	parent_name=None,
	add_totals=0,
):
	"""Stream a formatted xlsx of the rows the client passed in.

	Rows come from the browser rather than the database on purpose: the grid may
	hold unsaved edits, and the user should get what they are looking at.
	"""
	fieldnames = parse(fieldnames, [])
	rows = parse(data, [])

	if not fieldnames:
		frappe.throw(_("Select at least one column to export"))

	# the payload is the caller's own screen, but don't hand out a formatting
	# endpoint for documents they cannot read
	if parent_doctype:
		if not frappe.has_permission(parent_doctype, "read", doc=parent_name or None):
			raise frappe.PermissionError

	meta = frappe.get_meta(doctype)
	columns = get_columns(meta, fieldnames)

	if not columns:
		frappe.throw(_("None of the selected columns exist on {0}").format(doctype))

	label = title or _(meta.name)
	subtitle = get_subtitle(parent_doctype, parent_name, len(rows))

	xlsx = build_workbook(
		columns=columns,
		rows=rows,
		title=label,
		subtitle=subtitle,
		add_totals=cint(add_totals),
		sheet_name=label,
	)

	filename = safe_filename("{0} - {1}".format(parent_name, label) if parent_name else label)

	frappe.response["filename"] = filename + ".xlsx"
	frappe.response["filecontent"] = xlsx.getvalue()
	frappe.response["type"] = "binary"


def get_columns(meta, fieldnames):
	"""Resolve the requested fieldnames to docfields, keeping the caller's order."""
	by_fieldname = {df.fieldname: df for df in meta.fields}
	columns = []

	for fieldname in fieldnames:
		if fieldname == "idx":
			columns.append(dict(IDX_FIELD))
			continue

		df = by_fieldname.get(fieldname)
		if not df:
			continue

		columns.append(
			{
				"fieldname": df.fieldname,
				"label": df.label or df.fieldname,
				"fieldtype": df.fieldtype,
				"precision": df.precision,
			}
		)

	return columns


def get_subtitle(parent_doctype, parent_name, row_count):
	from frappe.utils import format_datetime, now_datetime

	parts = []
	if parent_doctype and parent_name:
		parts.append("{0}: {1}".format(_(parent_doctype), parent_name))
	parts.append(_("{0} rows").format(row_count))
	parts.append(_("Exported {0} by {1}").format(format_datetime(now_datetime()), frappe.session.user))

	return "  •  ".join(parts)
