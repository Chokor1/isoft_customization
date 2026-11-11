# Invoice stock reservation (Sales Invoice reserves, Purchase Invoice orders) — design

Date: 2026-11-11 · App: isoft_customization · Approach 1, chosen by the user

## Intent

In Angola the usual selling flow is **Quotation → Sales Invoice → Delivery Note**; Sales Orders
are not used. The goods are invoiced (often paid) first and delivered later, and in between they
must count as **Reserved** so nobody else plans to sell them. The user does not want an extra
document for this: the Sales Invoice itself reserves, with a tick box to switch it off. The
purchase side mirrors it: a Purchase Invoice for goods not yet received counts as **Ordered**
until the Purchase Receipt arrives.

## What the user decided

- A tick box on **Sales Invoice**: ticked, the invoice's undelivered quantity counts in the
  item/warehouse **Reserved Qty** (as a Sales Order would) until Delivery Notes made from it deliver it.
- The same on **Purchase Invoice**: ticked, its unreceived quantity counts in **Ordered Qty** (as a
  Purchase Order would) until Purchase Receipts made from it receive it.
- The user can untick it to invoice without reserving / ordering.
- Delivery Note, Purchase Receipt, cancel and credit/debit notes must all leave the figures right.
- Build it as approach 1: the invoice counts directly inside ERPNext's own Reserved / Ordered
  calculation. Rejected: a hidden Sales/Purchase Order behind each invoice (brings back the extra
  documents, numbering and cancel chains the user wants to avoid); a separate reservation table
  (ERPNext's reports and Projected Qty would not see it).

## Goals

1. **Sales Invoice** gets `Reserve Stock` (Check). **Purchase Invoice** gets `Order Stock` (Check).
2. While a submitted, ticked invoice line is still pending, it adds to Bin `reserved_qty`
   (Sales) or `ordered_qty` (Purchase) for its item and warehouse, in stock UOM.
   `projected_qty` follows, as Bin always recomputes it.
3. Pending quantity per line (transaction UOM, then × `conversion_factor`, floored at 0):
   - Sales: `qty − delivered_qty − credited_qty`
   - Purchase: `qty − received_qty − debited_qty`

   where `delivered_qty` is ERPNext's own Sales Invoice Item field (filled by Delivery Notes made
   from the invoice via `si_detail`, including their returns). `received_qty` is **counted
   directly** from submitted Purchase Receipt Items with `purchase_invoice_item` = the line, not
   read from the invoice line's stored `received_qty` (dev has stale values left by toggling
   Update Stock / duplicating). `credited_qty` / `debited_qty` is the quantity on submitted
   return invoices against that line (`sales_invoice_item` / `purchase_invoice_item`) **with Update
   Stock off**.
   - Sales: core forbids an Update-Stock credit note against an invoice without Update Stock
     (`sales_and_purchase_return.py:66`), so every sales credit note against a reserving invoice
     counts as credited. Goods coming back = Delivery Note return + credit note.
   - Purchase: a debit note *with* Update Stock is a physical return of received goods and cancels
     out (last example row), so it is not counted.
   - *Builder-check call:* a **Purchase Receipt return does not reopen Ordered**. ERPNext does not
     carry `purchase_invoice_item` onto PR returns (`make_return_doc`), and goods sent back to a
     supplier are normally settled by a debit note. Delivery Note returns *do* reopen Reserved,
     because ERPNext links them (`si_detail`) and the customer is still owed the goods.
4. The figures are refreshed (the affected item/warehouse Bins recomputed from the documents,
   never incremented) on submit and cancel of: the ticked invoice; its credit/debit notes; Delivery
   Notes / Purchase Receipts (and their returns) linked to it; and on "Stop reserving".
5. ERPNext's recalculation tools (`stock_balance.repost_stock` and anything else that calls
   `get_reserved_qty` / `get_ordered_qty`) include the invoice part, so a repost never wipes it.
6. **Stop reserving / Stop ordering** button on a submitted ticked invoice (and Resume), for goods
   that will never be delivered through a Delivery Note. Sets an allow-on-submit flag; a stopped
   invoice contributes 0.
7. **Product Bundles (user: must be handled).** Core only builds Packed Items on a Sales Invoice
   with Update Stock on and empties them otherwise (`sales_invoice.py` ~1034-1040). On a
   **reserving** invoice the app rebuilds them (`make_packing_list`) after the core validate, so
   the components are stored on the invoice at submit time. That way, editing the bundle later
   does not change what was reserved. Each component reserves
   `packed qty × (parent line pending ÷ parent line qty)`, the same proportional rule ERPNext uses
   for Sales Orders. The parent bundle item itself never reserves (it is not a stock item).
   Checked on dev: no Sales Invoice print format, SAF-T or AGT code reads `packed_items`; the
   only other reader, `batch_integrity.py`, only checks rows that carry a batch. Purchase
   Invoices have no bundles.
8. *Builder-check call:* **channels that publish actual − reserved** (isoft_mobile catalogue,
   woocommerceconnector) will stop offering reserved stock. That is the intended meaning (the
   goods are sold), so no exclusions. **CS-Cart** already has a choice in CSCart Integration
   Settings → *Quantity Basis*: Actual Qty / Actual Qty − Reserved Qty / Projected Qty. The user
   wants it left as it is (dev is on *Actual Qty*, so CS-Cart is unaffected). Nothing to build. **POS Awesome:** its
   "Ordered" column reads `Bin.reserved_qty` and will include invoices. The Customer Orders panel
   and badge list reserving invoices too (read-only, no pull-to-cart), so the column and panel agree.

### Worked examples (sales; purchase is identical with receipts)

| Steps | qty | delivered | credited (no stock) | Reserved |
|---|---|---|---|---|
| Invoice 10 | 10 | 0 | 0 | 10 |
| + DN 6 from the invoice | 10 | 6 | 0 | 4 |
| + Credit note 3, Update Stock off | 10 | 6 | 3 | 1 |
| + DN 1 | 10 | 7 | 3 | 0 |
| Invoice 10, DN 10, DN return 2 | 10 | 8 | 0 | 2 (owed again, as with Sales Orders) |
| … + credit note 2, Update Stock off | 10 | 8 | 2 | 0 |
| *Purchase only:* Invoice 10, PR 6, debit note 2 *with* stock (goods sent back) | 10 | 6 | 0 | 4 — paid for 8, holds 6−2=4, owed 4 |

## When the box is allowed (validate; off and read-only otherwise)

- Not with **Update Stock** on (the invoice delivers/receives itself), not on a **return**,
  not on **POS** invoices (`is_pos`).
- Lines that come from a **Sales Order** (`so_detail`) or **Delivery Note** (`dn_detail`) — or on
  the purchase side from a **Purchase Order** (`po_detail`) or **Purchase Receipt** (`pr_detail`) —
  never count: the order already reserves them / the goods already moved. Other lines on the
  same invoice still count.
- Non-stock items and drop-ship lines (`delivered_by_supplier`) never count.
- Every counting line needs a **warehouse** (mandatory when the box is ticked); reservation is per
  item + warehouse.
- Changing the box after submit is not allowed (only Stop / Resume).

## Settings

- **No settings page** (user's decision). Both boxes start **unticked** (field default 0). The user
  changes the default per site through **Customize Form** (Sales Invoice / Purchase Invoice →
  field → Default).
- The app's field installer must therefore **never overwrite** a default changed in Customize
  Form: on migrate it creates the fields only if missing and does not push a `default`.
- Builder-check finding behind the unticked default: on dev, ~330 of 344 recent ITEC lines on
  invoices without Update Stock never got a Delivery Note made from the invoice. Ticked by
  default, they would reserve forever. Staff tick the box only for real deliver-later sales and
  then create the Delivery Note from the invoice.

## Non-goals

- **Blocking sales of reserved stock** (available = actual − reserved). Discussed separately;
  this design only makes the numbers right.
- Reserving specific serial numbers or batches.
- Back-filling invoices submitted before go-live (their box is 0; nothing changes for them).
- Delivery Notes / Purchase Receipts *not* made from the invoice do not release it. The user must
  make them from the invoice (Create → Delivery Note), which is ERPNext's existing button.
- Changing ERPNext core files.

## Anti-goals (a failure even if it works)

- **Double counting**: an invoice line made from a Sales Order reserving on top of the order.
- **Drift**: Reserved/Ordered moving by increments that a cancel, repost or partial delivery
  could leave wrong. Always recompute from documents.
- A repost (`bench execute erpnext.stock.stock_balance.repost_stock` or the Stock Settings tools)
  erasing the invoice part.
- Any change to the invoice's accounting, SAF-T or AGT output. The fields are internal only and
  the AGT/SAF-T apps never read them.
- Slowing invoice / DN submit noticeably (the recompute is one SQL per affected item/warehouse).

## Constraints

- Frappe/ERPNext **v13 fork**, Python 3.8; commits straight to master; the user deploys production.
- `get_reserved_qty` lives in `erpnext.stock.stock_balance` and is also imported by name into
  `erpnext.selling.doctype.sales_order.sales_order`; `get_ordered_qty` likewise into
  `erpnext.buying.doctype.purchase_order.purchase_order`. Both bindings must be wrapped, using the
  app's existing runtime-patch pattern (`isoft_customization/__init__.py` + `before_request` /
  job hooks in hooks.py).
- New fields are Custom Fields created by the app (as its other features do), not core JSON edits.
- Tests: the app's rollback check-script style (`isoft_customization/tests/*_check.py`, one
  transaction rolled back). **Never `bench run-tests` without `--app`** (it wipes Item Prices).
- dev.isoft.ao has out-of-sync Sales Orders from the fork's old SI→SO bug; reserved figures there
  are already overstated by those. Tests must assert deltas, not absolute Bin values.

## UI

- Sales Invoice: `Reserve Stock` next to `Update Stock`; hidden when Update Stock / is_pos / return.
  On a submitted ticked invoice: indicator "Reserving N units" (or "Reservation stopped") and the
  Stop / Resume button under the existing actions. Purchase Invoice mirrors it ("Ordering N units").
- No new pages or reports: Stock Projected Qty, item dashboards, the POS stock column and Bin
  already show the figures.

## Left to the builder

- Field names and labels (PT translations through the app's translation file).
- Exact hook list per doctype (submit / cancel / update_after_submit of SI, PI, DN, PR and their
  returns) as long as Goal 4 holds; whether to recompute in `on_submit` or `after_commit`.
- The SQL for the invoice part (one query per item/warehouse, mirroring ERPNext's own) and how
  credited/debited quantities are summed.
- Exact indicator wording and placement.
