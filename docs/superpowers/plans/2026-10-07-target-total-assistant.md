# Target Total Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dialog on draft Quotation / Delivery Note / Sales Invoice that rewrites the free item lines so the document's Grand Total or Net Total equals a typed target.

**Architecture:** Pure split/secant helpers in one dependency-free JS file (testable in Node); a dialog module that previews on `frm.doc` and drives ERPNext's own client calculator (`frm.cscript._calculate_taxes_and_totals()` + `calculate_discount_amount()` silently per iteration, full `calculate_taxes_and_totals()` once per fit for refresh); three doctype_js `refresh` handlers add the toolbar button. No server code; one patch bumps `tabDocType.modified` so browsers refetch the form bundles.

**Tech Stack:** Frappe v13 desk JS (jQuery, `frappe.ui.Dialog`), ERPNext v13 `taxes_and_totals.js`, Node 20 for unit tests, Playwright (bench `env/`) for browser verification.

**Spec:** `docs/superpowers/specs/2026-10-07-target-total-assistant-design.md`

## Global Constraints

- Doctypes: Quotation, Delivery Note, Sales Invoice; `docstatus == 0` and `items.length > 0` only.
- Name "Target Total Assistant"; button label "Target Total"; pt "Assistente de Total Alvo" / "Total Alvo".
- Tolerance 0.005 for the solver, 0.01 shown as warning threshold; max 12 secant iterations, max 3 residue passes.
- Rates rounded with `flt(x, precision("rate", item))`; never below 0.
- Default mode Price List Rate; default target kind Grand Total.
- The panel never saves; Apply only closes and marks dirty.
- Never save or submit a Sales Invoice on dev.isoft.ao (FE Angola sends it to the AGT). Quotations may be saved.
- Python edits need `bench restart`; JS in `app_include_js` needs `touch sites/.build`; doctype_js needs the DocType `modified` bump (patch).

## Review Focus

1. Document with a document-level discount (`additional_discount_percentage` / `discount_amount`, `apply_discount_on` Grand Total): Net Total target must be the post-discount `net_total` the form shows. Test: Task 4 browser step 2 uses a quotation with 5% additional discount.
2. Inclusive taxes (`included_in_print_rate`): the Grand Total equals the sum of rates × qty; the solver must still converge. Test: Task 1 secant test with a non-linear S(k); the browser test quotation has only an exclusive 14% tax and dev has no inclusive-tax template, so this stays covered by the synthetic Node secant test only.
3. Two item rows with the same item_code: the residue step must address the row, not the item. Test: Task 2 residue picks by row index (`largest_free` returns an index, writers address `frm.doc.items[idx]`).
4. Typing a rate on a line then changing the default mode: the typed line must stay Fixed. Test: Task 3 `set_default_mode` only touches rows whose mode is not Fixed (Node test on the state helper).
5. Target lower than the fixed lines' contribution: refuse with the lowest reachable total, leave lines at original values. Test: Task 1 `clamp` test and Task 3 `fit` returning `{ok:false, reason}` with the minimum.

---

### Task 1: Pure math helpers with Node tests

**Files:**
- Create: `isoft_customization/public/js/target_total_math.js`
- Test: `isoft_customization/tests/target_total_math.test.js`

**Interfaces:**
- Produces (global `isoft.target_total.math` in the browser, `module.exports` in Node):
  - `scaled_rate(original_rate, k, precision) -> number` : `flt(original_rate * k, precision)`, never < 0. Implement a local `round(x, p)` (Node has no `flt`), used by both environments.
  - `secant_next(k0, s0, k1, s1, target) -> number` : next k; if `s1 == s0` return `k1`; clamp result at 0.
  - `largest_free(lines) -> number` : index of the line with the largest `Math.abs(amount)` among `lines[i].free === true`; -1 if none.
  - `converged(s, target, tol) -> boolean` : `Math.abs(s - target) <= tol`.
  - `set_default_mode(rows, mode) -> rows` : returns a new array where every row whose `mode !== "Fixed"` gets `mode`.

- [ ] **Step 1: Write the failing test** `isoft_customization/tests/target_total_math.test.js` using `node:assert` and `node:test`:

```js
const m = require('../public/js/target_total_math.js');
test('scaled_rate rounds and clamps', () => {
  assert.equal(m.scaled_rate(123.456, 1.1, 2), 135.8);
  assert.equal(m.scaled_rate(10, -0.5, 2), 0);
});
test('secant_next moves toward the target', () => {
  // S(k) = 1000k ; s0 at k0=1 is 1000, s1 at k1=1.2 is 1200, target 1500 -> k=1.5
  assert.equal(m.secant_next(1, 1000, 1.2, 1200, 1500), 1.5);
  assert.equal(m.secant_next(1, 1000, 1.2, 1000, 1500), 1.2); // flat: keep k1
  assert.equal(m.secant_next(1, 1000, 0.5, 500, -100), 0);    // clamp
});
test('secant converges on a non-linear S', () => {
  const S = k => 100 * k + 50 * Math.sqrt(k); // inclusive-tax-like curvature
  let k0 = 1, s0 = S(1), k1 = 2, s1 = S(2), target = 400, n = 0;
  while (!m.converged(s1, target, 0.005) && n++ < 12) {
    const k2 = m.secant_next(k0, s0, k1, s1, target);
    k0 = k1; s0 = s1; k1 = k2; s1 = S(k2);
  }
  assert.ok(m.converged(s1, target, 0.005), `not converged: ${s1}`);
});
test('largest_free picks by row index among free rows', () => {
  const rows = [{amount: 500, free: false}, {amount: 300, free: true}, {amount: 300.5, free: true}];
  assert.equal(m.largest_free(rows), 2);
  assert.equal(m.largest_free([{amount: 1, free: false}]), -1);
});
test('set_default_mode leaves Fixed rows alone', () => {
  const rows = [{mode: 'Fixed'}, {mode: 'Rate'}];
  assert.deepEqual(m.set_default_mode(rows, 'Price List Rate').map(r => r.mode), ['Fixed', 'Price List Rate']);
});
```

- [ ] **Step 2: Run** `node --test isoft_customization/tests/target_total_math.test.js` — expected: FAIL, cannot find module.

- [ ] **Step 3: Implement** `target_total_math.js` as an IIFE that builds `const math = {...}` and ends with `if (typeof module !== 'undefined') module.exports = math; if (typeof window !== 'undefined') { window.isoft = window.isoft || {}; window.isoft.target_total = window.isoft.target_total || {}; window.isoft.target_total.math = math; }`.

- [ ] **Step 4: Run** the test again — expected: all 5 PASS.

- [ ] **Step 5: Commit** `git add isoft_customization/public/js/target_total_math.js isoft_customization/tests/target_total_math.test.js && git commit -m "Target Total Assistant: pure fitting helpers"`.

---

### Task 2: Line writers and the silent recalculation (browser module, part 1)

**Files:**
- Create: `isoft_customization/public/js/target_total_assistant.js`
- Modify: `isoft_customization/hooks.py` (`app_include_js`: add `target_total_math.js` then `target_total_assistant.js`, with a two-line comment like the neighbours)

**Interfaces:**
- Consumes: `isoft.target_total.math` from Task 1.
- Produces (namespace `isoft.target_total`):
  - `snapshot(frm) -> Array<object>` : per row copy of `rate, price_list_rate, discount_percentage, discount_amount, margin_type, margin_rate_or_amount, rate_with_margin`.
  - `restore(frm, snap) -> void` : writes the snapshot back onto `frm.doc.items[i]`.
  - `write_rate(item, new_rate, mode) -> {margin: boolean}` : implements the spec's "What each mode writes" exactly: `Price List Rate` sets `price_list_rate=rate=new_rate`, zeroes `discount_percentage, discount_amount, margin_rate_or_amount, rate_with_margin`, `margin_type=""`; `Rate` with `price_list_rate > 0` sets `rate`, and either discount (`new_rate <= price_list_rate`) or margin `Amount` (`new_rate > price_list_rate`, returns `{margin:true}`); `Rate` with `price_list_rate == 0` behaves as Price List Rate.
  - `recalc_silent(frm) -> void` : `frm.cscript.discount_amount_applied = false; frm.cscript._calculate_taxes_and_totals(); frm.cscript.calculate_discount_amount();` then, if `frm.doc.apply_discount_on == "Grand Total" && frm.doc.is_cash_or_non_trade_discount`, subtract `discount_amount` / `base_discount_amount` from the grand totals (mirror of `calculate_taxes_and_totals` without `refresh_fields`).
  - `current(frm, kind) -> number` : `kind === "Grand Total" ? flt(frm.doc.grand_total) : flt(frm.doc.net_total)`.

- [ ] **Step 1: Write the browser check** as a Playwright step list in `isoft_customization/tests/browser_target_total.py` (harness from the memory recipe: `frappe.sessions.Session(user="Administrator", resume=False, ...)` after stubbing `frappe.local.request` with `cookies: {}`, cookie `sid = session.data.sid`, `ignore_https_errors`, delete the `tabSessions` row at the end). Step for this task: open a draft Quotation, `page.evaluate` `isoft.target_total.write_rate(cur_frm.doc.items[0], 123.45, "Rate")` then `isoft.target_total.recalc_silent(cur_frm)` and assert `cur_frm.doc.items[0].discount_percentage` equals `(plr-123.45)/plr*100` within 1e-6 and `cur_frm.doc.net_total` changed by `(123.45 - old_rate) * qty`. Keep the script runnable with `env/bin/python apps/isoft_customization/isoft_customization/tests/browser_target_total.py --quotation <name>`; it writes its log to a file in the scratchpad (never pipe through `head`, see memory note).

- [ ] **Step 2: Run it** — expected: FAIL, `isoft.target_total.write_rate is not a function`.

- [ ] **Step 3: Implement** the five functions above in `target_total_assistant.js`, register both files in `hooks.py`, `bench build --app isoft_customization` and `touch sites/.build`.

- [ ] **Step 4: Run the browser check** — expected: PASS lines for discount and net_total.

- [ ] **Step 5: Commit** `git add isoft_customization/public/js/target_total_assistant.js isoft_customization/hooks.py isoft_customization/tests/browser_target_total.py && git commit -m "Target Total Assistant: line writers and silent recalculation"`.

---

### Task 3: Solver and dialog (browser module, part 2)

**Files:**
- Modify: `isoft_customization/public/js/target_total_assistant.js`
- Create: `isoft_customization/public/css/target_total_assistant.css`
- Modify: `isoft_customization/hooks.py` (`app_include_css`)
- Modify: `isoft_customization/translations/pt.csv`

**Interfaces:**
- Consumes: Task 1 math, Task 2 writers.
- Produces:
  - `fit(frm, state) -> {ok: boolean, diff: number, reason?: string, min_total?: number}` where `state = {kind: "Grand Total"|"Net Total", target: number, rows: [{idx, mode, original_rate, typed_rate|null, margin:boolean}]}`. Algorithm: restore snapshot; write typed rates on Fixed rows that have `typed_rate`; free rows = mode not Fixed and `qty != 0`; if none → `{ok:false, reason: __("All lines are fixed")}`; if all free `original_rate*qty == 0` → `{ok:false, reason: __("Free lines have no amount; type a rate on at least one line")}`; compute `S(0)` (all free rates 0) → if `target < S(0) - 0.005` → restore, `{ok:false, reason: __("Target too low: lowest reachable total is {0}"), min_total}`; secant from `k0=1, k1 = S(1) ? target/S(1) : 2` using `math.secant_next` up to 12 iterations, each iteration writing `math.scaled_rate(original_rate, k, precision("rate", item))` through `write_rate(item, rate, row.mode)` then `recalc_silent`; then up to 3 residue passes on `math.largest_free`: measure response by nudging that row's rate by one precision unit, scale the nudge by `(target - S) / response`, write, recalc; finally `return {ok: Math.abs(diff) <= 0.01, diff}`. Each `write_rate` return updates `row.margin`.
  - `open(frm) -> frappe.ui.Dialog` : builds the dialog per the spec's Panel section. Header fields (`kind` Select, `target` Currency defaulting to `current(frm, kind)`, `default_mode` Select) are `frappe.ui.Dialog` fields; the lines table and footer are HTML in a `HTML` field (`<table class="isoft-tt-table">`) rendered by `render(state, result)`; row `<select class="tt-mode">` and `<input class="tt-rate">` use delegated `change`/`input` handlers (debounce 150 ms on `input`) that update `state` then call `fit` + `render` + `frm.refresh_field("items")` + `frm.cscript.calculate_taxes_and_totals()` (one full refresh per fit). Rows flagged `margin` get class `tt-margin` and the title text from the spec. Footer shows `net_total`, `total_taxes_and_charges`, `grand_total`, target and status (`tt-ok` green / `tt-bad` red / warning when `0.005 < |diff| <= 0.01`). Buttons: primary "Apply" (`dialog.hide(); frm.dirty();`), secondary "Reset" (restore + state rows to default mode + fit + render), and `dialog.onhide` restores the snapshot unless `applied` is set.
  - Typing into `tt-rate` sets `row.mode = "Fixed"` and `row.typed_rate = value` (written in the mode the row had before, per spec).

- [ ] **Step 1: Extend the browser check** with: open the dialog via `page.evaluate("() => { isoft.target_total.open(cur_frm); }")`, wait for `.isoft-tt-table`, set target = current grand total + 1000 through the dialog field, wait 300 ms, assert `cur_frm.doc.grand_total == target` (±0.005), assert the footer has `tt-ok`; set row 0 mode Fixed, assert `items[0].rate` unchanged while the others moved; type a rate into row 1, assert row 1 `select` reads Fixed and the grand total still equals the target; set target below `S(0)` and assert the red reason text starts with "Target too low"; click Reset and assert totals equal the opening snapshot; click Cancel and assert the same.

- [ ] **Step 2: Run** — expected: FAIL, `open` not a function.

- [ ] **Step 3: Implement** `fit`, `open`, `render` and the CSS (table full width inside the dialog, numeric columns right aligned, `.tt-margin td { background: var(--orange-50, #fff4e5) }`, `.tt-ok { color: var(--green-600) }`, `.tt-bad { color: var(--red-600) }`). Add pt.csv rows for: Target Total, Target Total Assistant, Target kind, Grand Total, Net Total, Target, Current, Difference, Default mode for free lines, Price List Rate, Rate, Fixed, Mode, New rate, New amount, Discount %, On target, Apply, Reset, All lines are fixed, Free lines have no amount; type a rate on at least one line, Target too low: lowest reachable total is {0}, Above price list rate: creates a margin (rejected by AGT on invoices). Use Price List Rate. (skip any label already present in pt.csv). Register the CSS in `hooks.py`, rebuild, `touch sites/.build`.

- [ ] **Step 4: Run the browser check** — expected: all assertions PASS.

- [ ] **Step 5: Commit** `git add -A isoft_customization/public isoft_customization/hooks.py isoft_customization/translations/pt.csv isoft_customization/tests/browser_target_total.py && git commit -m "Target Total Assistant: solver and dialog"`.

---

### Task 4: Toolbar buttons on the three forms, patch, end-to-end verification

**Files:**
- Modify: `isoft_customization/public/js/quotation.js` (add the button inside the existing `refresh`)
- Create: `isoft_customization/public/js/sales_invoice.js`, `isoft_customization/public/js/delivery_note.js`
- Modify: `isoft_customization/hooks.py` (`doctype_js` entries for Sales Invoice and Delivery Note)
- Create: `isoft_customization/patches/bump_target_total_meta.py`; append `isoft_customization.patches.bump_target_total_meta` to `patches.txt` under `[post_model_sync]`

**Interfaces:**
- Consumes: `isoft.target_total.open(frm)`.
- Produces: button "Target Total" (`frm.add_custom_button(__('Target Total'), () => isoft.target_total.open(frm))`) when `frm.doc.docstatus === 0 && (frm.doc.items || []).length`.

- [ ] **Step 1: Extend the browser check** with a `--doctype` switch: for Quotation, Delivery Note and Sales Invoice drafts assert the button `button:has-text("Target Total")` exists on a draft and is absent on a submitted document of the same type (pick names via `frappe.get_all` in the script). Quotation flow (spec test 1): fit to a Grand Total target, `cur_frm.save()` for real, reload, assert `grand_total == target`. Quotation flow (spec test 2) with 5% `additional_discount_percentage`: Net Total target, assert `net_total == target`. Sales Invoice flow (spec test 3): Rate mode with a target above the price list rates, assert a `tt-margin` row exists, Cancel, reload without saving, assert totals unchanged.

- [ ] **Step 2: Run** — expected: FAIL, button not found.

- [ ] **Step 3: Implement** the three doctype_js files (header comment in the style of `purchase_invoice.js`), the hooks entries, the patch (same body as `bump_purchase_invoice_meta.py` looping over the three doctypes), then `bench --site dev.isoft.ao migrate`, `bench build --app isoft_customization`, `touch sites/.build`, `bench restart`.

- [ ] **Step 4: Run the browser check** — expected: PASS for the three doctypes and the three flows. Also run `node --test isoft_customization/tests/target_total_math.test.js` once more.

- [ ] **Step 5: Commit** `git add -A isoft_customization && git commit -m "Target Total Assistant: toolbar button on Quotation, Delivery Note, Sales Invoice"`.

- [ ] **Step 6: Memory note**: update `isoft-customization-app.md` with a short "Target Total Assistant (added 2026-10-07)" paragraph: files, the silent-recalc trick, the margin flag, the never-save rule for Sales Invoice tests.
