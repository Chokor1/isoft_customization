# Copyright (c) 2026, Isoft and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals

import json

import frappe
from frappe import _
from frappe.utils import cint

from isoft_customization.excel import (
	build_template_workbook,
	build_workbook,
	read_spreadsheet,
	safe_filename,
)

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
				"reqd": df.reqd,
				"read_only": df.read_only,
				"options": df.options,
				"description": df.description,
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


# ---------------------------------------------------------------------------
# Bulk edit round trip: xlsx template out, xlsx / xls / csv back in
#
# Replaces the core CSV template (six rows of instructions, every field of the
# child doctype, dates in whatever the browser felt like). Same two buttons,
# same wipe-and-refill semantics, spreadsheet instead of CSV.
# ---------------------------------------------------------------------------

# no point offering these in a spreadsheet even though they hold a value
SKIPPED_FIELDTYPES = ("Password", "Signature", "Geolocation", "JSON", "Attach", "Attach Image")
# never write these onto a child row, whatever the sheet says
PROTECTED_FIELDS = (
	"name",
	"owner",
	"creation",
	"modified",
	"modified_by",
	"parent",
	"parentfield",
	"parenttype",
	"doctype",
	"docstatus",
	"idx",
	"_user_tags",
	"_comments",
	"_assign",
	"_liked_by",
)
# how many columns a "visible" template falls back to when nothing is flagged
FALLBACK_COLUMN_COUNT = 10
# rows scanned while hunting for the header row of an uploaded sheet
HEADER_SCAN_ROWS = 25
TRUTHY = ("1", "y", "yes", "true", "sim", "s", "x", "✓", "ok")


def value_fields(meta):
	"""Child fields that can hold a value and make sense in a spreadsheet."""
	from frappe.model import no_value_fields

	return [
		df
		for df in meta.fields
		if df.fieldtype not in no_value_fields and df.fieldtype not in SKIPPED_FIELDTYPES
	]


def template_fields(meta, scope="visible"):
	"""Columns to put in a bulk edit template.

	`all` is every editable field, `visible` narrows it to what the grid and the
	row form actually ask for - which is what makes the sheet usable.
	"""
	# read-only fields stay in: on this site plenty of mandatory ones (charge_type
	# on Sales Taxes and Charges, for instance) are read-only, and the core CSV
	# template included them too. They are flagged in the header tooltip instead.
	fields = [df for df in value_fields(meta) if not df.hidden]

	if scope == "all":
		return fields

	narrowed = [df for df in fields if df.reqd or df.in_list_view or df.bold]
	return narrowed or fields[:FALLBACK_COLUMN_COUNT]


@frappe.whitelist()
def export_grid_template(
	doctype,
	title=None,
	parent_doctype=None,
	parent_name=None,
	fieldnames=None,
	data=None,
	scope="visible",
):
	"""Stream the bulk edit template for a child table, prefilled with its rows."""
	fieldnames = parse(fieldnames, [])
	rows = parse(data, [])

	if parent_doctype and not frappe.has_permission(parent_doctype, "read", doc=parent_name or None):
		raise frappe.PermissionError

	meta = frappe.get_meta(doctype)

	if not fieldnames:
		fieldnames = [df.fieldname for df in template_fields(meta, scope)]

	columns = get_columns(meta, fieldnames)
	if not columns:
		frappe.throw(_("None of the selected columns exist on {0}").format(doctype))

	label = title or _(meta.name)

	xlsx = build_template_workbook(columns=columns, rows=rows, title=label, sheet_name=label)

	filename = safe_filename(
		"{0} - {1}".format(parent_name, label) if parent_name else _("Bulk Edit {0}").format(label)
	)

	frappe.response["filename"] = filename + ".xlsx"
	frappe.response["filecontent"] = xlsx.getvalue()
	frappe.response["type"] = "binary"


@frappe.whitelist()
def import_grid_rows(doctype, filedata, filename=None, parent_doctype=None, parent_name=None):
	"""Parse an uploaded sheet into child rows the browser can drop into the grid.

	Nothing is written here - the rows go back to the form, so the user still
	sees them, can fix them and saves the parent as usual.
	"""
	if parent_doctype and not frappe.has_permission(parent_doctype, "write", doc=parent_name or None):
		raise frappe.PermissionError

	content = decode_upload(filedata)
	table = read_spreadsheet(content, filename)

	if not table:
		frappe.throw(_("{0} is empty").format(filename or _("The file")))

	meta = frappe.get_meta(doctype)
	header_index, mapping = detect_header(table, meta)

	if not mapping:
		frappe.throw(
			_("Could not find a header row in {0}.").format(frappe.bold(filename or _("the file")))
			+ "<br>"
			+ _("Download the template first and edit that - the header row is what tells us which column is which.")
		)

	rows, warnings = parse_rows(table, header_index, mapping, meta)

	return {
		"rows": rows,
		"columns": sorted({df.fieldname for df in mapping.values()}),
		"skipped_columns": skipped_columns(table[header_index], mapping),
		"warnings": warnings[:20],
	}


def decode_upload(filedata):
	"""FileUploader hands us a data URI; accept bare base64 too."""
	import base64

	if isinstance(filedata, bytes):
		return filedata

	filedata = filedata or ""
	if "," in filedata and filedata.startswith("data:"):
		filedata = filedata.split(",", 1)[1]

	try:
		return base64.b64decode(filedata)
	except Exception:
		frappe.throw(_("Could not read the uploaded file"))


def detect_header(table, meta):
	"""Find the row that names the columns and map column index -> docfield.

	Matches fieldnames first (that is what the hidden row of our template holds),
	then falls back to labels, so a sheet built by hand or an older CSV template
	still lands. On a tie the later row wins - in our own template the labels sit
	under the fieldnames, and data starts below whichever we pick.
	"""
	fields = {df.fieldname: df for df in value_fields(meta) if df.fieldname not in PROTECTED_FIELDS}
	by_label = {}
	for df in fields.values():
		for label in (df.label, _(df.label or "")):
			key = normalize_header(label)
			if key:
				by_label.setdefault(key, df)

	best_index, best_mapping = 0, {}

	for index, row in enumerate(table[:HEADER_SCAN_ROWS]):
		mapping = {}
		for position, cell in enumerate(row or []):
			if not isinstance(cell, str):
				continue

			key = cell.strip()
			df = fields.get(key) or by_label.get(normalize_header(key))
			if df and df.fieldname not in {d.fieldname for d in mapping.values()}:
				mapping[position] = df

		if len(mapping) >= len(best_mapping) and mapping:
			best_index, best_mapping = index, mapping

	return best_index, best_mapping


def normalize_header(label):
	import re as _re

	label = frappe.as_unicode(label or "").strip().rstrip("*").strip()
	return _re.sub(r"[^a-z0-9]+", "", label.lower())


def skipped_columns(header_row, mapping):
	"""Header cells we could not place - worth telling the user about."""
	return [
		cell.strip()
		for position, cell in enumerate(header_row or [])
		if isinstance(cell, str) and cell.strip() and position not in mapping
	]


def parse_rows(table, header_index, mapping, meta):
	rows, warnings, blanks = [], [], {}
	start = header_index + 1

	# legacy CSV templates put their instructions under the header and end them
	# with a row of dashes; everything above the dashes is noise
	for index in range(start, min(start + 8, len(table))):
		first = frappe.as_unicode((table[index] or [None])[0] or "").strip()
		if first and set(first) == {"-"}:
			start = index + 1
			break

	for index in range(start, len(table)):
		row = table[index] or []
		if is_noise_row(row, mapping):
			continue

		child = {}
		for position, df in mapping.items():
			raw = row[position] if position < len(row) else None
			try:
				value = parse_cell(raw, df)
			except Exception:
				value = None
				warnings.append(
					_("Row {0}: could not read {1} - left blank").format(index + 1, _(df.label or df.fieldname))
				)

			if value is not None:
				child[df.fieldname] = value

		if not child:
			continue

		for df in mapping.values():
			if df.reqd and child.get(df.fieldname) in (None, ""):
				blanks[df.fieldname] = blanks.get(df.fieldname, 0) + 1

		rows.append(child)

	# one line per column rather than per row - a 300 row sheet missing a
	# mandatory column should not produce 300 warnings
	for df in mapping.values():
		count = blanks.get(df.fieldname)
		if count:
			warnings.append(
				_("{0} is empty in {1} of {2} rows").format(
					_(df.label or df.fieldname), count, len(rows)
				)
			)

	return rows, warnings


def is_noise_row(row, mapping):
	"""Blank rows, separators and the totals row of a formatted export."""
	values = [row[p] for p in mapping if p < len(row)]
	if not any(v not in (None, "") for v in values):
		return True

	first = frappe.as_unicode(next((v for v in values if v not in (None, "")), "")).strip()
	if set(first) == {"-"}:
		return True

	filled = [v for v in values if v not in (None, "")]
	if len(filled) == 1 and first.lower() in ("total", _("Total").lower()):
		return True

	return False


def parse_cell(value, df):
	"""Turn a spreadsheet cell into something the child row will accept."""
	import datetime

	from frappe.utils import cint, flt, get_datetime

	fieldtype = df.fieldtype

	if isinstance(value, str):
		value = value.strip()

	if value in (None, ""):
		return None

	if fieldtype == "Check":
		if isinstance(value, str):
			return 1 if value.strip().lower() in TRUTHY else 0
		return 1 if cint(value) else 0

	if fieldtype == "Int":
		return cint(parse_number(value))

	if fieldtype in ("Currency", "Float", "Percent"):
		return flt(parse_number(value), cint(df.precision) or None)

	if fieldtype == "Date":
		return parse_date(value).strftime("%Y-%m-%d")

	if fieldtype == "Datetime":
		if isinstance(value, datetime.datetime):
			return value.strftime("%Y-%m-%d %H:%M:%S")
		if isinstance(value, datetime.date):
			return value.strftime("%Y-%m-%d 00:00:00")
		return get_datetime(str(value)).strftime("%Y-%m-%d %H:%M:%S")

	if fieldtype == "Time":
		if isinstance(value, datetime.timedelta):
			total = int(value.total_seconds())
			return "{0:02d}:{1:02d}:{2:02d}".format(total // 3600, total // 60 % 60, total % 60)
		if isinstance(value, (datetime.datetime, datetime.time)):
			return value.strftime("%H:%M:%S")
		return get_datetime("2000-01-01 " + str(value)).strftime("%H:%M:%S")

	if isinstance(value, float) and value.is_integer():
		# item codes typed as numbers come back as 1234.0
		value = int(value)

	return frappe.as_unicode(value)


def parse_date(value):
	import datetime

	from frappe.utils import getdate, guess_date_format

	if isinstance(value, datetime.datetime):
		return value.date()
	if isinstance(value, datetime.date):
		return value

	text = frappe.as_unicode(value).strip()
	fmt = guess_date_format(text)
	if fmt:
		from datetime import datetime as dt

		return dt.strptime(text, fmt).date()

	return getdate(text)


def parse_number(value):
	"""Numbers typed by hand carry the user's separators; flt only knows commas."""
	if not isinstance(value, str):
		return value

	import re as _re

	text = _re.sub(r"[^\d,.\-]", "", value).strip()
	if not text:
		return 0

	if "," in text and "." in text:
		decimal = "," if text.rfind(",") > text.rfind(".") else "."
	elif "," in text:
		decimal = "," if site_decimal_separator() == "," else "."
	else:
		decimal = "."

	if decimal == ",":
		text = text.replace(".", "").replace(",", ".")
	else:
		text = text.replace(",", "")

	return text


def site_decimal_separator():
	number_format = frappe.db.get_default("number_format") or "#,###.##"
	try:
		from frappe.utils.data import get_number_format_info

		return get_number_format_info(number_format)[0]
	except Exception:
		return "," if number_format.startswith("#.") else "."
