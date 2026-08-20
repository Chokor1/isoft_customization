"""Make this app's Portuguese overrides actually win.

The overrides live in isoft_customization/translations/pt.csv, which is the intended
mechanism -- frappe.translate.load_lang() merges every app's catalogue with
out.update() in app order, so a later app overrides an earlier one.

Except this app is not later. That merge walks frappe.get_all_apps(True), which is
sites/apps.txt order, and there isoft_customization sits at 14 while erpnext sits at
16. A plain pt.csv here would be overwritten by erpnext's 9,248-line catalogue for
every key the two share -- silently, and only for the strings that matter most.

(Worth knowing why this is easy to get wrong: hooks use a different order,
frappe.get_installed_apps(), where this app *does* come after erpnext. So the same
app wins for hooks and loses for translations.)

get_full_dict() applies one more layer after all the files:

    frappe.local.lang_full_dict = load_lang(lang)
    frappe.local.lang_full_dict.update(get_user_translations(lang))

get_user_translations() reads the Translation DocType, so those entries beat every
app's file regardless of order. Seeding the CSV into Translation records therefore
guarantees precedence without touching sites/apps.txt, which would reorder asset
builds bench-wide to fix a translation problem.

The CSV stays the source of truth in git; the records are only the enforcement. Run
from after_migrate, so a fresh site and an upgraded one end up the same.
"""
import csv
import os

import frappe

LANG = "pt"


def _csv_path():
	return os.path.join(os.path.dirname(os.path.abspath(__file__)), "translations", LANG + ".csv")


def read_overrides():
	"""[(source, translation, context)] from this app's catalogue."""
	path = _csv_path()
	if not os.path.exists(path):
		return []
	out = []
	with open(path, "r", encoding="utf-8") as f:
		for row in csv.reader(f):
			if not row or len(row) < 2 or not row[0].strip():
				continue
			out.append((row[0], row[1], row[2] if len(row) > 2 else ""))
	return out


def sync_translations():
	"""Upsert this app's overrides as Translation records. Idempotent.

	Only touches rows whose translated_text differs, so a re-run on an unchanged
	catalogue writes nothing and a hand-edit made in the UI is replaced only when the
	CSV actually disagrees with it.
	"""
	overrides = read_overrides()
	if not overrides:
		return {"created": 0, "updated": 0, "unchanged": 0}

	existing = {}
	for row in frappe.get_all(
		"Translation",
		filters={"language": LANG},
		fields=["name", "source_text", "context", "translated_text"],
		limit_page_length=0,
	):
		existing[(row.source_text, row.context or "")] = row

	created = updated = unchanged = 0
	for source, translated, context in overrides:
		found = existing.get((source, context or ""))
		if found is None:
			doc = frappe.get_doc({
				"doctype": "Translation",
				"language": LANG,
				"source_text": source,
				"translated_text": translated,
				"context": context or None,
			})
			doc.insert(ignore_permissions=True)
			created += 1
		elif found.translated_text != translated:
			frappe.db.set_value("Translation", found.name, "translated_text", translated,
			                    update_modified=False)
			updated += 1
		else:
			unchanged += 1

	frappe.db.commit()
	# Both caches are keyed by language and would otherwise serve the old strings.
	frappe.cache().delete_key("lang_user_translations")
	frappe.cache().hdel("lang_full_dict", LANG, shared=True)
	frappe.clear_cache()

	return {"created": created, "updated": updated, "unchanged": unchanged}
