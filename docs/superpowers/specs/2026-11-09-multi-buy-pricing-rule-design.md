# Multi-buy Pricing Rule (Buy X get Y at d%) — design

Date: 2026-11-09 · App: isoft_customization (+ a small change in the posawesome fork) · Approach A, chosen by the user

## Intent

A customer wants retail offers of the kind "buy 2, get the 3rd at 30% off". The offer works
**across items**: the basket's eligible units are pooled and the **cheapest** units get the
discount. It must work on desk sales documents and in POS Awesome, be managed like a normal
Pricing Rule (same conditions, same priority), and must not hand out a discount the basket
did not earn, including after a return.

## What the user decided

- Offer shape is dynamic: **Buy X, get Y at d%** (examples: buy 1 get 1 at 50%, buy 2 get the 3rd at 30%).
- **Across items:** eligible = the rule's Item Codes / Item Groups / Brands / Item Group and Brand,
  exactly as a Pricing Rule's Apply On.
- Conditions, priority and where it applies (all selling documents and POS) behave like a
  normal Pricing Rule; on the document the discount shows like a pricing-rule discount (a
  per-row discount %).
- **"Allow partial return"** per rule. Off: a return may not leave the customer holding a
  discount the remaining basket no longer earns ("return the discounted item too"). On: any
  return is accepted.
- Build it as an **extension of Pricing Rule** (approach A), not a separate document.

## Goals

1. A Pricing Rule can be marked **Multi-buy**, with `Buy` (X ≥ 1), `Get` (Y ≥ 1), `Discount %`
   (0 < d ≤ 100), optional `Max discounted units per invoice`, `Allow partial return`.
2. Applied on **Quotation, Sales Order, Delivery Note, Sales Invoice** (desk and POS Awesome).
3. Groups repeat: discounted units = `floor(N / (X+Y)) × Y`, capped by the max (N = eligible units).
4. The discounted units are the **cheapest eligible units in the whole basket** (unit price =
   price list rate per stock unit), ties broken by row order.
5. Each row gets a blended `discount_percentage` = discount on its units / (price list rate × qty);
   the row stores which rule and how many of its units are discounted.
6. Returns honour "Allow partial return".
7. POS: the total on the payment screen is the server's; the cart shows the same discounts
   before payment.

## Non-goals

- Free-item (extra row) promotions, coupon codes, buying side.
- Stacking a multi-buy discount on top of another pricing-rule discount on the same row.
- POS offline mode.
- Changing ERPNext or frappe core files.

## Anti-goals (a failure even if it "works")

- **ERPNext applying the multi-buy % to every unit of a row.** Guarded twice: (a) ERPNext's own
  rule lookup skips multi-buy rules; (b) the multi-buy % lives in its own field and the standard
  `discount_percentage` / `rate` / `discount_amount` of a multi-buy rule are forced to 0 on save,
  so any unwrapped path that still matched it would apply nothing.
- A discount the basket did not earn (too few units, below the minimum, expired, wrong
  company/store/customer group, or kept after a forbidden partial return).
- A POS payment total different from the invoice the server saves.
- Anything the AGT rejects: no grand-total discount, no item margin (see memory agt-pricing-constraints).

## Constraints

- Frappe/ERPNext v13 fork, Python 3.8; commits straight to master; production deploys with
  git pull + migrate + restart; no new dependencies.
- The Pricing Rule extension follows the existing pattern of Apply On "Item Group and Brand"
  (`item_group_and_brand.py`: wrappers installed from `before_request`, `before_job` and the
  package `__init__`; `overrides/pricing_rule.py` IsoftPricingRule; conflict guard
  `pricing_rule_conflicts.py`; form JS `public/js/pricing_rule.js`).
- ERPNext validate re-runs any rule listed in a row's `pricing_rules`. Multi-buy therefore
  **never** writes its rule into `pricing_rules`; it uses its own row fields.
- POS Awesome sends `ignore_pricing_rule = 1` and clears `pricing_rules` in
  `update_invoice` / `_apply_manual_discount_override`; `update_invoice` returns the
  server-computed document that the payment screen uses.
- Never save or submit transactions on dev in tests (roll back); never `bench run-tests`.

## Approaches considered

- **A. Extend Pricing Rule (chosen).** One place to manage offers, same conditions and
  priority scale, reuses the proven lookup-wrapper pattern; the zero-standard-discount safety
  net covers paths the wrapper misses. Cost: hide irrelevant fields, teach the conflict guard and
  the Pricing Rules Manager about multi-buy.
- B. Separate "Multi-buy Promotion" DocType: fully isolated, but duplicates every condition field,
  and priority must be compared across two doctypes in two screens. Rejected by the user.
- (Ruled out) Standard ERPNext free-item / recursive / mixed-condition rules and POS Offers:
  none can discount only part of the units or pick the cheapest; v13 "recursive" multiplies by
  total qty; invoice-level discounts are rejected by the AGT.

## The design

### Pricing Rule fields (Custom Fields, created in after_migrate)
Section "Multi-buy (Buy X get Y)", shown for selling rules:
`isoft_multibuy` (Check), `isoft_buy_qty` (Int, ≥1), `isoft_get_qty` (Int, ≥1),
`isoft_multibuy_discount` (Percent, 0<d≤100), `isoft_multibuy_max_units` (Int, 0 = no cap),
`isoft_allow_partial_return` (Check, default 0).
When `isoft_multibuy` is set, validation (IsoftPricingRule) forces: selling=1, buying=0,
price_or_product_discount="Price", rate_or_discount="Discount Percentage",
discount_percentage=0, discount_amount=0, rate=0, margin 0, no free item, apply_on ≠ Transaction,
mixed_conditions irrelevant (always pooled), is_cumulative 0. The form hides the
discount/rate/margin/free-item/mixed/cumulative fields while it is ticked.
Kept as-is from Pricing Rule: Apply On (incl. Item Group and Brand) + its tables, company,
warehouse, applicable_for (customer / customer group / territory …), valid_from/upto,
min_qty, min_amt, max_qty, max_amt, priority, disable, title, currency, for_price_list.

### ERPNext lookup excludes multi-buy rules
The `_get_pricing_rules` wrapper (item_group_and_brand.py's mechanism, extended — or a sibling
wrapper installed the same way) drops rules with `isoft_multibuy = 1` from what ERPNext
matches per row. Plus the zero-standard-discount safety net above.

### Engine `isoft_customization/multi_buy.py`
`apply(doc)` — for a non-return Quotation / Sales Order / Delivery Note / Sales Invoice:
1. Skip when the doc is a return, or a desk doc with `ignore_pricing_rule = 1`. POS documents
   (`is_pos = 1`) are evaluated even though POS Awesome sets `ignore_pricing_rule` (its own
   convention for "keep my prices").
2. Clear previous multi-buy results on every row (row fields below; the row's
   `discount_percentage` is reset to 0 only on rows that had a multi-buy result).
3. Candidate rules: enabled multi-buy rules valid on the doc date for the doc's company,
   currency, selling price list (when `for_price_list` is set), customer / customer group /
   territory (root groups count as everyone, as in Barcode Label Studio), and warehouse (row
   warehouse in the rule warehouse's subtree).
4. Each row belongs to at most one rule: the highest-priority matching multi-buy rule.
   - **Normal pricing rules** are worked out by the engine itself for each row (ERPNext's own
     lookup, `get_pricing_rule_for_item` semantics with the doc's context), never read from the
     row's `pricing_rules` — POS never sends them. Higher or equal priority than the multi-buy
     rule → the row stays out of the basket and keeps its normal discount.
   - **Other discounts** on a row (typed on the desk, the cashier's line discount, POS customer
     discount, POS Offer, barcode discount) — i.e. a row discount that its normal rule does not
     explain (±0.01%) → the row stays out of the basket and keeps that discount. No stacking.
     (Builder call, review Q1.)
   - Rows with `is_free_item`, zero qty, a line price kept by the linked-document-prices switch,
     or **carried from a source document** (see "Mapped documents") are excluded from the basket.
4b. **Fallback (review Q2), pricing-rule semantics:** a multi-buy rule whose basket does not qualify
   (fewer than X+Y units, min_qty/min_amt/max not met) is not applicable: its rows are offered to
   the next multi-buy rule by priority, and failing that keep their normal-rule discount. When the
   basket qualifies, all its rows are priced by multi-buy only: discounted units at d%, the paying
   units at the price list rate (their normal discount does not stack). (Builder call.)
5. Per rule: units are stock units (`stock_qty`), unit price = `price_list_rate / conversion_factor`.
   Check min_qty / max_qty on N and min_amt / max_amt on Σ price_list_rate × qty (before tax,
   before any discount) — pricing-rule semantics. If not met: no discount.
6. `D = floor(N / (X+Y)) × Y`, capped by max units. Expand units, sort by unit price ascending
   (row order breaks ties), mark the first D units.
7. Per row: `isoft_multibuy_rule`, `isoft_multibuy_units` (discounted stock units),
   `discount_percentage = d × discounted_units_value / (price_list_rate × qty)` rounded to the
   field precision, `margin_*` 0; then `doc.calculate_taxes_and_totals()`.
**When it runs (review flaw fix):** `before_validate` wraps the document's
`calculate_taxes_and_totals` (the `linked_document_prices.keep_prices` mechanism) so the engine runs
right before every totals computation inside the controller's validate — after
set_missing_item_details, before the payment schedule, in-words, advances and the Angola
withholdings — and `validate` releases the wrapper. A plain validate hook would be too late
(saft_xml submits non-POS invoices inside before_save). Exposed as whitelisted `preview(doc_json)`
returning per-row results for the desk/POS displays (no save).

### Mapped documents (review Q3)
Rows made from another document (`quotation_item`, `so_detail`, `dn_detail`, `prevdoc_docname`
from a Quotation) that arrive with a multi-buy result **keep it** (rule, units and discount are
copied by the mapper, the fields are not no_copy) and are not re-evaluated: the source document
is the agreement, so partial delivery/billing (an order of 3 invoiced as 2 + 1) and an offer that
expires in between do not change the price — consistent with POS Customer Orders ("the order's
price and discount") and the keep-prices switches. New rows added on the target document form
their own basket. (Builder call.)

### Discount caps (review Q4)
- isoft_customization `discount_limits` and POS Awesome `api/discounts.check_discount_limits`
  (cashier `max_discount_allowed`): the multi-buy part of a row's discount is exempt.
- ERPNext core `Item.max_discount` (validate_max_discount): the row's multi-buy % is **capped at the
  item's max_discount**; the core check stays untouched. (Builder call; dev has no item with it.)

### Row fields (Custom Fields on the four item tables)
`isoft_multibuy_rule` (Link Pricing Rule, read-only, no_copy 0 so returns carry it),
`isoft_multibuy_units` (Float, read-only). Shown in the grid's detail view only.

### Returns (`is_return = 1`)
No re-application. If any returned row carries `isoft_multibuy_rule` and the rule's
`isoft_allow_partial_return` is off: rebuild the original invoice's basket minus everything
returned so far (submitted returns + this draft), re-run step 5–6 on what remains, and compare
**discount kept** (original discount on remaining units, at the original rows' blended rates) with
**discount earned** by the remaining basket. Kept > earned (+0.01 tolerance) → refuse with a
message naming the discounted items that must be returned too. Allowed → no check.

### Interactions
- `discount_limits.py`: a row's discount up to its multi-buy result is exempt (the row fields prove
  where it came from — POS clears `pricing_rules`, so that can't be used).
- `pricing_rule_conflicts.py`: two multi-buy rules overlapping at the same priority conflict like
  normal rules; a multi-buy rule and a normal rule at the same priority also conflict (priority
  is the tie-break between them).
- Pricing Rules Manager page: lists multi-buy rules with a "Buy X get Y d%" badge; editing them
  opens the standard form (the Manager's fixed-shape editor does not create multi-buy rules).
- `linked_document_prices.py` switches: rows whose price is kept from the DN/PR are excluded
  from the basket (they keep the price they had).
- AGT: discounts stay item-level; margins forced to 0. 100% lines (d = 100) produce rate 0 rows:
  allowed by the form but flagged in the rule description as "verify with AGT" (unverified).

### POS Awesome (posawesome fork)
- `update_invoice`: after `run_before_save_methods`, `_apply_manual_discount_override` must not
  re-impose cart discounts on rows with `isoft_multibuy_rule`; then `multi_buy.apply` runs last
  and totals are recomputed. The returned doc (used for the payment screen) carries the result.
- Cart: on item/qty/customer change (debounced ~300 ms) call `multi_buy.preview` and show each
  row's multi-buy discount and a "Buy X get Y" tag; one source of truth (server), no JS copy of
  the algorithm.
- `submit_invoice`: validate re-runs the engine on the same basket → same result.
- POS returns go through the same return check (error shown in the POS).

### Desk
`public/js/multi_buy.js` (doctype_js for the four doctypes): on items / qty / price list /
customer change, debounced `preview` call, writes each row's discount via `frappe.model.set_value`
and a header indicator "Multi-buy: −N Kz". The server result on save is authoritative.

### Tests (standalone checks, rolled back)
- `tests/multi_buy_engine_check.py`: buy 1 get 1 50% same item; across items cheapest first;
  buy 2 get the 3rd; 5 units → 1 group; 7 units buy2get1 → 2; max cap; min_qty / min_amt not met;
  expired / other company / other store / other customer group; UOM Box counts stock units;
  higher-priority normal rule keeps its rows; lower-priority normal rule replaced; desk
  ignore_pricing_rule skips, POS does not; ERPNext per-row lookup never returns a multi-buy rule;
  a multi-buy rule's standard discount fields are 0 after save; totals and taxes consistent;
  no margin; Quotation → SI mapping re-evaluates.
- `tests/multi_buy_return_check.py`: allowed → partial return accepted; not allowed → returning
  only the full-price unit refused, returning both accepted, full return accepted, second partial
  return counts the first.
- `tests/multi_buy_limits_check.py`: discount limits and POS cashier limits exempt multi-buy; a
  manual discount row stays out of the basket and is still checked; Item.max_discount caps.
- Engine cases added by review: row with manual discount out of the basket; non-qualifying basket
  falls back to the next multi-buy rule then to the normal rule; qualifying basket's paying units
  lose the normal discount; mapped rows keep the source result (partial billing 2 + 1).
- `tests/browser_multi_buy.py`: desk SI shows the discount live; POS cart shows it and the payment
  screen total equals the server's; nothing submitted.

## Left to the builder
Exact field placement/labels, the preview debounce, the badge/indicator styling (Invenza look),
Portuguese strings, how the lookup wrapper is shared with item_group_and_brand.py, and the
discount_percentage precision handling (keep the rounding error within one cent per row).
