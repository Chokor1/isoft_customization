# Copyright (c) 2026, ISOFT LDA
"""Refuse to save a Pricing Rule that collides with another active rule.

ERPNext lets two rules cover the same item with the same priority, then fails
every sales/purchase line that both match: "Multiple Price Rules exists with same
criteria, please resolve conflict by assigning priority"
(erpnext/accounts/doctype/pricing_rule/utils.py, filter_pricing_rules). The
mistake is made when the rule is saved but only surfaces at the counter.

`find_conflicts` mirrors how ERPNext picks rules for a line, so it only reports a
pair that really would collide:

  * same Apply On (Item Code / Item Group / Brand) sharing a value -- ERPNext
    looks at item-code rules first and only falls back to group/brand rules when
    none match, so an item-code rule never collides with a group rule;
  * both selling, or both buying;
  * the parties overlap: either rule is for everyone, or the same party, or one
    customer group / territory / supplier group sits under the other, or a
    customer/supplier belongs to the other rule's group;
  * validity dates, min/max qty and min/max amount ranges overlap;
  * same company, currency, warehouse subtree (a blank matches any);
  * price list: two different lists never meet; for two Discount Percentage
    rules a list-specific rule beats a list-less one, so that pair is fine too;
  * same priority (a higher priority wins quietly, which is not an error);
  * not both "Apply Multiple Pricing Rules" (then they stack), not coupon-based,
    no Python condition (cannot be evaluated here).

The Pricing Rule form calls `check_conflicts` before saving and offers the fixes
(remove the shared items from the old rule, disable it, or give this rule a
higher priority); `validate_no_conflicts` is the doc_events backstop for every
other path (imports, API, Promotional Scheme).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate, nowdate

APPLY_ON = {
	"Item Code": ("items", "item_code", "Pricing Rule Item Code"),
	"Item Group": ("item_groups", "item_group", "Pricing Rule Item Group"),
	"Brand": ("brands", "brand", "Pricing Rule Brand"),
}
TREES = {"Customer Group", "Territory", "Supplier Group"}
PARTY_IN_TREE = (
	("Customer", "Customer Group", "customer_group"),
	("Customer", "Territory", "territory"),
	("Supplier", "Supplier Group", "supplier_group"),
)
MAX_PRIORITY = 20

HEADER_FIELDS = [
	"name", "title", "disable", "priority", "selling", "buying", "apply_on",
	"applicable_for", "customer", "customer_group", "territory", "sales_partner", "campaign",
	"supplier", "supplier_group", "company", "currency", "for_price_list", "warehouse",
	"valid_from", "valid_upto", "min_qty", "max_qty", "min_amt", "max_amt",
	"apply_multiple_pricing_rules", "coupon_code_based", "condition",
	"price_or_product_discount", "rate_or_discount", "discount_percentage", "discount_amount", "rate",
	"promotional_scheme",
]


class PricingRuleConflictError(frappe.ValidationError):
	pass


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------

def _as_dict(doc):
	# isinstance, not hasattr: a frappe._dict answers None for any attribute.
	d = doc.as_dict() if isinstance(doc, Document) else doc
	return frappe._dict(d)


def _tree_related(doctype, a, b):
	"""a == b, or one is inside the other's subtree."""
	if a == b:
		return True
	la = frappe.get_cached_value(doctype, a, ["lft", "rgt"])
	lb = frappe.get_cached_value(doctype, b, ["lft", "rgt"])
	if not la or not lb or None in la or None in lb:
		return False
	return (la[0] <= lb[0] and lb[1] <= la[1]) or (lb[0] <= la[0] and la[1] <= lb[1])


def _parties_overlap(a, b):
	fa, fb = a.get("applicable_for") or "", b.get("applicable_for") or ""
	if not fa or not fb:
		return True
	va, vb = a.get(frappe.scrub(fa)), b.get(frappe.scrub(fb))
	if not va or not vb:
		return True
	if fa == fb:
		return _tree_related(fa, va, vb) if fa in TREES else va == vb
	values = {fa: va, fb: vb}
	for party, tree, field in PARTY_IN_TREE:
		if set(values) == {party, tree}:
			own = frappe.get_cached_value(party, values[party], field)
			return bool(own) and _tree_related(tree, values[tree], own)
	# e.g. a Customer Group rule against a Territory rule: they may share
	# customers, but nothing here can say which, so it is not reported.
	return False


def _ranges_overlap(a_min, a_max, b_min, b_max):
	a_min, a_max, b_min, b_max = flt(a_min), flt(a_max), flt(b_min), flt(b_max)
	return (not a_max or b_min <= a_max) and (not b_max or a_min <= b_max)


def _dates_overlap(a, b):
	af, au = a.get("valid_from"), a.get("valid_upto")
	bf, bu = b.get("valid_from"), b.get("valid_upto")
	return (not af or not bu or getdate(af) <= getdate(bu)) and (not bf or not au or getdate(bf) <= getdate(au))


def _relation(a, b, priority):
	"""How rule b meets candidate a (at `priority`) on a line both match:
	None        - never both, or a wins
	"conflict"  - equal footing: ERPNext refuses the line
	"shadowed"  - b wins quietly (higher priority, or a list-specific
	              Discount Percentage rule against a's list-less one)
	"""
	if cint(b.priority) < priority:
		return None
	if not ((cint(a.selling) and cint(b.selling)) or (cint(a.buying) and cint(b.buying))):
		return None
	if cint(a.apply_multiple_pricing_rules) and cint(b.apply_multiple_pricing_rules):
		return None
	if cint(b.coupon_code_based) or (b.condition or "").strip():
		return None
	if a.get("company") and b.company and a.get("company") != b.company:
		return None
	if a.get("currency") and b.currency and a.get("currency") != b.currency:
		return None
	if a.get("warehouse") and b.warehouse and not _tree_related("Warehouse", a.get("warehouse"), b.warehouse):
		return None
	if not _dates_overlap(a, b):
		return None
	if not _ranges_overlap(a.get("min_qty"), a.get("max_qty"), b.min_qty, b.max_qty):
		return None
	if not _ranges_overlap(a.get("min_amt"), a.get("max_amt"), b.min_amt, b.max_amt):
		return None

	# ERPNext keeps the highest priority first, then (only when every rule left
	# is a Discount Percentage) prefers the rule of the line's own price list.
	pa, pb = a.get("for_price_list") or "", b.get("for_price_list") or ""
	if pa and pb and pa != pb:
		return None
	shadowed = cint(b.priority) > priority
	both_pct = all(
		r.get("price_or_product_discount") == "Price" and r.get("rate_or_discount") == "Discount Percentage"
		for r in (a, b)
	)
	if not shadowed and pa != pb and both_pct:
		if pa:
			return None  # a is the list-specific one: a wins in its list
		shadowed = True
	if not _parties_overlap(a, b):
		return None
	return "shadowed" if shadowed else "conflict"


def describe_discount(rule):
	if rule.get("price_or_product_discount") == "Product":
		return _("Free item")
	rod = rule.get("rate_or_discount")
	if rod == "Discount Percentage":
		v = round(flt(rule.get("discount_percentage")), 4)
		return ("%g" % v) + "%"
	if rod == "Discount Amount":
		return _("{0} off").format(frappe.format_value(rule.get("discount_amount"), {"fieldtype": "Currency"}))
	if rod == "Rate":
		return _("Rate {0}").format(frappe.format_value(rule.get("rate"), {"fieldtype": "Currency"}))
	return rod or ""


def describe_parties(rule):
	af = rule.get("applicable_for") or ""
	if not af:
		return _("Everyone")
	return "{0}: {1}".format(_(af), rule.get(frappe.scrub(af)) or "?")


def find_conflicts(doc, priority=None, include_shadowed=False):
	"""Other enabled rules that would collide with `doc` on at least one shared
	item / item group / brand. `priority` overrides doc's own (used to find a
	priority that clears every conflict). `include_shadowed` also returns the
	rules that would quietly win over `doc` (kind "shadowed"); the save guard
	ignores those, the Pricing Rules Manager import reports them."""
	d = _as_dict(doc)
	if cint(d.disable) or d.apply_on not in APPLY_ON:
		return []
	if cint(d.coupon_code_based) or (d.condition or "").strip():
		return []
	table, field, child_dt = APPLY_ON[d.apply_on]
	has_uom = field == "item_code"

	mine = {}
	for row in d.get(table) or []:
		row = frappe._dict(row)
		if row.get(field):
			mine[row.get(field)] = (row.get("uom") or "") if has_uom else ""
	if not mine:
		return []

	if not d.get("valid_from"):
		d.valid_from = nowdate()
	prio = cint(d.priority) if priority is None else cint(priority)

	hits = frappe.db.sql(
		"""
		select c.parent, c.`{field}` as target, {uom} as uom
		from `tab{child_dt}` c
		inner join `tabPricing Rule` pr on pr.name = c.parent
		where c.parenttype = 'Pricing Rule' and c.`{field}` in %(targets)s
			and pr.name != %(me)s and pr.disable = 0 and pr.apply_on = %(apply_on)s
		""".format(field=field, child_dt=child_dt, uom="ifnull(c.uom, '')" if has_uom else "''"),
		{"targets": list(mine), "me": d.name or "", "apply_on": d.apply_on},
		as_dict=True,
	)
	if not hits:
		return []

	shared = {}
	for h in hits:
		mu = mine.get(h.target) or ""
		if mu and h.uom and mu != h.uom:
			continue
		shared.setdefault(h.parent, [])
		if h.target not in shared[h.parent]:
			shared[h.parent].append(h.target)
	if not shared:
		return []

	headers = frappe.get_all("Pricing Rule", filters={"name": ["in", list(shared)]}, fields=HEADER_FIELDS)
	totals = dict(frappe.db.sql(
		"select parent, count(*) from `tab{0}` where parent in %(n)s group by parent".format(child_dt),
		{"n": list(shared)},
	))

	out = []
	for b in headers:
		kind = _relation(d, b, prio)
		if not kind or (kind == "shadowed" and not include_shadowed):
			continue
		out.append({
			"kind": kind,
			"rule": b.name,
			"title": b.title,
			"priority": cint(b.priority),
			"discount": describe_discount(b),
			"parties": describe_parties(b),
			"valid_from": b.valid_from,
			"valid_upto": b.valid_upto,
			"price_list": b.for_price_list or "",
			"apply_on": b.apply_on,
			"shared": sorted(shared[b.name]),
			"total": cint(totals.get(b.name)),
			"promotional_scheme": b.promotional_scheme or "",
			"applicable_for": b.applicable_for or "",
			"party": b.get(frappe.scrub(b.applicable_for)) if b.applicable_for else "",
		})
	return sorted(out, key=lambda x: x["rule"])


def suggest_priority(doc, conflicts=None, include_shadowed=False):
	"""The lowest priority above the current one at which nothing collides (and,
	with include_shadowed, nothing wins over doc either), or None when even 20
	does not clear it."""
	d = _as_dict(doc)
	conflicts = conflicts if conflicts is not None else find_conflicts(d, include_shadowed=include_shadowed)
	if not conflicts:
		return None
	for p in range(cint(d.priority) + 1, MAX_PRIORITY + 1):
		if not find_conflicts(d, priority=p, include_shadowed=include_shadowed):
			return p
	return None


# ---------------------------------------------------------------------------
# server hook
# ---------------------------------------------------------------------------

def validate_no_conflicts(doc, method=None):
	"""doc_events: Pricing Rule.validate"""
	if doc.flags.ignore_pricing_rule_conflicts or cint(doc.disable):
		return
	conflicts = find_conflicts(doc)
	if not conflicts:
		return
	unit = {"Item Code": _("item"), "Item Group": _("item group"), "Brand": _("brand")}[doc.apply_on]
	lines = "".join(
		"<li><b>{0}</b> {1} ({2}, {3}, priority {4}): {5} {6}</li>".format(
			c["rule"], frappe.utils.escape_html(c["title"] or ""), c["discount"], c["parties"],
			c["priority"] or 0, unit, ", ".join(frappe.utils.escape_html(s) for s in c["shared"][:10])
			+ (" …" if len(c["shared"]) > 10 else ""),
		)
		for c in conflicts
	)
	frappe.throw(
		_("This rule overlaps {0} active pricing rule(s) with the same priority. "
			"Sales or purchases of the shared {1}s would stop with "
			"“Multiple Price Rules exists with same criteria”.").format(len(conflicts), unit)
		+ "<ul>{0}</ul>".format(lines)
		+ _("Open the rule in the Pricing Rule form to fix it: remove the shared {0}s from the other rule, "
			"disable the other rule, or give this rule a higher priority.").format(unit),
		PricingRuleConflictError,
		title=_("Pricing Rule Conflict"),
	)


# ---------------------------------------------------------------------------
# form API
# ---------------------------------------------------------------------------

@frappe.whitelist()
def check_conflicts(doc):
	"""Called by the Pricing Rule form before it saves. `doc` is the unsaved form."""
	if not frappe.has_permission("Pricing Rule", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	d = frappe._dict(frappe.parse_json(doc))
	conflicts = find_conflicts(d)
	return {
		"conflicts": conflicts,
		"suggested_priority": suggest_priority(d, conflicts) if conflicts else None,
	}


@frappe.whitelist()
def resolve_conflict(rule, action, targets=None):
	"""Apply one fix to the OTHER rule.

	remove  - take `targets` (the shared items/groups/brands) out of it
	disable - disable it
	"""
	doc = frappe.get_doc("Pricing Rule", rule)
	doc.check_permission("write")
	# Taking rows out or disabling can only reduce overlaps, so this save must not
	# be refused over some unrelated clash the old rule already had.
	doc.flags.ignore_pricing_rule_conflicts = True

	if action == "disable":
		doc.disable = 1
		doc.save()
		return {"rule": doc.name, "action": "disabled"}

	if action != "remove":
		frappe.throw(_("Unknown action {0}").format(action))
	if doc.promotional_scheme:
		frappe.throw(_("{0} is generated by Promotional Scheme {1}; change the scheme instead, "
			"or disable the rule.").format(doc.name, doc.promotional_scheme))
	if doc.apply_on not in APPLY_ON:
		frappe.throw(_("{0} applies on {1}; nothing to remove.").format(doc.name, doc.apply_on))
	targets = set(frappe.parse_json(targets) if isinstance(targets, str) else (targets or []))
	table, field, _child = APPLY_ON[doc.apply_on]
	keep = [r for r in doc.get(table) if r.get(field) not in targets]
	removed = len(doc.get(table)) - len(keep)
	if not keep:
		frappe.throw(_("That would leave {0} with nothing in it. Disable it instead.").format(doc.name))
	doc.set(table, keep)
	doc.save()
	return {"rule": doc.name, "action": "removed", "count": removed}
