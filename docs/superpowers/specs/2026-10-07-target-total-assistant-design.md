# Target Total Assistant — design

Date: 2026-10-07. App: isoft_customization. Status: approved in chat, pending spec review.

## Purpose

A user editing a draft Quotation, Delivery Note or Sales Invoice has lines with
prices and wants the document to land on a chosen total (grand total, or net
total before tax). Today they adjust rates by hand and iterate. The Target Total
Assistant opens a panel where they type the target, choose per line whether the
line is Fixed or free to move, choose how a free line is rewritten (Rate, i.e. a
discount against the price list rate, or Price List Rate itself), and the panel
rewrites the free lines so the document total equals the target exactly.

Name: **Target Total Assistant** (pt: "Assistente de Total Alvo").

## Scope

- Doctypes: Quotation, Delivery Note, Sales Invoice. Draft only (docstatus 0),
  at least one item row.
- Target kinds: Grand Total (after taxes and document discount) or Net Total
  (before taxes, after document discount). These are the form's own
  `grand_total` and `net_total`.
- Line modes: Fixed, Rate, Price List Rate.
- Split rule: proportional to each free line's current amount.
- Out of scope: buying documents, submitted documents, pricing-rule
  re-evaluation, server-side solver, any new DocType or setting.

## Entry point

Toolbar button "Target Total" on the three forms, shown by the doctype_js
`refresh` handler when `docstatus == 0` and `items.length > 0`. Opens a wide
`frappe.ui.Dialog`.

## Panel

Header
- Target kind: Select, Grand Total (default) | Net Total.
- Target: Currency input, defaults to the current value of the chosen kind.
- Current value and Difference, read only.
- Default mode for free lines: Select, Price List Rate (default) | Rate.
  Changing it sets every non-Fixed line to that mode.

Lines table, one row per `items` row, in document order
- Item code and item name, qty, current rate, current amount (read only).
- Mode: Select, Fixed | Rate | Price List Rate.
- New rate: editable number input. Typing a value sets the row to Fixed with
  that rate.
- New amount, resulting discount % (read only).
- Rows with qty 0 are shown as Fixed and cannot be freed.

Footer
- Resulting Net Total, Total Taxes, Grand Total, and the target, with a status
  line: green "On target" or a red reason.
- Buttons: Apply (primary), Reset, Cancel.

Every change (target kind, target, default mode, row mode, row rate) re-fits
immediately. No separate "Calculate" button.

## Fitting

Definitions: `original` is a deep snapshot of `rate`, `price_list_rate`,
`discount_percentage`, `discount_amount`, `margin_type`,
`margin_rate_or_amount`, `rate_with_margin` for every item, plus the document
totals, taken when the panel opens. Free lines are rows whose mode is not Fixed
and whose qty is not 0. The target total is `T`. Rate precision `p` is
`precision("rate", item)`.

Algorithm (client side, operating on `frm.doc`):

1. Compute the fixed part by running the form calculator with the free lines at
   factor `k = 1`. Let `S(k)` be the resulting total of the chosen kind after
   writing `rate_i = round(original_rate_i * k, p)` on every free line and
   running `frm.cscript.calculate_taxes_and_totals()`.
2. Solve `S(k) = T` by secant iteration starting from `k0 = 1` and
   `k1 = T / S(1)` (when `S(1)` is 0, fall back to `k1 = 2`). Stop when
   `|S(k) - T| <= 0.005` or after 12 iterations. Clamp `k >= 0`.
3. Residue: if `|S(k) - T| > 0.005` after iteration, adjust the largest free
   line (by amount) by `delta_rate = round((T - S(k)) / (qty * tax_factor), p)`
   where `tax_factor` is `line.net_amount ? (line_total_with_tax / line.net_amount) : 1`
   for Grand Total and 1 for Net Total, recalculate, and repeat at most 3 times.
   `line_total_with_tax` comes from the row's share in `taxes[].item_wise_tax_detail`.
4. Report the final difference. Anything beyond 0.01 after step 3 is shown in
   the footer as a warning rather than hidden.

Rates never go below 0: if the solution would need a negative rate the panel
shows "Target too low: lowest reachable total is X" (X = total with all free
rates at 0) and leaves the lines at their original values.

If there are no free lines the panel shows "All lines are fixed".
If every free line has amount 0 the proportional split cannot move them; the
panel says "Free lines have no amount; type a rate on at least one line".

## What each mode writes on a line

Price List Rate (default)
- `rate = new_rate`, margin cleared. An existing discount on the line (typed
  by hand or from a pricing rule) is kept (user decision 2026-10-07): with
  `discount_percentage` p in (0, 100), `price_list_rate = new_rate / (1 - p/100)`
  and `discount_amount = price_list_rate - new_rate`; with only a
  `discount_amount` a, `price_list_rate = new_rate + a`; with no discount,
  `price_list_rate = new_rate` and both discount fields are 0.

Rate
- `price_list_rate` unchanged. `rate = new_rate`.
- If `price_list_rate > 0` and `new_rate <= price_list_rate`:
  `discount_percentage = (price_list_rate - new_rate) / price_list_rate * 100`,
  `discount_amount = price_list_rate - new_rate`, margin cleared.
- If `price_list_rate > 0` and `new_rate > price_list_rate`: margin required.
  `margin_type = "Amount"`, `margin_rate_or_amount = new_rate - price_list_rate`,
  `rate_with_margin = new_rate`, discount cleared. The row is flagged orange:
  "Above price list rate: creates a margin (rejected by AGT on invoices). Use
  Price List Rate." The fit still applies if the user accepts.
- If `price_list_rate == 0`: behaves like Price List Rate mode (sets
  `price_list_rate` too), since a discount cannot be expressed.

Fixed
- Nothing written; the row keeps its current values (including a value typed
  by the user into New rate, which was written once when typed, in the mode the
  row had before it became Fixed).

Base-currency fields (`base_rate`, `base_amount`, `net_rate`, `net_amount`,
`base_price_list_rate`, `base_rate_with_margin`) are derived by the form
calculator and are not written by the panel.

## Apply, Reset, Cancel

- The panel previews on `frm.doc` itself, so the form behind the dialog always
  shows the pending result. Each refit calls `frm.refresh_field("items")` and
  the totals refresh that the calculator already does.
- Apply: closes the dialog, leaves the current values, `frm.dirty()`. The user
  saves as usual. Nothing is saved by the panel.
- Reset: restores `original` on every row, recalculates, re-renders the table
  with all rows in the default mode.
- Cancel (or closing the dialog): same restore as Reset, then closes.
- Pricing rules are not re-applied. The result behaves exactly like a manual
  rate edit; the server-side validate may re-apply pricing rules on save as it
  does for any manual edit.

## Files

- `isoft_customization/public/js/target_total_assistant.js`: the dialog, the
  pure split helpers (`isoft.target_total.split`, `isoft.target_total.residue`
  exposed for tests), the solver loop and the line writers. Registered in
  `app_include_js`.
- `isoft_customization/public/css/target_total_assistant.css`: table layout
  inside the dialog. Registered in `app_include_css`.
- `isoft_customization/public/js/quotation.js`, `sales_invoice.js` (new),
  `delivery_note.js` (new): `refresh` handler adding the button and calling
  `isoft.target_total.open(frm)`. `hooks.py` `doctype_js` gains the two new
  entries.
- `isoft_customization/translations/pt.csv`: labels.
- `isoft_customization/tests/target_total_split.test.js`: Node test for the
  pure helpers (run with `node`).
- `patches.txt`: no entry needed. doctype_js is served through the DocType's
  `__js` bundle; a `touch sites/.build` plus the DocType `modified` bump is
  only needed on deployment if a browser has the bundle cached (see memory
  note frappe-doctype-js-localstorage-cache). Sales Invoice and Delivery Note
  get a Python patch `bump_target_total_meta` that bumps `tabDocType.modified`
  for the three doctypes.

## Testing

- Node unit test for the proportional split and residue placement: shares sum
  to the target, fixed rows untouched, zero-amount rows get 0, residue lands on
  the largest free row, negative result refused.
- Browser (Playwright on dev.isoft.ao, session minted as in the memory recipe):
  1. Quotation with three lines and two tax rates: open the panel, set Grand
     Total target, confirm the footer reads On target and the form's grand
     total equals the target, save for real, reload, confirm it persisted.
  2. Same quotation: fix one line, type a rate on another, confirm the third
     absorbs the difference; Cancel restores the original totals.
  3. Sales Invoice draft: fit to a Net Total target in Rate mode with a line
     above price list rate, confirm the orange margin flag; Cancel; reload the
     page without saving. Never save or submit the Sales Invoice.
