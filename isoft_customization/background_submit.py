"""Submit or cancel documents with many child rows from a background worker.

The desk runs ``doc.submit()`` inside the HTTP request that the Submit button
fires (frappe.desk.form.save.savedocs). A Purchase Invoice with thousands of
rows needs far longer than the web tier allows: gunicorn ``-t`` and nginx
``proxy_read_timeout`` are both 120 s on a stock bench. At the limit gunicorn
kills the worker, MariaDB rolls the open transaction back, and the browser is
left with a frozen form and a Draft document. The same code finishes from
``bench console`` because the console has no request timeout.

ERPNext solves this for Stock Reconciliation by routing large documents through
``Document.queue_action`` (>100 rows). This module generalises that pattern so
any DocType can adopt it through an ``override_doctype_class`` entry::

    class IsoftPurchaseInvoice(BackgroundSubmitMixin, PurchaseInvoice):
        pass

Behaviour
---------
* Only interactive HTTP requests are affected. ``bench console``, data import,
  patches, tests and REST ``PUT`` calls keep their synchronous behaviour, so an
  administrator's existing console workflow still works unchanged.
* Threshold: ``background_submit_min_rows`` in site_config.json (default 200).
  A document whose ``items`` table has MORE rows than this is queued. Set it to
  0 to switch the feature off for a site.
* The job runs on the ``long`` queue with its own timeout (JOB_TIMEOUT). While
  it is queued the document carries a Frappe file lock; the form script
  ``public/js/purchase_invoice.js`` reads the ``__onload`` flag set here and
  hides Submit / Cancel until the job has landed. On success the worker's save
  publishes ``doc_update`` and the open form reloads by itself. On failure
  ``frappe.model.document.execute_action`` rolls back, adds an "Action Failed"
  comment with the error, and the document keeps its previous docstatus.
* Locks older than STALE_LOCK_SECONDS are treated as orphaned (the job never
  reached a worker: workers down, Redis flushed) and are cleared before
  re-queueing, instead of Frappe's stock behaviour of refusing forever with
  "This document is currently queued for execution".

Requires a ``bench worker --queue long`` process on the site's bench. When no
worker is registered for that queue in Redis the document is processed in the
foreground instead (with a warning), because a job nobody will ever pick up is
worse than a slow request. A lock that has outlived STALE_LOCK_SECONDS is
reported to the form as stale so Submit / Cancel come back and a second click
re-queues (or runs inline) after clearing it.
"""
from __future__ import unicode_literals

import os
import time

import frappe
from frappe import _
from frappe.utils import file_lock

DEFAULT_MIN_ROWS = 200
CONF_KEY = "background_submit_min_rows"
QUEUE = "long"
# Seconds one document may take on the worker. Generous on purpose: a 5000 row
# invoice with update_stock posts thousands of GL and stock ledger rows.
JOB_TIMEOUT = 4 * 60 * 60
# execute_action deletes the lock as its first step, so a lock this old means the
# job never started. Matches frappe.utils.file_lock.check_lock's own timeout.
STALE_LOCK_SECONDS = 600

ONLOAD_FLAG = "isoft_background_queued"
STALE_FLAG = "isoft_background_stale_minutes"

ACTION_LABELS = {
	"submit": "submission",
	"cancel": "cancellation",
}


def get_min_rows():
	value = frappe.conf.get(CONF_KEY)
	if value is None:
		return DEFAULT_MIN_ROWS
	try:
		return int(value)
	except (TypeError, ValueError):
		return DEFAULT_MIN_ROWS


def is_interactive_request():
	"""True for a real desk / API call, False for console, import, patch, test, worker."""
	if not getattr(frappe.local, "request", None):
		return False
	flags = frappe.flags
	return not (
		flags.in_import
		or flags.in_test
		or flags.in_patch
		or flags.in_migrate
		or flags.in_install
	)


def lock_age(doc):
	"""Seconds since the document's queue lock was created, or None when unlocked."""
	if not doc.creation:
		# Unsaved document (new form, mapper output such as Purchase Receipt ->
		# Purchase Invoice): get_signature() would hash None. Nothing can be queued.
		return None
	path = file_lock.get_lock_path(doc.get_signature())
	try:
		return time.time() - os.path.getmtime(path)
	except OSError:
		return None


def is_queued(doc):
	"""Lock present and young enough that a worker may still pick the job up."""
	age = lock_age(doc)
	return age is not None and age <= STALE_LOCK_SECONDS


def stale_minutes(doc):
	"""Minutes a lock has outlived STALE_LOCK_SECONDS, or 0 when not stale."""
	age = lock_age(doc)
	if age is None or age <= STALE_LOCK_SECONDS:
		return 0
	return int(age // 60)


def worker_available(queue=QUEUE):
	"""True when at least one RQ worker registered in Redis listens on ``queue``."""
	try:
		from rq import Worker
		from frappe.utils.background_jobs import get_redis_conn

		return any(queue in w.queue_names() for w in Worker.all(connection=get_redis_conn()))
	except Exception:
		return False


def should_run_in_background(doc, rows_field="items"):
	if not is_interactive_request():
		return False
	min_rows = get_min_rows()
	if min_rows <= 0:
		return False
	if not doc.name or not doc.creation or not frappe.db.exists(doc.doctype, doc.name):
		# Never saved: nothing for the worker to load. Fall through to inline.
		return False
	return len(doc.get(rows_field) or []) > min_rows


def clear_stale_lock(doc):
	age = lock_age(doc)
	if age is not None and age > STALE_LOCK_SECONDS:
		doc.unlock()
		try:
			frappe.logger("isoft_customization").warning(
				"Cleared orphaned background-submit lock on {0} {1} ({2:.0f}s old)".format(
					doc.doctype, doc.name, age
				)
			)
		except Exception:
			# Logging must never block the user's action (the log dir resolves relative
			# to the working directory and is missing outside gunicorn / workers).
			pass
		doc.add_comment(
			"Comment",
			_(
				"A previous background job for this document never started and its lock was cleared automatically."
			),
		)


def queue_document_action(doc, action, rows_field="items"):
	"""Hand ``action`` ('submit' / 'cancel') to the long queue and tell the user."""
	clear_stale_lock(doc)
	# queue_action resolves 'submit' -> '_submit' so the override is not re-entered
	# on the worker, and raises a friendly error if the document is already queued.
	# enqueue_after_commit: the worker must not pick the job up before this request
	# has committed (the lock comment above, or a failed request that rolls back).
	doc.queue_action(action, queue=QUEUE, timeout=JOB_TIMEOUT, enqueue_after_commit=True)
	doc.set_onload(ONLOAD_FLAG, True)
	frappe.msgprint(
		_(
			"This document has {0} rows. Its {1} has been queued as a background job and the form will refresh when it finishes. If it fails, the error is added as a comment and the document keeps its current status."
		).format(len(doc.get(rows_field) or []), _(ACTION_LABELS[action])),
		title=_("Queued in background"),
		indicator="orange",
	)


class BackgroundSubmitMixin(object):
	"""Mix in ahead of the ERPNext controller: ``class X(BackgroundSubmitMixin, PurchaseInvoice)``."""

	background_rows_field = "items"

	def onload(self):
		super(BackgroundSubmitMixin, self).onload()
		self.set_onload(ONLOAD_FLAG, is_queued(self))
		self.set_onload(STALE_FLAG, stale_minutes(self))

	def _wants_background(self):
		if not should_run_in_background(self, self.background_rows_field):
			return False
		if worker_available():
			return True
		# Queueing now would strand the document behind a lock nobody clears.
		clear_stale_lock(self)
		frappe.msgprint(
			_(
				"No background worker is listening on the '{0}' queue, so this large document is being processed in the foreground. Ask the administrator to start the workers."
			).format(QUEUE),
			title=_("Background worker unavailable"),
			indicator="orange",
		)
		return False

	def submit(self):
		if self._wants_background():
			queue_document_action(self, "submit", self.background_rows_field)
			# savedocs flips docstatus to 1 on this in-memory copy before calling
			# submit(). The database still says Draft, and that is what the browser
			# must show until the worker has actually posted the document.
			self.docstatus = 0
		else:
			self._submit()

	def cancel(self):
		if self._wants_background():
			queue_document_action(self, "cancel", self.background_rows_field)
		else:
			self._cancel()
