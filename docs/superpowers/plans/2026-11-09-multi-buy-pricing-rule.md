# Multi-buy Pricing Rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pricing Rules can be "Buy X get Y at d%": pooled across eligible items, cheapest units discounted, applied on Quotation / Sales Order / Delivery Note / Sales Invoice (desk and POS Awesome), with a partial-return guard.

**Architecture:** Custom fields extend Pricing Rule; ERPNext's per-row lookup never sees multi-buy rules (wrapper + zero standard discount). A document-level engine (`multi_buy.py`) runs right before every `calculate_taxes_and_totals` during validate, works out each row's normal rule itself, pools eligible rows per multi-buy rule and writes blended row discounts + its own row fields. POS and desk forms show the server's `preview`; returns are checked against what the remaining basket earns.

**Tech Stack:** Frappe/ERPNext v13 fork (Python 3.8), desk JS, POS Awesome (Vue 2) fork, Playwright for browser checks.

**Spec:** `docs/superpowers/specs/2026-11-09-multi-buy-pricing-rule-design.md`

## Global Constraints

- Commit straight to master; every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. posawesome commits go to its own repo (master).
- No new dependency; production deploys with git pull + migrate + `bench restart`.
- Checks are standalone scripts run from `sites/`: `../env/bin/python ../apps/isoft_customization/isoft_customization/tests/<check>.py dev.isoft.ao`; everything they write is rolled back. Never `bench run-tests`.
- Never save or submit a Sales Invoice on dev. Server checks drive the validate path with `doc.run_method("before_validate"); doc.run_method("validate")` (no before_save: saft_xml submits non-POS invoices there). Quotations may be inserted and rolled back.
- Python edits need `bench restart` before browser checks; doctype_js changes need the DocType `modified` bumped (patch) for production.
- Field names (Pricing Rule): `isoft_multibuy` Check, `isoft_buy_qty` Int, `isoft_get_qty` Int, `isoft_multibuy_discount` Percent, `isoft_multibuy_max_units` Int, `isoft_allow_partial_return` Check. Row fields on Quotation Item, Sales Order Item, Delivery Note Item, Sales Invoice Item: `isoft_multibuy_rule` Link Pricing Rule (read_only), `isoft_multibuy_units` Float (read_only), `isoft_multibuy_pct` Percent (read_only) — none no_copy.
- Units are whole stock units: `floor(stock_qty)` per row; unit price = `price_list_rate / conversion_factor`.
- `D = floor(N / (X+Y)) × Y`, capped by max units (0 = no cap); cheapest units first, ties by row idx.
- Row `discount_percentage` = d × (discounted units × unit price) / (price_list_rate × qty), rounded to the field precision; capped at `Item.max_discount` when that is set.
- Desk docs with `ignore_pricing_rule = 1` are skipped; POS docs (`is_pos = 1`) are always evaluated. Returns are never re-evaluated.

## Review Focus

- **Row edited after multi-buy applied** (qty lowered so the basket no longer qualifies): the discount disappears and the row falls back to its normal rule — pinned in Task 2 (`requalify_after_qty_change`).
- **Same item on two rows** (scanned twice): units pool across both rows like any other items — Task 2 (`same_item_two_rows`).
- **Decimal stock qty** (0.5 kg, UOM factor 2.5): only whole units count, no crash — Task 2 (`fractional_units`).
- **Rule edited or disabled after a Quotation used it**: the quotation's saved rows keep their discount; a new SI from it carries it (mapped) — Task 2 (`mapped_rows_keep_result`).
- **POS cart with a manual discount on one eligible row**: that row is out of the basket, payment total equals server total — Task 5 (`pos_manual_row_out`).

---

### Task 1: Pricing Rule extension (fields, validation, lookup exclusion, conflicts)

**Files:**
- Create: `isoft_customization/multi_buy_rule.py` (custom fields, `validate_rule(doc)`, `setup_custom_fields()`, `MULTIBUY_LOOKUP` flag helper)
- Modify: `isoft_customization/overrides/pricing_rule.py` (call `multi_buy_rule.validate_rule` in `validate_mandatory`), `isoft_customization/item_group_and_brand.py` `_get_pricing_rules` (filter by flag), `isoft_customization/pricing_rule_conflicts.py` (describe/compare multi-buy), `isoft_customization/hooks.py` (after_migrate), `public/js/pricing_rule.js` (show/hide)
- Test: `isoft_customization/tests/multi_buy_rule_check.py`

**Interfaces:**
- Produces: `multi_buy_rule.multibuy_lookup()` context manager setting `frappe.flags.isoft_multibuy_lookup = True`; inside it `_get_pricing_rules` returns **only** rules with `isoft_multibuy = 1`, outside **never** returns them. `multi_buy_rule.FIELDS` tuple of the six field names.

- [ ] **Step 1: Write the failing check** — rule "MB test 2+1 30%" on an Item Group, priority 5: after insert `discount_percentage == 0 and rate == 0 and rate_or_discount == "Discount Percentage" and selling == 1`; `isoft_buy_qty = 0` → ValidationError; `isoft_multibuy_discount = 0` or `101` → ValidationError; `apply_on = "Transaction"` → ValidationError; ERPNext `get_item_details` for an item of that group returns no `pricing_rules` and discount 0; inside `multibuy_lookup()` `utils._get_pricing_rules("Item Group", args, {})` returns the rule; a normal 10% rule on the same group at priority 5 → conflict (`find_conflicts`), at priority 3 → none.
- [ ] **Step 2: Run, expect FAIL** (fields missing).
- [ ] **Step 3: Implement**; create fields via `setup_custom_fields()` run once on dev (and in after_migrate). d = 100 is allowed but `validate_rule` appends "(100%: verify with AGT)" to `rule_description` once.
- [ ] **Step 4: Run, expect PASS**; also `item_group_and_brand` behaviour unchanged: rerun its check if one exists (`tests/item_group_and_brand_check.py`), else note.
- [ ] **Step 5: Commit** `Multi-buy pricing rules: fields, validation, lookup exclusion`.

### Task 2: Engine + row fields + hooks

**Files:**
- Create: `isoft_customization/multi_buy.py`
- Modify: `multi_buy_rule.py` (row custom fields), `hooks.py` (doc_events for Quotation, Sales Order, Delivery Note, Sales Invoice: `before_validate: multi_buy.before_validate`, `validate: multi_buy.release` — appended after the existing entries, as lists)
- Test: `isoft_customization/tests/multi_buy_engine_check.py`

**Interfaces:**
- Consumes: `multi_buy_rule.multibuy_lookup()`.
- Produces:
  - `allocate(units, buy, get, max_units=0) -> dict` — `units` = list of `(row_key, unit_price, idx, count)`; returns `{row_key: discounted_count}`. Pure.
  - `apply(doc) -> dict` — mutates rows (discount_percentage, rate via ERPNext recalculation, `isoft_multibuy_*`), returns `{"rules": {rule: {"units": D, "amount": discount}}, "rows": {row.name or idx: {...}}}`. Does not call `calculate_taxes_and_totals` itself.
  - `before_validate(doc, method=None, *args, **kwargs)` wraps `doc.calculate_taxes_and_totals` to call `apply(doc)` first (same mechanism as `linked_document_prices.keep_prices`); `release(doc, method=None, *args, **kwargs)` removes the wrapper.
  - `@frappe.whitelist() preview(doc) -> dict` — `doc` JSON; builds an unsaved doc, runs `set_missing_values`, `apply`, `calculate_taxes_and_totals`; returns per-row `{idx, isoft_multibuy_rule, isoft_multibuy_units, isoft_multibuy_pct, discount_percentage, rate}` and totals. Checks read permission on the doctype.
  - `normal_rule_effect(doc, row) -> (rule_name or None, priority, expected_rate)` — via ERPNext `get_pricing_rule_for_item` on a copy of the row's args (multi-buy rules excluded by the wrapper).

- [ ] **Step 1: Write the failing checks.** `allocate`: `[(a,100,1,2),(b,60,2,2)]`, buy 1 get 1 → `{b:2}`; buy 2 get 1, 7 units → 2 discounted; max_units 1 caps; ties by idx. Doc-level (throwaway items + prices + rules created in the check, Quotation inserted & rolled back, SI via validate path only):
  `same_item_buy1get1_50` (one row qty 2 → 25%), `across_items_cheapest` (A 10000×2 + B 6000×2, buy1get1 50% → B row 50%, A 0), `buy2_get3rd`, `five_units_one_group`, `max_cap`, `min_qty_not_met`, `min_amt_not_met`, `expired`, `other_company`, `other_store`, `other_customer_group`, `uom_box_counts_stock_units`, `fractional_units`, `same_item_two_rows`, `higher_normal_rule_keeps_rows`, `lower_normal_rule_replaced_when_qualifying`, `fallback_to_normal_when_not_qualifying`, `fallback_to_next_multibuy`, `manual_discount_row_out`, `desk_ignore_pricing_rule_skips`, `pos_flag_still_applies`, `requalify_after_qty_change`, `mapped_rows_keep_result` (Quotation → SI via `make_sales_invoice` mapper, partial qty), `totals_consistent` (grand_total == Σ net + taxes, no margin), `item_max_discount_caps`, `kept_dn_price_rows_excluded` (keep-DN-prices switch on: SI rows with dn_detail stay out).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** in the order of the spec's engine steps 1–7 + 4b. Rules per row: `multibuy_lookup()` + the three `_get_pricing_rules` stages with args built like `get_item_details` (company, transaction_date/posting_date, customer, customer_group, territory, currency, price_list, warehouse, item_group, brand, transaction_type "selling"), then filter `valid_from/upto`, highest priority first. Evaluate rules in priority order; a rule's basket = its rows not yet claimed; non-qualifying → rows freed for the next rule. Row reset: rows previously carrying `isoft_multibuy_rule` get their normal-rule price back (`normal_rule_effect`) before evaluation.
- [ ] **Step 4: Run, expect PASS** (+ rerun `discount_limits_check.py`, `scan_barcode_uom_check.py server`, `quotation_tax_id_check.py` — unchanged).
- [ ] **Step 5: Commit** `Multi-buy pricing rules: document engine`.

### Task 3: Returns guard

**Files:** Modify `multi_buy.py` (`validate_return(doc)` called from `release` when `is_return`); Test `tests/multi_buy_return_check.py`.

**Interfaces:** `validate_return(doc) -> None` raises `frappe.ValidationError` with the list of discounted items to return too.

- [ ] **Step 1: Failing checks** — original invoice fixture written with `db_insert` (docstatus 1, rows with multi-buy fields; no hooks, rolled back), then return drafts via `make_sales_return` + validate path: `allowed_partial_ok`; `not_allowed_paying_unit_only_refused` (message names the discounted item); `not_allowed_both_ok`; `full_return_ok`; `second_partial_counts_first` (a submitted earlier return fixture also via db_insert).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** — kept discount = Σ over remaining units of (price_list_rate − rate) at the original rows; earned = `allocate` on the remaining units with the rule's X/Y/max and d; refuse when kept > earned + 0.01.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `Multi-buy pricing rules: partial return guard`.

### Task 4: Discount limits

**Files:** Modify `isoft_customization/discount_limits.py` (exempt `pct <= isoft_multibuy_pct + TOL` when `isoft_multibuy_rule`), posawesome `posawesome/posawesome/api/discounts.py` `check_discount_limits` (same exemption, field read with `.get`); Test `tests/multi_buy_limits_check.py`.

- [ ] **Step 1: Failing checks** — user limit 0%: multi-buy row passes `validate_discounts`; a manual 5% on another row still throws; POS cashier `max_discount_allowed` 10% with a 50% multi-buy row passes `check_discount_limits`; manual 15% on a non-multi-buy row still fails.
- [ ] **Step 2: Run, expect FAIL.** - [ ] **Step 3: Implement.** - [ ] **Step 4: PASS.**
- [ ] **Step 5: Commit** both repos (`Multi-buy: exempt from discount limits`).

### Task 5: POS Awesome

**Files:** Modify posawesome `posawesome/posawesome/api/posapp.py` (`_apply_manual_discount_override` skips rows with `isoft_multibuy_rule`; `update_invoice` calls `isoft_customization.multi_buy.apply` + `calculate_taxes_and_totals` last when that module is importable), `posawesome/public/js/posapp/components/pos/Invoice.vue` (debounced 300 ms `isoft_customization.multi_buy.preview` on items/qty/customer change; show row tag "Buy X get Y −d%" and the row discount; ignore a stale answer via a request counter), rebuild POS bundle per the repo's build recipe; Test `tests/browser_multi_buy.py --pos`.

- [ ] **Step 1: Failing browser check** (POS test recipe from memory posawesome-product-bundle-support; nothing submitted): add 2 eligible items → tag and discount shown; open payment → payment total == server `update_invoice` grand_total == cart total; `pos_manual_row_out`: manual 5% on one row → that row has no tag, totals still equal.
- [ ] **Step 2–4: RED → implement → GREEN.**
- [ ] **Step 5: Commit** posawesome + isoft_customization.

### Task 6: Desk form, Pricing Rule form, Manager badge, translations

**Files:** Create `public/js/multi_buy.js` (doctype_js for the four doctypes: debounced `preview` on items/qty/price list/customer/warehouse change → `frappe.model.set_value` discount per row, header indicator "Multi-buy −N"); modify `public/js/pricing_rule.js` (section toggle, hide discount/rate/margin/free item/mixed/cumulative when ticked); Pricing Rules Manager page (badge "Buy X get Y d%", rows open the standard form); patch `bump_multi_buy_meta` (DocType.modified for the four doctypes + Pricing Rule); `translations/pt.csv`; Test `tests/browser_multi_buy.py --desk`.

- [ ] **Step 1: Failing browser check** — new Quotation (not saved): add 2 eligible items → row discounts appear, indicator shows; Pricing Rule form: ticking Multi-buy hides the discount fields; Manager lists the rule with the badge.
- [ ] **Step 2–4: RED → implement → GREEN; rerun Tasks 1–5 checks.**
- [ ] **Step 5: Commit** `Multi-buy pricing rules: desk forms and Manager`; update memory `isoft-customization-app`.
