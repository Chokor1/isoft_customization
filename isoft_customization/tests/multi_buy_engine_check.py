"""Multi-buy engine check. Throwaway items/prices/rules + Quotations inserted inside one transaction,
Sales Invoices only through the validate path; everything rolled back.

Run from sites/: ../env/bin/python ../apps/isoft_customization/isoft_customization/tests/multi_buy_engine_check.py dev.isoft.ao
"""
import os
import sys

import frappe
from frappe.utils import flt, nowdate

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import multi_buy_fixtures as fx  # noqa: E402

frappe.init(site=sys.argv[1], sites_path=".")
frappe.connect()
frappe.set_user("Administrator")
fails = 0
CUSTOMER = "Abbass"
G, G2 = "MB Eng Group", "MB Eng Group 2"


def check(name, cond, detail=""):
	global fails
	print(("PASS" if cond else "FAIL"), name, "" if cond else str(detail)[:700])
	fails += not cond


def rows(doc):
	return {r.item_code + ("#%d" % r.idx): (flt(r.discount_percentage, 2), flt(r.isoft_multibuy_units), r.isoft_multibuy_rule or None, flt(r.rate, 2))
		for r in doc.items}


def lines(doc):
	"""[(qty, discount %)] in row order."""
	return [(flt(r.qty), flt(r.discount_percentage, 2)) for r in doc.items]


def by_code(doc, code):
	return [r for r in doc.items if r.item_code == code]


def quotation(lines, **hdr):
	d = frappe.get_doc(dict({"doctype": "Quotation", "quotation_to": "Customer", "party_name": CUSTOMER, "company": fx.COMPANY,
		"transaction_date": nowdate(), "selling_price_list": fx.PL, "currency": fx.CURRENCY, "conversion_rate": 1,
		"plc_conversion_rate": 1, "order_type": "Sales", "taxes": [dict(fx.IVA_ROW)],
		"items": [dict({"item_code": c, "qty": q}, **(extra[0] if extra else {})) for c, q, *extra in lines]}, **hdr))
	d.insert()
	return d


def invoice(lines, **hdr):
	"""Sales Invoice through the validate path only (never saved)."""
	d = frappe.get_doc(dict({"doctype": "Sales Invoice", "customer": CUSTOMER, "company": fx.COMPANY, "posting_date": nowdate(),
		"due_date": nowdate(), "selling_price_list": fx.PL, "currency": fx.CURRENCY, "conversion_rate": 1, "plc_conversion_rate": 1,
		"taxes": [dict(fx.IVA_ROW)], "items": [dict({"item_code": c, "qty": q}, **(extra[0] if extra else {})) for c, q, *extra in lines]}, **hdr))
	d._action = "save"
	d.set_missing_values()
	d.run_method("before_validate")
	d.run_method("validate")
	return d


savepoint_n = [0]


def isolated(fn):
	"""Each case in its own savepoint so rules from one don't leak into the next."""
	savepoint_n[0] += 1
	sp = "mb_case_%d" % savepoint_n[0]
	frappe.db.savepoint(sp)
	try:
		fn()
	except Exception as e:  # noqa: BLE001
		import traceback

		traceback.print_exc()
		check(fn.__name__ + "_no_exception", False, repr(e))
	finally:
		frappe.db.rollback(save_point=sp)


try:
	fx.item_group(G)
	fx.item_group(G2)
	fx.item("MB-E-A", G, 10000)
	fx.item("MB-E-B", G, 6000)
	fx.item("MB-E-C", G, 3000)
	fx.item("MB-E-BOX", G, 2000, uoms=[("Box", 5)])
	fx.item("MB-E-KG", G, 1000, stock_uom="Kg")
	fx.item("MB-E-MAX", G, 4000, max_discount=20)
	fx.item("MB-E-G2", G2, 5000)
	from isoft_customization import multi_buy

	# ---- pure allocation
	a = multi_buy.allocate([("a", 100, 1, 2), ("b", 60, 2, 2)], 1, 1)
	check("allocate_cheapest", a == {"b": 2}, a)
	a = multi_buy.allocate([("a", 100, 1, 7)], 2, 1)
	check("allocate_seven_units_buy2get1", a == {"a": 2}, a)
	a = multi_buy.allocate([("a", 100, 1, 4)], 1, 1, max_units=1)
	check("allocate_max_cap", a == {"a": 1}, a)
	a = multi_buy.allocate([("a", 50, 2, 1), ("b", 50, 1, 1)], 1, 1)
	check("allocate_ties_by_idx", a == {"b": 1}, a)

	def same_item_buy1get1_50():
		fx.rule("MB 1+1", G, 5).insert()
		d = quotation([("MB-E-A", 2)])
		# split like the POS (user 2026-11-09): one line at the offer's discount, one at full price
		check("same_item_buy1get1_50", lines(d) == [(1, 50), (1, 0)] and d.items[0].isoft_multibuy_units == 1
			and flt(d.items[0].rate) == 5000 and flt(d.items[1].rate) == 10000, rows(d))

	def across_items_cheapest():
		fx.rule("MB 1+1", G, 5).insert()
		d = quotation([("MB-E-A", 2), ("MB-E-B", 2)])
		check("across_items_cheapest", rows(d)["MB-E-A#1"][:2] == (0, 0) and rows(d)["MB-E-B#2"][:2] == (50, 2), rows(d))

	def buy2_get3rd():
		fx.rule("MB 2+1", G, 5, isoft_buy_qty=2, isoft_get_qty=1, isoft_multibuy_discount=30).insert()
		d = quotation([("MB-E-A", 1), ("MB-E-B", 1), ("MB-E-C", 1)])
		check("buy2_get3rd", rows(d)["MB-E-C#3"][:2] == (30, 1) and rows(d)["MB-E-A#1"][:2] == (0, 0), rows(d))

	def five_units_one_group():
		fx.rule("MB 2+1", G, 5, isoft_buy_qty=2, isoft_get_qty=1, isoft_multibuy_discount=30).insert()
		d = quotation([("MB-E-C", 5)])
		check("five_units_one_group", lines(d) == [(1, 30), (4, 0)], rows(d))

	def max_cap():
		fx.rule("MB 1+1 max1", G, 5, isoft_multibuy_max_units=1).insert()
		d = quotation([("MB-E-C", 4)])
		check("max_cap", lines(d) == [(1, 50), (3, 0)], rows(d))

	def min_qty_not_met():
		fx.rule("MB 1+1 min5", G, 5, min_qty=5).insert()
		d = quotation([("MB-E-C", 4)])
		check("min_qty_not_met", not d.items[0].isoft_multibuy_rule and flt(d.items[0].discount_percentage) == 0, rows(d))

	def min_amt_not_met():
		fx.rule("MB 1+1 min amt", G, 5, min_amt=50000).insert()
		d = quotation([("MB-E-C", 4)])
		check("min_amt_not_met", not d.items[0].isoft_multibuy_rule, rows(d))

	def expired():
		fx.rule("MB 1+1 old", G, 5, valid_from="2020-01-01", valid_upto="2020-12-31").insert()
		d = quotation([("MB-E-C", 2)])
		check("expired", not d.items[0].isoft_multibuy_rule, rows(d))

	def other_company():
		fx.rule("MB 1+1 NDA", G, 5, company="Nova Distribuição Angola").insert()
		d = quotation([("MB-E-C", 2)])
		check("other_company", not d.items[0].isoft_multibuy_rule, rows(d))

	def other_store():
		fx.rule("MB 1+1 store", G, 5, warehouse="01 - Loja Alvalade - ITEC").insert()
		d = quotation([("MB-E-C", 2, {"warehouse": "07 - Maculusso Armazem - ITEC"})])
		check("other_store", not d.items[0].isoft_multibuy_rule, rows(d))
		d2 = quotation([("MB-E-C", 2, {"warehouse": "01 - Loja Alvalade - ITEC"})])
		check("same_store", d2.items[0].isoft_multibuy_rule, rows(d2))

	def other_customer_group():
		fx.rule("MB 1+1 gov", G, 5, customer_group="Government").insert()
		d = quotation([("MB-E-C", 2)])
		check("other_customer_group", not d.items[0].isoft_multibuy_rule, rows(d))

	def uom_box_counts_stock_units():
		fx.rule("MB 1+1", G, 5).insert()
		d = quotation([("MB-E-BOX", 1, {"uom": "Box"})])  # 5 stock units at 2000 -> 2 discounted
		check("uom_box_counts_stock_units", d.items[0].isoft_multibuy_units == 2 and flt(d.items[0].discount_percentage, 2) == 20, rows(d))

	def fractional_units():
		fx.rule("MB 1+1", G, 5).insert()
		d = quotation([("MB-E-KG", 2.5)])
		check("fractional_units", lines(d) == [(1, 50), (1.5, 0)], rows(d))

	def same_item_two_rows():
		fx.rule("MB 1+1", G, 5).insert()
		d = quotation([("MB-E-C", 1), ("MB-E-C", 1)])
		check("same_item_two_rows", sum(r.isoft_multibuy_units for r in d.items) == 1, rows(d))

	def higher_normal_rule_keeps_rows():
		fx.rule("MB 1+1", G, 3).insert()
		fx.rule("Normal 10", G, 5, multibuy=False, discount_percentage=10).insert()
		d = quotation([("MB-E-C", 2)])
		check("higher_normal_rule_keeps_rows", not d.items[0].isoft_multibuy_rule and flt(d.items[0].discount_percentage) == 10, rows(d))

	def lower_normal_rule_replaced_when_qualifying():
		fx.rule("MB 1+1", G, 5).insert()
		fx.rule("Normal 10", G, 3, multibuy=False, discount_percentage=10).insert()
		d = quotation([("MB-E-C", 2)])
		r = d.items[0]
		check("lower_normal_rule_replaced_when_qualifying", r.isoft_multibuy_rule and lines(d) == [(1, 50), (1, 0)]
			and not any((x.pricing_rules or "").strip("[]\" \n") for x in d.items), rows(d))

	def fallback_to_normal_when_not_qualifying():
		fx.rule("MB 1+1", G, 5).insert()
		fx.rule("Normal 10", G, 3, multibuy=False, discount_percentage=10).insert()
		d = quotation([("MB-E-C", 1)])
		check("fallback_to_normal_when_not_qualifying", not d.items[0].isoft_multibuy_rule and flt(d.items[0].discount_percentage) == 10, rows(d))

	def fallback_to_next_multibuy():
		fx.rule("MB 2+1 top", G, 6, isoft_buy_qty=2, isoft_get_qty=1, isoft_multibuy_discount=30).insert()
		fx.rule("MB 1+1 next", G, 4).insert()
		d = quotation([("MB-E-C", 2)])
		check("fallback_to_next_multibuy", d.items[0].isoft_multibuy_rule and frappe.db.get_value("Pricing Rule", d.items[0].isoft_multibuy_rule, "title") == "MB 1+1 next", rows(d))

	def manual_discount_row_out():
		fx.rule("MB 1+1", G, 5).insert()
		d = quotation([("MB-E-A", 1, {"discount_percentage": 5}), ("MB-E-C", 1)])
		check("manual_discount_row_out", not d.items[0].isoft_multibuy_rule and flt(d.items[0].discount_percentage) == 5
			and not d.items[1].isoft_multibuy_rule, rows(d))

	def desk_ignore_pricing_rule_skips():
		fx.rule("MB 1+1", G, 5).insert()
		d = quotation([("MB-E-C", 2)], ignore_pricing_rule=1)
		check("desk_ignore_pricing_rule_skips", not d.items[0].isoft_multibuy_rule, rows(d))

	def pos_flag_still_applies():
		fx.rule("MB 1+1", G, 5).insert()
		d = invoice([("MB-E-C", 2)], is_pos=0, ignore_pricing_rule=1)
		check("si_desk_ignore_skips", not d.items[0].isoft_multibuy_rule, rows(d))
		from isoft_customization.multi_buy import apply

		d2 = frappe.get_doc({"doctype": "Sales Invoice", "customer": CUSTOMER, "company": fx.COMPANY, "is_pos": 1, "ignore_pricing_rule": 1,
			"selling_price_list": fx.PL, "currency": fx.CURRENCY, "conversion_rate": 1, "plc_conversion_rate": 1,
			"posting_date": nowdate(), "items": [{"item_code": "MB-E-C", "qty": 2, "price_list_rate": 3000, "rate": 3000, "uom": "Nos",
			"conversion_factor": 1, "stock_qty": 2}]})
		apply(d2)
		check("pos_flag_still_applies", d2.items[0].isoft_multibuy_rule and flt(d2.items[0].discount_percentage, 2) == 25, rows(d2))

	def requalify_after_qty_change():
		fx.rule("MB 1+1", G, 5).insert()
		d = quotation([("MB-E-C", 2)])  # -> 1 @50% + 1 @0%
		d.remove(d.items[1])
		d.save()
		check("requalify_after_qty_change", not d.items[0].isoft_multibuy_rule and flt(d.items[0].discount_percentage) == 0 and flt(d.items[0].rate) == 3000, rows(d))

	def mapped_rows_keep_result():
		rule = fx.rule("MB 2+1", G, 5, isoft_buy_qty=2, isoft_get_qty=1, isoft_multibuy_discount=30).insert()
		q = quotation([("MB-E-C", 3)])
		q.db_set("docstatus", 1)  # fixture: mapping needs a submitted quotation (no hooks, rolled back)
		for it in q.items:
			it.db_set("docstatus", 1)
		frappe.db.set_value("Pricing Rule", rule.name, "disable", 1)  # the offer ends after the quotation
		from erpnext.selling.doctype.quotation.quotation import make_sales_order

		so = make_sales_order(q.name)
		so.delivery_date = nowdate()
		check("mapped_quotation_split", lines(q) == [(1, 30), (2, 0)], rows(q))
		so.items[1].qty = 1  # partial: only part of the full-price units
		for it in so.items:
			it.delivery_date = nowdate()
		so.insert()
		check("mapped_rows_keep_result", [x.isoft_multibuy_rule for x in so.items] == [rule.name, rule.name] and lines(so) == [(1, 30), (1, 0)], rows(so))

	def totals_consistent():
		fx.rule("MB 1+1", G, 5).insert()
		d = quotation([("MB-E-A", 1), ("MB-E-B", 3), ("MB-E-C", 1)])
		net = sum(flt(r.net_amount, 2) for r in d.items)
		margins = [r.margin_rate_or_amount for r in d.items if flt(r.margin_rate_or_amount)]
		check("totals_consistent", abs(net - flt(d.net_total, 2)) < 0.02 and abs(flt(d.grand_total) - flt(d.net_total) - flt(d.total_taxes_and_charges)) < 0.02 and not margins,
			(net, d.net_total, d.grand_total, d.total_taxes_and_charges, margins))
		disc = sum((flt(r.price_list_rate) - flt(r.rate)) * r.qty for r in d.items)
		# 5 units -> 2 discounted: the two cheapest = C 3000 + B 6000 at 50% = 4500
		check("discount_amount_exact", abs(disc - 4500) <= 0.05, (disc, rows(d)))

	def item_max_discount_caps():
		fx.rule("MB 1+1", G, 5, isoft_multibuy_discount=100).insert()
		d = quotation([("MB-E-MAX", 2)])
		check("item_max_discount_caps", lines(d) == [(1, 20), (1, 0)] and d.items[0].isoft_multibuy_rule, rows(d))

	def b2b_matches_pos_cents():
		# the user's case (FT FT3726S2554N/1394 vs FR FR3726S1246N/124): 6 x 4117.66, buy 2 get 1 at 5%
		fx.item("MB-E-CENT", G, 4117.66)
		fx.rule("MB 2+1 5", G, 5, isoft_buy_qty=2, isoft_get_qty=1, isoft_multibuy_discount=5).insert()
		d = quotation([("MB-E-CENT", 6)])
		check("b2b_matches_pos_cents", lines(d) == [(2, 5), (4, 0)] and flt(d.net_total, 2) == 24294.20, (lines(d), d.net_total))
		si = invoice([("MB-E-CENT", 6)])
		check("b2b_invoice_matches_pos_cents", lines(si) == [(2, 5), (4, 0)] and flt(si.net_total, 2) == 24294.20, (lines(si), si.net_total))

	def merge_back_and_grow():
		fx.rule("MB 1+1", G, 5).insert()
		d = quotation([("MB-E-C", 2)])  # 1 @50 + 1 @0
		d.items[1].qty = 3  # 4 units now -> 2 @50 + 2 @0
		d.save()
		check("split_grows", lines(d) == [(2, 50), (2, 0)], rows(d))
		d.items[1].qty = 0.0001
		d.remove(d.items[1])
		d.items[0].qty = 1  # one unit left -> one line, no offer
		d.save()
		check("split_merges_back", lines(d) == [(1, 0)] and not d.items[0].isoft_multibuy_rule, rows(d))

	def serial_rows_not_split():
		from isoft_customization.multi_buy import _splittable

		check("serial_rows_not_split", not _splittable(frappe._dict(serial_no="SN1\nSN2", item_code="MB-E-A")) and _splittable(frappe._dict(item_code="MB-E-A")))

	def submit_keeps_offer():  # review C1
		fx.rule("MB 1+1 p1", G, 1).insert()
		fx.rule("Normal 15 p0", G, "", multibuy=False, discount_percentage=15).insert()
		d = quotation([("MB-E-C", 2)])
		before = lines(d)
		d.submit()
		check("submit_keeps_offer", before == [(1, 50), (1, 0)] and lines(d) == before, (before, lines(d)))

	def saved_lines_keep_identity():  # review C2
		fx.rule("MB 1+1", G, 5).insert()
		d = quotation([("MB-E-C", 2)])
		names = [(r.name, flt(r.qty), flt(r.discount_percentage, 2)) for r in d.items]
		d.save()
		again = [(r.name, flt(r.qty), flt(r.discount_percentage, 2)) for r in d.items]
		check("resave_keeps_row_names", names == again, (names, again))
		import json

		pv = multi_buy.preview(json.dumps(d.as_dict(), default=str))
		got = [(x["name"], x["qty"], round(x["discount_percentage"], 2)) for x in pv["rows"]]
		check("preview_of_saved_doc_unchanged", got == names, (got, names))

	def carried_rows_capped():  # review I1
		rule = fx.rule("MB 1+1", G, 5).insert()
		q = quotation([("MB-E-C", 2)])  # 1 @50 + 1 @0
		q.db_set("docstatus", 1)
		for it in q.items:
			it.db_set("docstatus", 1)
		from erpnext.selling.doctype.quotation.quotation import make_sales_order

		so = make_sales_order(q.name)
		so.delivery_date = nowdate()
		for it in so.items:
			it.delivery_date = nowdate()
		disc_row = [r for r in so.items if flt(r.discount_percentage)][0]
		disc_row.qty = 10  # raise the discounted line
		so.append("items", dict(disc_row.as_dict(), name=None, idx=None, qty=1))  # and duplicate it
		so.insert()
		total_disc = sum((flt(r.price_list_rate) - flt(r.rate)) * flt(r.qty) for r in so.items)
		check("carried_rows_capped", abs(total_disc - 1500) < 0.05, (total_disc, rows(so)))
		from isoft_customization.multi_buy import _carried

		si_row = frappe._dict(prevdoc_docname=q.name, item_code="MB-E-C", isoft_multibuy_rule=rule.name)
		check("si_from_quotation_carried", _carried(frappe._dict(doctype="Sales Invoice"), si_row))  # review I3

	def dn_from_si_links_kept_apart():  # review I4
		from isoft_customization.multi_buy import LINE_KEY, SOURCE_LINKS

		check("dn_from_si_links_kept_apart", "si_detail" in LINE_KEY and "against_sales_invoice" in LINE_KEY
			and ("si_detail", "Sales Invoice Item") in SOURCE_LINKS)

	def early_exit_without_rules():  # review I5
		from isoft_customization import multi_buy as mb

		calls = []
		orig_normal, orig_any = mb._normal_effect, mb._any_multibuy
		mb._normal_effect = lambda *a, **k: calls.append(1) or orig_normal(*a, **k)
		mb._any_multibuy = lambda doc: False
		try:
			d = quotation([("MB-E-C", 2)])
		finally:
			mb._normal_effect, mb._any_multibuy = orig_normal, orig_any
		check("early_exit_without_rules", not calls and not d.items[0].isoft_multibuy_rule, calls)

	def no_split_when_duplicates_disallowed():  # review I8
		fx.rule("MB 1+1", G, 5).insert()
		frappe.db.set_value("Selling Settings", None, "allow_multiple_items", 0)
		frappe.clear_document_cache("Selling Settings", "Selling Settings")
		try:
			d = quotation([("MB-E-C", 2)])
			check("no_split_when_duplicates_disallowed", lines(d) == [(2, 25)], lines(d))
		finally:
			frappe.db.set_value("Selling Settings", None, "allow_multiple_items", 1)
			frappe.clear_document_cache("Selling Settings", "Selling Settings")

	def kept_dn_price_rows_excluded():
		from isoft_customization.multi_buy import _kept_by_switch

		row = frappe._dict(dn_detail="x")
		frappe.db.set_value("Selling Settings", None, "isoft_keep_delivery_note_prices", 1)
		frappe.clear_document_cache("Selling Settings", "Selling Settings")
		check("kept_dn_price_rows_excluded", _kept_by_switch(frappe._dict(doctype="Sales Invoice"), row) and not _kept_by_switch(frappe._dict(doctype="Quotation"), row))
		frappe.db.set_value("Selling Settings", None, "isoft_keep_delivery_note_prices", 0)
		frappe.clear_document_cache("Selling Settings", "Selling Settings")

	def preview_matches_save():
		fx.rule("MB 1+1", G, 5).insert()
		import json

		pv = multi_buy.preview(json.dumps({"doctype": "Quotation", "quotation_to": "Customer", "party_name": CUSTOMER, "company": fx.COMPANY,
			"transaction_date": nowdate(), "selling_price_list": fx.PL, "currency": fx.CURRENCY, "conversion_rate": 1, "plc_conversion_rate": 1,
			"taxes": [dict(fx.IVA_ROW)], "items": [{"item_code": "MB-E-A", "qty": 1}, {"item_code": "MB-E-C", "qty": 1}]}))
		d = quotation([("MB-E-A", 1), ("MB-E-C", 1)])
		check("preview_matches_save", [round(x["discount_percentage"], 2) for x in pv["rows"]] == [flt(r.discount_percentage, 2) for r in d.items]
			and abs(pv["grand_total"] - flt(d.grand_total)) < 0.01, (pv, rows(d)))

	for case in (same_item_buy1get1_50, across_items_cheapest, buy2_get3rd, five_units_one_group, max_cap, min_qty_not_met,
			min_amt_not_met, expired, other_company, other_store, other_customer_group, uom_box_counts_stock_units, fractional_units,
			same_item_two_rows, higher_normal_rule_keeps_rows, lower_normal_rule_replaced_when_qualifying,
			fallback_to_normal_when_not_qualifying, fallback_to_next_multibuy, manual_discount_row_out, desk_ignore_pricing_rule_skips,
			pos_flag_still_applies, requalify_after_qty_change, mapped_rows_keep_result, totals_consistent, item_max_discount_caps,
			kept_dn_price_rows_excluded, preview_matches_save, b2b_matches_pos_cents, merge_back_and_grow, serial_rows_not_split,
			submit_keeps_offer, saved_lines_keep_identity, carried_rows_capped, dn_from_si_links_kept_apart, early_exit_without_rules,
			no_split_when_duplicates_disallowed):
		isolated(case)
except Exception as e:  # noqa: BLE001
	import traceback

	traceback.print_exc()
	check("no_exception", False, repr(e))
finally:
	frappe.db.rollback()
	frappe.clear_document_cache("Selling Settings", "Selling Settings")
	frappe.destroy()

print("FAILURES:", fails)
sys.exit(1 if fails else 0)
