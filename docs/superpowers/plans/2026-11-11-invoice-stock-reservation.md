# Invoice Stock Reservation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A ticked Sales Invoice counts its undelivered stock as Reserved Qty, and a ticked Purchase Invoice counts its unreceived stock as Ordered Qty, until Delivery Notes / Purchase Receipts made from it (or credit/debit notes, cancel, Stop) settle it.

**Architecture:** One module, `isoft_customization/invoice_reservation.py`, owns the fields, validation, the per item+warehouse SQL for the invoice part, the runtime wrap of ERPNext's `get_reserved_qty` / `get_ordered_qty` (so every Bin refresh and repost includes it), the doc_event hooks that recompute affected Bins, and the Stop/Resume API. A desk script adds the indicator and buttons. POS Awesome's Customer Orders panel lists reserving invoices next to Sales Orders.

**Tech Stack:** Frappe/ERPNext v13 fork, Python 3.8, MariaDB, desk JS (jQuery/frappe.ui), POS Awesome Vue 2 (Vuetify).

**Spec:** `docs/superpowers/specs/2026-11-11-invoice-stock-reservation-design.md` (read it first; worked examples there are the test oracle).

## Global Constraints

- Frappe/ERPNext v13 fork, Python 3.8. No edits to frappe or erpnext files.
- Commit straight to `master` of each app (isoft_customization, posawesome). Do not push.
- Both boxes default **unticked**. The field installer must never send a `default` key, so a default changed in Customize Form survives `bench migrate`.
- Always **recompute** Bin figures from documents; never add/subtract increments.
- Pending per line, floored at 0, stock UOM:
  - Sales: `stock_qty − delivered_qty × conversion_factor − credited_stock`, credited = −`stock_qty` of submitted returns with `sales_invoice_item` = line.
  - Purchase: `stock_qty − received_stock − debited_stock`, received = Σ `received_stock_qty` of submitted **non-return** Purchase Receipt Items with `purchase_invoice_item` = line; debited = −`stock_qty` of submitted returns with `purchase_invoice_item` = line **and update_stock = 0**.
  - Bundle component: `packed.qty × pending(parent line) ÷ parent line stock_qty`.
- A line never counts when: the invoice is not submitted, is a return, has update_stock = 1, is POS, is stopped; the line has `so_detail` / `dn_detail` (sales) or `po_detail` / `pr_detail` (purchase); the item is not a stock item; `delivered_by_supplier` = 1.
- Tests are rolled-back check scripts run from `sites/`: `../env/bin/python ../apps/isoft_customization/isoft_customization/tests/<file>.py dev.isoft.ao`. **Never `bench run-tests`.** Assert Bin **deltas** (dev already has overstated SO reservations).
- Test company: **Nova Distribuição Angola** (abbr NDA), warehouse `03 - Loja Talatona - NDA`; create throwaway items inside the transaction.
- Labels in English in code; Portuguese in `isoft_customization/translations/pt.csv`.

## Review Focus

1. **A partial Delivery Note from the invoice, then its cancel.** Reserved returns exactly to the pre-DN value (Task 3 `e2e_dn_cancel_restores`).
2. **A repost of the Bin** (`erpnext.stock.stock_balance.repost_stock`) after an invoice reserves. Reserved stays the same (Task 3 `e2e_repost_keeps_invoice_part`).
3. **Invoice created from a Sales Order with the box ticked.** The order's lines don't count twice (Task 2 `calc_so_line_ignored`, Task 1 `validate_keeps_box_for_mixed_lines`).
4. **Ticking the box on an invoice whose stock line has no warehouse.** Refused with a clear message naming the row (Task 1 `validate_requires_warehouse`).
5. **Customize Form default survives migrate.** Run the installer twice with a changed default in between; the default stays (Task 1 `fields_keep_custom_default`).

---

### Task 1: Fields, indexes, validation and bundle components

**Files:**
- Create: `isoft_customization/invoice_reservation.py`
- Modify: `isoft_customization/hooks.py` (after_migrate list; Sales Invoice / Purchase Invoice `validate` lists)
- Test: `isoft_customization/tests/invoice_reservation_fields_check.py`

**Interfaces:**
- Produces:
  - `setup_custom_fields(*args, **kwargs) -> None`. Creates the fields below with `create_custom_fields(..., update=True)` and no `default` key. Adds DB indexes, idempotently:
    - `Sales Invoice Item.sales_invoice_item`
    - `Purchase Invoice Item.purchase_invoice_item`
    - `Purchase Receipt Item.purchase_invoice_item`
    - `Delivery Note Item.si_detail`
    - `Packed Item.parent_detail_docname`

    When it creates a field, it bumps `tabDocType.modified` for Sales Invoice / Purchase Invoice (same as `linked_document_prices.setup_custom_fields`).
  - Fields (Check):

    | Doctype | Field | Label | Settings |
    |---|---|---|---|
    | Sales Invoice | `isoft_reserve_stock` | "Reserve Stock" | insert_after `update_stock`; depends_on `eval:!doc.update_stock && !doc.is_pos && !doc.is_return`; description "Count undelivered quantities as Reserved until Delivery Notes made from this invoice deliver them." |
    | Sales Invoice | `isoft_reservation_stopped` | "Reservation Stopped" | read_only, allow_on_submit, no_copy; depends_on `eval:doc.docstatus==1 && doc.isoft_reserve_stock` |
    | Purchase Invoice | `isoft_order_stock` | "Order Stock" | insert_after `update_stock`; depends_on `eval:!doc.update_stock && !doc.is_return` |
    | Purchase Invoice | `isoft_ordering_stopped` | "Ordering Stopped" | same as `isoft_reservation_stopped` |
  - `validate_sales_invoice(doc, method=None) -> None`:
    - Forces `isoft_reserve_stock = 0` when `update_stock`, `is_pos` or `is_return`.
    - Forces `isoft_reservation_stopped = 0` on drafts.
    - When ticked, every **counting** line (`line_counts(doc, row)`) without a warehouse throws `"Row {0}: Warehouse is required to reserve stock for {1}."`
    - When ticked, rebuilds packed items with `erpnext.stock.doctype.packed_item.packed_item.make_packing_list(doc)`. Core's `update_packing_list` emptied them earlier in validate.
  - `validate_purchase_invoice(doc, method=None) -> None`. The purchase mirror (no POS, no packed items). Message: `"Row {0}: Warehouse is required to order stock for {1}."`
  - `line_counts(doc, row) -> bool`. The line rules from Global Constraints for one row of a saved/draft doc. Bundle parents count when they have packed items.

- [ ] **Step 1: Write the failing test** `invoice_reservation_fields_check.py` (pattern: `multi_buy_return_check.py`: init site from argv, `check(name, cond, detail)`, rollback at end, exit code = fails). Checks:
  - `fields_exist`: all four custom fields exist with the labels above, and none has a `default` other than empty/0.
  - `fields_keep_custom_default`: set `Custom Field.default = "1"` on `Sales Invoice-isoft_reserve_stock`, run `setup_custom_fields()`, and the default is still `"1"`.
  - `indexes_exist`: `show index` finds the five columns.
  - `validate_off_with_update_stock`: an unsaved NDA Sales Invoice with update_stock=1 and the box ticked has the box at 0 after `doc.run_method("validate")`. Same for `is_pos=1`.
  - `validate_requires_warehouse`: box ticked, stock line with warehouse cleared → `frappe.ValidationError` whose message contains `"Row 1"`.
  - `validate_keeps_box_for_mixed_lines`: ticked invoice with one line carrying `so_detail` and one free line validates; `line_counts` is False/True respectively.
  - `validate_builds_packed_items`: ticked invoice with a Product Bundle line (bundle created in-test over two throwaway stock items, 2 and 3 per bundle; line qty 2) has packed_items with qty 4 and 6 after validate. Unticked: no packed_items.
  - `validate_purchase_off_on_return`: Purchase Invoice with `is_return=1` and box ticked → box 0.

- [ ] **Step 2: Run it and see it fail**
  Run: `../env/bin/python ../apps/isoft_customization/isoft_customization/tests/invoice_reservation_fields_check.py dev.isoft.ao`
  Expected: FAIL `fields_exist` (ImportError or missing fields).

- [ ] **Step 3: Implement** the Interfaces above in `invoice_reservation.py`. Wire them in hooks.py:
  - Append `setup_custom_fields` to `after_migrate`.
  - Append `validate_sales_invoice` to `doc_events["Sales Invoice"]["validate"]` and `validate_purchase_invoice` to the Purchase Invoice `validate` list (both are existing lists).
  - Run `setup_custom_fields()` once on dev through a venv script (memory: `bench execute` cannot import app modules).

- [ ] **Step 4: Run the check**. Expected: every line PASS, exit 0.

- [ ] **Step 5: Commit**
```bash
git add isoft_customization/invoice_reservation.py isoft_customization/hooks.py isoft_customization/tests/invoice_reservation_fields_check.py
git commit -m "Invoice stock reservation: fields, indexes, validation, bundle components"
```

---

### Task 2: Invoice part of Reserved / Ordered, wrapped into ERPNext's calculation

**Files:**
- Modify: `isoft_customization/invoice_reservation.py`
- Modify: `isoft_customization/__init__.py` (`_install_runtime_patches`), `isoft_customization/hooks.py` (`before_request`, `before_job`)
- Test: `isoft_customization/tests/invoice_reservation_calc_check.py`

**Interfaces:**
- Consumes: Task 1 fields and `line_counts` rules (expressed in SQL here; no per-row Python).
- Produces:
  - `invoice_reserved_qty(item_code: str, warehouse: str) -> float`. Sum over counting Sales Invoice lines **and** Packed Item components (parenttype "Sales Invoice") for that item+warehouse, per the Global Constraints formulas. One SQL query per call.
  - `invoice_ordered_qty(item_code: str, warehouse: str) -> float`. Purchase mirror. One SQL query.
  - `apply() -> None`. Idempotent; it marks wrapped functions with an attribute so they are never wrapped twice. It replaces:
    - `erpnext.stock.stock_balance.get_reserved_qty` **and** `erpnext.selling.doctype.sales_order.sales_order.get_reserved_qty` with `original(item, wh) + invoice_reserved_qty(item, wh)`;
    - `erpnext.stock.stock_balance.get_ordered_qty` **and** `erpnext.buying.doctype.purchase_order.purchase_order.get_ordered_qty` with `original + invoice_ordered_qty`.

    Never raises if erpnext is not importable.

- [ ] **Step 1: Write the failing test** `invoice_reservation_calc_check.py`. Fixtures are written with `db_insert` as submitted documents (as in `multi_buy_return_check.py`: no hooks, no GL) for throwaway NDA stock items in `03 - Loja Talatona - NDA`. Set `delivered_qty`, `received_stock_qty`, return rows and their links directly. Assert `invoice_reserved_qty` / `invoice_ordered_qty`:
  - `calc_spec_example_1`: invoice 10 → 10; line `delivered_qty` 6 → 4; + submitted credit note −3 linked via `sales_invoice_item` → 1; delivered 7 → 0.
  - `calc_spec_example_2`: invoice 10, delivered 8 → 2; + credit note −2 → 0.
  - `calc_uom`: qty 2 "Box" conversion_factor 12 (stock_qty 24) → 24; delivered_qty 1 → 12.
  - `calc_so_line_ignored`: a line with `so_detail` set → 0. `calc_dn_line_ignored`: `dn_detail` set → 0.
  - `calc_excluded_invoices`: box 0 → 0; stopped → 0; update_stock 1 → 0; docstatus 2 → 0; non-stock item → 0; delivered_by_supplier 1 → 0.
  - `calc_over_delivered_floor`: delivered_qty 12 on qty 10 → 0, not −2.
  - `calc_bundle`: bundle line qty 2, packed component A qty 4 and B qty 6; parent `delivered_qty` 1 → A 2, B 3.
  - `calc_purchase`:
    - Invoice 10 → 10.
    - Purchase Receipt Item (non-return, docstatus 1) `received_stock_qty` 6 linked → 4.
    - Plus a debit note (update_stock 0) −3 → 1.
    - Plus a debit note (update_stock 1) −2 → still 1.
    - Plus a Purchase Receipt return row without the link → still 1.
    - A line with `po_detail` → 0.
  - `calc_wrap`:
    - After `apply()`, `stock_balance.get_reserved_qty(item, wh)` equals `<original>(item, wh) + invoice_reserved_qty(item, wh)`. The original is read from the wrapper's stored reference.
    - `sales_order.get_reserved_qty is stock_balance.get_reserved_qty`.
    - Calling `apply()` again leaves the function object unchanged.
    - The same three checks for ordered qty and `purchase_order`.

- [ ] **Step 2: Run it and see it fail.** Expected: ImportError `invoice_reserved_qty`.

- [ ] **Step 3: Implement** the Interfaces above.
  - Call `apply()` from `_install_runtime_patches` in its own try/except block (same shape as the existing ones).
  - Append `"isoft_customization.invoice_reservation.apply"` to `before_request` and `before_job`.

- [ ] **Step 4: Run the check.** Expected: all PASS. Also run `EXPLAIN` on both queries for one item and note the plan in the commit message (expect index use on item_code and the new link indexes).

- [ ] **Step 5: Commit**
```bash
git add isoft_customization/invoice_reservation.py isoft_customization/__init__.py isoft_customization/hooks.py isoft_customization/tests/invoice_reservation_calc_check.py
git commit -m "Invoice stock reservation: invoice part of Reserved/Ordered inside ERPNext's calculation"
```

---

### Task 3: Recompute Bins on every document that moves a pending quantity; Stop/Resume

**Files:**
- Modify: `isoft_customization/invoice_reservation.py`, `isoft_customization/hooks.py`
- Test: `isoft_customization/tests/invoice_reservation_flow_check.py`

**Interfaces:**
- Consumes: Task 2 `apply()` (so `stock_balance.get_reserved_qty` / `get_ordered_qty` already include invoices); `erpnext.stock.stock_balance.update_bin_qty`.
- Produces:
  - `invoice_pairs(doctype: str, name: str) -> set`: `(item_code, warehouse)` of the invoice's items and packed items (any line with a warehouse; recomputing extra pairs is harmless).
  - `refresh_invoice(doctype: str, name: str) -> None`: for each pair, `update_bin_qty(item, wh, {"reserved_qty": stock_balance.get_reserved_qty(item, wh)})` (Sales Invoice) or `{"ordered_qty": stock_balance.get_ordered_qty(...)}` (Purchase Invoice). Skips invoices whose box is 0.
  - Hooks (all `(doc, method=None)`), registered on `on_submit` and `on_cancel`:

    | Hook | Doctype | What it refreshes |
    |---|---|---|
    | `on_sales_invoice_event` | Sales Invoice | itself, or `return_against` when `is_return` |
    | `on_delivery_note_event` | Delivery Note | every distinct `against_sales_invoice` on rows with `si_detail` (covers DN returns) |
    | `on_purchase_invoice_event` | Purchase Invoice | itself, or `return_against` |
    | `on_purchase_receipt_event` | Purchase Receipt | every distinct `purchase_invoice` on rows with `purchase_invoice_item` |
  - `@frappe.whitelist() set_stopped(doctype: str, name: str, stopped: int) -> dict`:
    - Doctype must be Sales Invoice or Purchase Invoice.
    - The invoice must be submitted with the box ticked.
    - Requires `frappe.has_permission(doctype, "submit", name)`.
    - Then `db_set` the stopped field, `refresh_invoice`, and return `pending_summary(...)`.
  - `@frappe.whitelist() pending_summary(doctype: str, name: str) -> dict` returns `{"enabled": 0|1, "stopped": 0|1, "pending_qty": float}`. `pending_qty` is the stock-UOM sum over this invoice's counting lines (bundle parents counted by their components), and it ignores the stopped flag. Needs read permission.

- [ ] **Step 1: Write the failing test** `invoice_reservation_flow_check.py`. These are **real** documents in one transaction that is rolled back at the end.
  - Before anything else, replace `frappe.db.commit` with a function that raises `"commit attempted"`. Any commit fails the check instead of leaving data behind.
  - Setup: a throwaway NDA stock item, plus a submitted Material Receipt Stock Entry of 20 into `03 - Loja Talatona - NDA`.
  - Read Bin `reserved_qty` / `ordered_qty` as the baseline B.
  - Sales checks, in order:
    - `e2e_si_reserves`: submit a ticked SI for 5 → reserved = B + 5, and `projected_qty` drops by 5.
    - `e2e_dn_partial`: `make_delivery_note` from the SI, qty 2, submit → B + 3.
    - `e2e_credit_note`: `make_sales_return` from the SI, qty −1 (Update Stock off), submit → B + 2.
    - `e2e_dn_return`: return of the DN, qty −1, submit → B + 3.
    - `e2e_stop_resume`: `set_stopped(..., 1)` → B, and `pending_summary` shows `stopped=1` with `pending_qty` 3. `set_stopped(..., 0)` → B + 3.
    - `e2e_repost_keeps_invoice_part`: `erpnext.stock.stock_balance.repost_stock(item, wh)` → still B + 3.
    - `e2e_dn_cancel_restores`: cancel the DN return, then the DN → B + 4.
    - `e2e_cancel_all`: cancel the credit note, then the SI → B.
  - Purchase checks:
    - `e2e_pi_orders`: submit a ticked PI for 4 → ordered = B′ + 4.
    - `e2e_pr_partial`: `make_purchase_receipt` from the PI, qty 3, submit → B′ + 1.
    - `e2e_pr_cancel`: cancel → B′ + 4.
    - `e2e_debit_note`: debit note qty −4, Update Stock off → B′.
    - `e2e_pi_cancel`: cancel the debit note, then the PI → B′.
  - `e2e_bundle`: ticked SI with 2 bundles (components 2 + 3 per bundle) → component A reserved +4 and B +6. Then a DN from the SI for 1 bundle → +2 and +3.
  - `e2e_untouched_invoice`: an unticked SI changes nothing.

- [ ] **Step 2: Run it and see it fail.** Expected: FAIL `e2e_si_reserves` (Bin unchanged).

- [ ] **Step 3: Implement** the Interfaces above and register them in hooks.py:
  - Append to the existing `on_submit` value (string → list) and add `on_cancel` for each of the four doctypes. Use `_append_doc_event` where the shape is irregular.
  - If an `e2e_*` check fails because a third-party hook commits, stop and report which hook. Do not remove the guard.

- [ ] **Step 4: Run all three checks** (fields, calc, flow). Expected: all PASS.

- [ ] **Step 5: Commit**
```bash
git add isoft_customization/invoice_reservation.py isoft_customization/hooks.py isoft_customization/tests/invoice_reservation_flow_check.py
git commit -m "Invoice stock reservation: Bin refresh on SI/PI/DN/PR submit and cancel, Stop/Resume"
```

---

### Task 4: Desk indicator and Stop / Resume buttons

**Files:**
- Create: `isoft_customization/public/js/invoice_reservation.js`
- Modify: `isoft_customization/hooks.py` (append to `doctype_js` for Sales Invoice and Purchase Invoice, same loop style as `multi_buy.js`)
- Modify: `isoft_customization/translations/pt.csv`
- Test: `isoft_customization/tests/browser_invoice_reservation.py` (pattern: `browser_multi_buy.py` / `browser_target_total.py` helpers)

**Interfaces:**
- Consumes: Task 3 `pending_summary`, `set_stopped`.
- Produces: on `refresh` of a submitted invoice with the box ticked, the script calls `pending_summary`:
  - **Indicator** via `frm.dashboard.set_headline_alert`:
    - `"Reserving {0} units until delivered"` (blue). Purchase: `"Ordering {0} units until received"`.
    - `"Reservation stopped"` / `"Ordering stopped"` (grey).
    - Nothing when pending is 0.
  - **Buttons** in the group `"Reservation"` (purchase: `"Ordering"`):
    - `"Stop reserving"` / `"Stop ordering"`, shown when not stopped and pending > 0.
    - `"Resume reserving"` / `"Resume ordering"`, shown when stopped.
    - Each asks `frappe.confirm` first, then calls `set_stopped` and `frm.reload_doc()`.
  - **PT strings**:

    | English | Portuguese |
    |---|---|
    | Reserve Stock | Reservar Stock |
    | Order Stock | Encomendar Stock |
    | Reservation Stopped | Reserva Parada |
    | Ordering Stopped | Encomenda Parada |
    | Reserving {0} units until delivered | A reservar {0} unidades até à entrega |
    | Ordering {0} units until received | A encomendar {0} unidades até à receção |
    | Reservation stopped | Reserva parada |
    | Ordering stopped | Encomenda parada |
    | Reservation | Reserva |
    | Ordering | Encomenda |
    | Stop reserving | Parar reserva |
    | Resume reserving | Retomar reserva |
    | Stop ordering | Parar encomenda |
    | Resume ordering | Retomar encomenda |
    | Row {0}: Warehouse is required to reserve stock for {1}. | Linha {0}: o Armazém é obrigatório para reservar stock de {1}. |
    | Row {0}: Warehouse is required to order stock for {1}. | Linha {0}: o Armazém é obrigatório para encomendar stock de {1}. |

    Add the description strings from Task 1 too.

- [ ] **Step 1: Write the failing browser check.**
  - Use one real **draft** ticked SI on NDA, created by the script and deleted at the end.
  - `draft_box_visible`: the draft form shows the "Reserve Stock" checkbox, and it hides when Update Stock is ticked.
  - `submitted_indicator`: no real submit (a browser session cannot roll back). Mock `frappe.call` for `pending_summary` in the page (`page.evaluate`) on the draft form forced to `docstatus=1` client-side. Assert the indicator text and the button labels for the three states (pending, stopped, zero).
- [ ] **Step 2: Run it and see it fail.** Run: `../env/bin/python ../apps/isoft_customization/isoft_customization/tests/browser_invoice_reservation.py`. Expected: FAIL `submitted_indicator`.
- [ ] **Step 3: Implement** the script and the translations.
  - Bump `tabDocType.modified` for Sales Invoice and Purchase Invoice (memory: frappe-doctype-js-localstorage-cache), and `touch sites/.build`.
  - Run `translations_override.sync_translations`.
- [ ] **Step 4: Run the browser check.** Expected: all PASS.
- [ ] **Step 5: Commit**
```bash
git add isoft_customization/public/js/invoice_reservation.js isoft_customization/hooks.py isoft_customization/translations/pt.csv isoft_customization/tests/browser_invoice_reservation.py
git commit -m "Invoice stock reservation: desk indicator, Stop/Resume buttons, PT labels"
```

---

### Task 5: POS Awesome Customer Orders lists reserving invoices

**Files:**
- Modify: `apps/posawesome/posawesome/posawesome/api/customer_orders.py`
- Modify: `apps/posawesome/posawesome/public/js/posapp/components/pos/CustomerOrders.vue`
- Test: `apps/posawesome/posawesome/posawesome/api/customer_orders.py` `_self_check()` (extend it) or a new rolled-back check script in isoft_customization/tests named `pos_customer_orders_invoices_check.py`

**Interfaces:**
- Consumes: Task 2 `invoice_reserved_qty` semantics. Reuse the same line conditions. Import a SQL-condition helper from `isoft_customization.invoice_reservation` only if `frappe.get_installed_apps()` includes it; otherwise the API returns Sales Orders only, as today.
- Produces:
  - `search_customer_orders(...)`: every row gains `doctype` ("Sales Order" | "Sales Invoice").
    - With `status="open"`, it also returns reserving Sales Invoices with pending > 0 in the profile's warehouse and company.
    - Fields mapped onto the existing row keys: `transaction_date` ← posting_date, `delivery_date` ← posting_date, `status` ← "To Deliver", `per_delivered` computed, `po_no` ← "", requester fields empty, `item_pending` = that item's pending.
    - Order: by date, as now.
  - `count_open_customer_orders` counts both doctypes.
  - `get_customer_order_items(pos_profile, sales_order, doctype="Sales Order")` accepts Sales Invoice (lines with their pending qty).
  - Vue:
    - Invoice rows show a small "Invoice" chip after the name.
    - They never show "Pull to cart". The slot shows `__('To deliver')` instead.
    - Expand loads lines with `doctype`.
    - The row key becomes `doctype + name`.

- [ ] **Step 1: Write the failing check.**
  - Inside a rollback, `db_insert` a submitted ticked SI fixture (as in Task 2) for an NDA POS Profile's warehouse.
  - `pos_lists_invoice`: `search_customer_orders(profile, status="open")` contains it with `doctype == "Sales Invoice"`.
  - `pos_item_pending`: with `item_code`, `item_pending` equals `invoice_reserved_qty` for that invoice alone.
  - `pos_count`: the count increased by 1.
  - `pos_not_listed_when_stopped`: the stopped invoice is absent.
  - Pick an NDA POS Profile; if none exists, create one in the transaction.
- [ ] **Step 2: Run it and see it fail.**
- [ ] **Step 3: Implement** the API and Vue changes. Build: `cd /home/frappe/frappe-bench && bench build --app posawesome` (dart-sass toolchain per memory sass-build-toolchain).
- [ ] **Step 4: Run the check**, then open the POS on dev (Playwright via the nginx host mapping, per memory invenza-manufacturing-mode). Assert that the Customer Orders panel shows the "Invoice" chip on a reserving invoice and has no pull button for it. Use the same mock approach as Task 4 if no real reserving invoice exists on dev.
- [ ] **Step 5: Commit (in posawesome, and the check in isoft_customization)**
```bash
cd /home/frappe/frappe-bench/apps/posawesome && git add posawesome/posawesome/api/customer_orders.py posawesome/public/js/posapp/components/pos/CustomerOrders.vue && git commit -m "Customer Orders: list Sales Invoices that reserve stock (read-only)"
cd /home/frappe/frappe-bench/apps/isoft_customization && git add isoft_customization/tests/pos_customer_orders_invoices_check.py && git commit -m "Check: POS Customer Orders lists reserving invoices"
```

---

### Task 6: Deploy on dev and verify

**Files:** none new.

- [ ] **Step 1:** `cd /home/frappe/frappe-bench && bench --site dev.isoft.ao migrate`. Expected: no errors. The four fields and five indexes exist (re-run the Task 1 check).
- [ ] **Step 2:** `bench restart` (gunicorn `--preload`: Python edits need it), then `touch sites/.build`.
- [ ] **Step 3:** Re-run the four check scripts plus both browser checks. Expected: all PASS, exit 0.
- [ ] **Step 4:** Sanity check that nothing changed for existing data. On dev, `select count(*) from tabBin` where `reserved_qty` differs from `get_reserved_qty(item, wh)` should be the same before and after (no ticked invoices exist yet). Record the numbers.
- [ ] **Step 5:** Commit any fix-ups; report to the user, with the commit hashes, what to try on dev.
