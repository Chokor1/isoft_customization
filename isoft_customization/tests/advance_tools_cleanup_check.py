"""Check that the old "Advance Tools" module left nothing behind.

Run from sites/:  ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/advance_tools_cleanup_check.py <site> [--apply]
Without --apply it only reports; with --apply it runs the patch and commits.
"""
import sys

import frappe

site = sys.argv[1]
apply = "--apply" in sys.argv
frappe.init(site=site, sites_path=".")
frappe.connect()

if apply:
	from isoft_customization.patches import remove_advance_tools_module

	scrape_rows = frappe.db.sql("select count(*) from `tabScrape Tool Item`")[0][0] if frappe.db.table_exists("Scrape Tool Item") else 0
	frappe.flags.in_patch = True
	remove_advance_tools_module.execute()
	frappe.flags.in_patch = False
	frappe.db.commit()
	if scrape_rows:
		kept = frappe.db.sql("select count(*) from `tabScrape Tool Item`")[0][0]
		print(("PASS" if kept == scrape_rows else "FAIL"), f"Scrape Tool Item table kept ({kept}/{scrape_rows} rows)")

fails = 0
left = []
for doctype in ("DocType", "Report", "Print Format", "Workspace", "Page"):
	left += [(doctype, n) for n in frappe.get_all(doctype, filters={"module": "Advance Tools"}, pluck="name")]
left += [("Module Def", n) for n in frappe.get_all("Module Def", filters={"name": "Advance Tools"}, pluck="name")]
print(("PASS" if not left else "FAIL"), "no Advance Tools records left", left or "")
fails += bool(left)

from frappe.desk.form.load import getdoctype  # noqa: E402

for dt in ("Barcode Generation Tool", "Scrape Tool"):
	try:
		frappe.local.response = frappe._dict(docs=[])
		getdoctype(dt)
		ok, why = False, "still loads"
	except frappe.DoesNotExistError:
		ok, why = True, "DoesNotExistError (gone cleanly)"
	except KeyError as e:
		ok, why = False, f"KeyError {e}"
	except Exception as e:  # noqa: BLE001
		ok, why = "DoesNotExist" in type(e).__name__, f"{type(e).__name__}: {e}"
	print(("PASS" if ok else "FAIL"), f"getdoctype({dt!r}) -> {why}")
	fails += not ok

# what else on this site still points at a module no installed app provides (report only)
known = set(frappe.local.module_app)
custom = set(frappe.get_all("Module Def", filters={"custom": 1}, pluck="name"))
other = {}
for doctype in ("DocType", "Report", "Workspace", "Print Format", "Page"):
	for r in frappe.get_all(doctype, fields=["name", "module"], filters={"module": ["is", "set"]}):
		if frappe.scrub(r.module) not in known and r.module not in custom:
			other.setdefault(r.module, []).append(f"{doctype}:{r.name}")
print("INFO other orphan modules:", {k: len(v) for k, v in other.items()} or "none")
frappe.destroy()
sys.exit(1 if fails else 0)
