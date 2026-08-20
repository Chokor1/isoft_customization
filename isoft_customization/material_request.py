# Copyright (c) 2026, Isoft and Contributors
# MIT License. See license.txt

from __future__ import unicode_literals

import json

import frappe
from frappe import _

# processing more than this in one request risks a gateway timeout
MAX_BULK_SIZE = 500


@frappe.whitelist()
def bulk_stop(names):
	"""Set status = Stopped on every submitted, open Material Request in `names`.

	Documents that cannot be stopped (draft, cancelled or already stopped) are
	reported back instead of aborting the whole batch.
	"""
	if isinstance(names, str):
		names = json.loads(names or "[]")

	names = [name for name in (names or []) if name]
	if not names:
		frappe.throw(_("No Material Request selected"))

	if len(names) > MAX_BULK_SIZE:
		frappe.throw(
			_("Cannot stop more than {0} Material Requests at once. Please filter the list.").format(
				MAX_BULK_SIZE
			)
		)

	stopped, skipped, failed = [], [], []

	for name in names:
		try:
			doc = frappe.get_doc("Material Request", name)
			doc.check_permission("write")

			if doc.docstatus != 1:
				skipped.append(
					{
						"name": name,
						"reason": _("Cancelled") if doc.docstatus == 2 else _("Not submitted"),
					}
				)
				continue

			if doc.status == "Stopped":
				skipped.append({"name": name, "reason": _("Already stopped")})
				continue

			doc.update_status("Stopped")
			frappe.db.commit()
			stopped.append(name)
		except Exception as e:
			frappe.db.rollback()
			frappe.log_error(frappe.get_traceback(), "Material Request bulk stop: {0}".format(name))
			failed.append({"name": name, "reason": str(e)})

	return {"stopped": stopped, "skipped": skipped, "failed": failed}
