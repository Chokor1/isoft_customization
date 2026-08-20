# Copyright (c) 2026, Isoft and Contributors
# MIT License. See license.txt

"""Bench-scoped RQ queue helpers (backported from Frappe v15).

Reclaimed from `frappe/utils/background_jobs.py`, where they had been added as a
v15 backport to support the `RQ Job` DocType.

`is_queue_accessible()` was broken: it called `List(get_queues_timeout())` --
`typing.List` is not callable, so it raised `TypeError` on the first invocation.
Because `get_queues()` calls it for every queue, the RQ Job list view could never
load. `isoft_command_center_client.collectors.workers` documents working around
exactly this. `generate_qname()` had the same `isinstance(qtype, List)` mistake,
which silently never matched.

Both now use the builtin `list` / `tuple`. `get_bench_id()` is implemented here
rather than imported so this module does not depend on a framework-level
backport that may be reverted later.
"""

from __future__ import unicode_literals

import os
from typing import List

import frappe
from rq import Queue

from frappe.utils.background_jobs import get_queues_timeout, get_redis_conn


def get_bench_path():
	return os.path.realpath(
		os.path.join(os.path.dirname(frappe.__file__), "..", "..", "..")
	)


def get_bench_id():
	"""Identifier for this bench, used to namespace queue names."""
	return frappe.get_conf().get("bench_id", get_bench_path().strip("/").replace("/", "-"))


def generate_qname(qtype) -> str:
	"""Build a queue name by combining the bench id with the queue type.

	qnames namespace one bench's queues away from another's on a shared Redis.
	"""
	if isinstance(qtype, (list, tuple)):
		qtype = ",".join(qtype)
	return f"{get_bench_id()}:{qtype}"


def is_queue_accessible(qobj: Queue) -> bool:
	"""True when the queue belongs to this bench.

	Frappe only began prefixing queue names with the bench id in v14. This bench
	runs v13, where the queues are plainly named `default` / `short` / `long`, so
	both forms are accepted -- matching only the prefixed form would report every
	queue as inaccessible and leave the RQ Job list permanently empty.
	"""
	qtypes = list(get_queues_timeout())
	accessible_queues = set(qtypes) | {generate_qname(q) for q in qtypes}
	return qobj.name in accessible_queues


def get_queues(connection=None) -> List[Queue]:
	"""Every RQ queue belonging to this bench."""
	queues = Queue.all(connection=connection or get_redis_conn())
	return [q for q in queues if is_queue_accessible(q)]
