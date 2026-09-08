# Copyright (c) 2026, Isoft and contributors
# For license information, please see license.txt

"""Company-wise naming series.

One site, several companies, one shared Naming Series option list per DocType:
every company sees every series. This Single maps (Document Type, Company) to
the subset of series that company may use, and marks one of them as default.

Enforced in two places, both no-ops while the setting is disabled or the
(doctype, company) pair has no rows:

* the desk: `public/js/company_naming_series.js` rebuilds the dropdown from
  the map shipped in boot (`boot_session` below) and follows Company changes;
* the server: `before_naming` (hooked on "*") fills the company default when
  the series is blank and rejects a series the company is not assigned. It
  runs only when a document is named, so drafts created before a rule was
  added still save.

A series assigned to a company is exclusive: companies with no rows of their
own only see the series nobody claimed.

"Naming Series Per User" (erpnext fork) stacks on top of this: the desk shows
the intersection, and its own validate hook keeps enforcing the user side.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class IsoftNamingSeriesSettings(Document):
	def validate(self):
		seen = set()
		defaults = set()
		options_cache = {}

		for row in self.series:
			row.naming_series = (row.naming_series or "").strip()
			meta = frappe.get_meta(row.reference_doctype)

			if not meta.get_field("naming_series"):
				frappe.throw(
					_("Row {0}: Document Type {1} does not have a Naming Series field").format(
						row.idx, row.reference_doctype
					)
				)
			if not meta.get_field("company"):
				frappe.throw(
					_("Row {0}: Document Type {1} does not have a Company field").format(
						row.idx, row.reference_doctype
					)
				)

			if row.reference_doctype not in options_cache:
				options_cache[row.reference_doctype] = get_naming_series_options(row.reference_doctype)
			options = options_cache[row.reference_doctype]
			if options and row.naming_series not in options:
				frappe.throw(
					_("Row {0}: {1} is not a naming series option of {2}. Valid options: {3}").format(
						row.idx, row.naming_series, row.reference_doctype, ", ".join(options)
					)
				)

			key = (row.reference_doctype, row.company, row.naming_series)
			if key in seen:
				frappe.throw(
					_("Row {0}: {1} is already assigned to {2} for {3}").format(
						row.idx, row.naming_series, row.company, row.reference_doctype
					)
				)
			seen.add(key)

			if cint(row.is_default):
				if key[:2] in defaults:
					frappe.throw(
						_("Row {0}: {1} already has a default naming series for {2}").format(
							row.idx, row.company, row.reference_doctype
						)
					)
				defaults.add(key[:2])

	def on_update(self):
		# The desk reads the map from boot, and v13 caches boot per user in
		# redis (frappe.sessions.get) until the session cache is cleared. Drop
		# it so the next page load sees the new rules without a re-login.
		frappe.cache().delete_key("bootinfo")


def get_naming_series_options(doctype):
	field = frappe.get_meta(doctype).get_field("naming_series")
	if not field or not field.options:
		return []
	return [s.strip() for s in field.options.split("\n") if s.strip()]


def get_company_series_map():
	"""Per DocType, the series each company may use, or {} when the setting is off.

	    {doctype: {"companies": {company: {"series": [...], "default": series}},
	               "unassigned": [series no company claims]}}

	A series assigned to any company is exclusive: companies without rows of
	their own only get the "unassigned" remainder (which may be empty).

	The Single is read through the document cache, which Frappe clears on
	every save of the settings, so this is cheap enough to call per insert.
	"""
	settings = frappe.get_cached_doc("Isoft Naming Series Settings")
	if not cint(settings.enabled):
		return {}

	result = {}
	for row in settings.series:
		if not (row.reference_doctype and row.company and row.naming_series):
			continue
		by_company = result.setdefault(row.reference_doctype, {"companies": {}, "unassigned": []})["companies"]
		entry = by_company.setdefault(row.company, {"series": [], "default": None})
		if row.naming_series not in entry["series"]:
			entry["series"].append(row.naming_series)
		if cint(row.is_default) and not entry["default"]:
			entry["default"] = row.naming_series

	for doctype, cfg in result.items():
		assigned = set()
		for entry in cfg["companies"].values():
			if not entry["default"]:
				entry["default"] = entry["series"][0]
			assigned.update(entry["series"])
		cfg["unassigned"] = [s for s in get_naming_series_options(doctype) if s not in assigned]

	return result


def get_allowed_series(doctype, company):
	"""(allowed series, default) for `company` on `doctype`; None when unrestricted."""
	cfg = get_company_series_map().get(doctype)
	if not cfg:
		return None

	entry = cfg["companies"].get(company)
	if entry:
		return entry["series"], entry["default"]
	unassigned = cfg["unassigned"]
	return unassigned, (unassigned[0] if unassigned else None)


def boot_session(bootinfo):
	"""Ship the map, plus each DocType's full option list, to the desk."""
	series_map = get_company_series_map()
	if not series_map:
		return

	bootinfo.isoft_company_naming_series = series_map


def apply_company_naming_series(doc, method=None):
	"""before_naming on "*": default and enforce the series for doc.company."""
	if not doc.meta.get_field("naming_series") or not doc.get("company"):
		return
	if doc.get("amended_from") or doc.flags.ignore_naming_series_validation:
		return
	if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_import:
		return

	resolved = get_allowed_series(doc.doctype, doc.company)
	if resolved is None:
		return
	allowed, default = resolved

	if not allowed:
		frappe.throw(
			_(
				"No naming series is available for {0} in company {1}: every series of this "
				"document type is assigned to other companies. Assign one to {1} in Isoft Naming Series Settings."
			).format(_(doc.doctype), frappe.bold(doc.company)),
			title=_("No Naming Series for this Company"),
		)

	# Blank, or still the DocType's own field default: nobody chose this series.
	# frappe.new_doc and friends copy the field default in, so integrations and
	# POS flows that never pick a series get the company default instead of an
	# error. A deliberate choice is enforced below.
	field_default = doc.meta.get_field("naming_series").default
	if not doc.naming_series or (doc.naming_series == field_default and doc.naming_series not in allowed):
		doc.naming_series = default
		return

	if doc.naming_series not in allowed:
		frappe.throw(
			_("Naming Series {0} is not allowed for {1} in company {2}. Allowed: {3}").format(
				frappe.bold(doc.naming_series),
				_(doc.doctype),
				frappe.bold(doc.company),
				", ".join(allowed),
			),
			title=_("Naming Series not allowed for this Company"),
		)


@frappe.whitelist()
def get_doctypes_with_naming_series():
	"""DocTypes that have both a naming_series and a company field."""
	frappe.only_for("System Manager")
	with_series = set(
		frappe.db.sql_list("select parent from `tabDocField` where fieldname='naming_series'")
		+ frappe.db.sql_list("select dt from `tabCustom Field` where fieldname='naming_series'")
	)
	with_company = set(
		frappe.db.sql_list("select parent from `tabDocField` where fieldname='company'")
		+ frappe.db.sql_list("select dt from `tabCustom Field` where fieldname='company'")
	)
	return sorted(with_series & with_company)


@frappe.whitelist()
def get_naming_series_options_map(doctypes):
	"""{doctype: [series, ...]} for the settings grid's per-row dropdown."""
	frappe.only_for("System Manager")
	if isinstance(doctypes, str):
		doctypes = json.loads(doctypes)
	return {dt: get_naming_series_options(dt) for dt in doctypes or [] if frappe.db.exists("DocType", dt)}
