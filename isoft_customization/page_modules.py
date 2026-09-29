# Copyright (c) 2026, Isoft and Contributors
# MIT License. See license.txt

"""Keep this app's desk Pages pointing at this app's own files.

A standard Page is imported from its .json only when the file's `modified` is
newer than the record's (frappe/modules/import_file.py, `is_db_timestamp_latest`
uses <=, so equal timestamps skip). Moving a page from one app to another
changes `module` inside the file, but if `modified` is left untouched migrate
skips that file for ever. The record keeps the module it was first imported
under, Frappe looks for the page's .js under that old module's folder, finds
nothing, and renders a blank page with no error anywhere.

That is exactly what happened to `account-rename-tool`: created under erpnext's
Accounts module, later moved here, with the timestamp left alone. Sites that
imported it after the move (dev) were fine; sites that had imported it before
(production) kept module = Accounts and showed an empty page.

Bumping the timestamp fixes it once. This runs on every migrate and fixes it
for good: it compares each of this app's page files with its record and
re-imports any whose module has drifted. Cheap -- the app owns two pages -- and
idempotent, so it costs nothing on a healthy site.
"""

from __future__ import unicode_literals

import json
import os

import frappe
from frappe.modules.import_file import import_file_by_path

APP = "isoft_customization"


def page_files():
	"""Every `<module>/page/<name>/<name>.json` this app ships."""
	for module in frappe.get_module_list(APP):
		try:
			page_root = os.path.join(frappe.get_module_path(module), "page")
		except Exception:
			continue
		if not os.path.isdir(page_root):
			continue
		for folder in sorted(os.listdir(page_root)):
			path = os.path.join(page_root, folder, folder + ".json")
			if os.path.exists(path):
				yield path


def sync_page_modules():
	"""Re-import any page whose record no longer names the module of its file."""
	repaired = []
	for path in page_files():
		try:
			with open(path) as handle:
				doc = json.load(handle)
		except Exception:
			continue

		name, file_module = doc.get("name"), doc.get("module")
		if not (name and file_module) or not frappe.db.exists("Page", name):
			continue

		db_module = frappe.db.get_value("Page", name, "module")
		if db_module == file_module:
			continue

		# force=True: the whole point is that the timestamps do not help here.
		import_file_by_path(path, force=True)
		repaired.append((name, db_module, file_module))

	if repaired:
		frappe.clear_cache()
		for name, was, now in repaired:
			print("isoft_customization: Page {0} re-imported, module {1} -> {2}".format(name, was, now))
	return repaired
