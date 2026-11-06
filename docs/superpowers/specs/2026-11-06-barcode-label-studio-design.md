# Barcode Label Studio — design

Date: 2026-11-06 · App: isoft_customization · Route: `/app/barcode-label-studio`

## Intent

Shops need barcode stickers for their items: to stick on products and shelves so the POS and
the sales documents can scan them, showing the price a customer will actually pay today.
Today nothing does this. The Item Labels page (POS Awesome) exports price labels to Excel with
no barcode. The Barcode Discount Generator prints one discount barcode per document. The old
"Barcode Generation Tool" was a dead stub and has been removed (patch `remove_advance_tools_module`).

## Goals

- One desk page where the user builds a list of labels and gets **one PDF**, **one label per
  page**, at a **label size chosen from a saved list** (e.g. 30×50 mm, 50×80 mm).
- The label content is **dynamic**: each element can be switched on or off: company name/logo,
  item name, item code, barcode graphic, barcode digits, UOM, price, discount, final price.
- **Price** = the item's rate on the chosen **Price List** for the barcode's UOM.
  **Discount** = the **pricing rule that applies on the print date**, evaluated by ERPNext's own
  pricing engine for **qty 1 with no customer** (only rules valid for everyone). An optional
  **Customer Group** narrows it to rules for that group (e.g. wholesale labels).
  *"Valid for everyone" includes rules set to the root groups.* The fork's `get_other_conditions`
  keeps only rules with an empty customer group/territory when none is passed, yet 9 of the 13
  active selling rules on dev say "All Customer Groups", and the till applies them (its walk-in
  customer is in that group). So when the picker is empty, `pricing.py` passes the root Customer
  Group and the root Territory. Rules for a specific customer stay out. (Builder call, following
  the agreed "rules for all customers".)
- An optional **Warehouse (store)** picker, defaulting to the user's default warehouse, is
  passed to the pricing engine so warehouse-scoped rules (6 active on dev) apply only to that
  store's labels. With it empty, warehouse-scoped rules are skipped. (Builder call.)
- A barcode row with its own **UOM** (`Item Barcode.posa_uom`) prints that UOM's price (Box
  barcode → Box price), matching what scanning it gives in the POS and on invoices.
- A barcode row with its own **discount** (`Item Barcode.discount`, the Barcode Discount
  Generator ones) shows that discount **instead of** the pricing rule's. That is what POS Awesome
  does: `Invoice.vue update_item_detail` applies the rule first, then overwrites
  `discount_percentage` with the barcode's discount whenever it has one.
- **Optional IVA**: a "price includes IVA" switch with a Tax Category. On it, the item's IVA rate
  (Item Tax row for the category, else the category's default Sales Taxes template) is **added on
  top** of the discounted price. That fits how dev prices today: every template has
  `included_in_print_rate = 0`, so list prices are without IVA. A price list that already
  includes IVA is printed with the switch off. (Builder call; no add/remove logic.)
- Items **without a barcode** can get a **new EAN-13** generated and saved to the item's barcode
  table (type EAN, UOM = stock UOM) from the page, before printing.

## Non-goals

- No thermal-printer drivers (ZPL/EPL) and no direct printing; the PDF is printed from the browser.
- No QR codes (can come later; `qrcode` is already installed).
- No change to the Item Labels page, the Barcode Discount Generator or their print formats.
- No list-view bulk print (the user declined bulk-print work on 2026-10-29).

## Anti-goals

- A label showing a price the till won't charge. The price must come from ERPNext's own
  price list and pricing rule functions, never re-implemented rules.
- Saving or changing prices, pricing rules or transactions. The only write is a generated barcode.
- Anything that needs `pip install` on production: the user deploys with `git pull` + `migrate`.

## Constraints

- Frappe/ERPNext v13 fork, Python 3.8, desk Page (not Vue). Committed straight to the default branch.
- PDF through `frappe.utils.pdf.get_pdf` (wkhtmltopdf 0.12.6 patched qt) with
  `page-size: Custom`, `page-width`/`page-height` in mm and margins `0mm`.
- Barcodes drawn **server-side as inline SVG** (wkhtmltopdf's old WebKit can't be trusted with
  JsBarcode), so the PDF is identical everywhere.
- Look follows the Invenza style (slate palette, compact), like the Pricing Rules Manager page.
- Page access: the Page's role list (Stock User, Stock Manager, Sales User, Sales Manager,
  System Manager, Item Manager). Every API method also checks `frappe.has_permission("Item", "read")`;
  generating a barcode checks write on that Item. No Page class override: isoft_permission_manager
  already overrides Page, and a second override would break it.

## Approaches

1. **Server PDF + own barcode encoder (chosen).** We write a small, self-contained encoder for
   EAN-13, EAN-8, UPC-A and Code 128 (any other value) that outputs SVG bars. The page posts
   the label list; the server prices, renders HTML and returns the PDF. Same output everywhere,
   large batches fine, no new dependency. Cost: ~200 lines of encoder, tested against known
   reference encodings and check digits.
2. Server PDF with the `python-barcode` library: less code, but a new dependency that
   production must install, or the page breaks after a pull.
3. Browser PDF (JsBarcode + vendored jsPDF): instant preview but slow for hundreds of labels
   and weak with Portuguese accents and fonts.

A print format on Item was ruled out: one item at a time, no copies, no size picked at print time.

The user picked approach 1, via "do that" on the recommendation.

## The design

### Settings: Single `Barcode Label Settings`
- Child table `Barcode Label Size`: label name, width mm, height mm, padding mm, base font
  size, default. Seeded with **50×30 mm**, **30×50 mm** (portrait) and **50×80 mm**.
- Defaults: price list, show-element switches, IVA switch + tax category, currency symbol
  and position (before/after), decimals (0/2).
- Opened from a gear button on the page (same pattern as Pricing Assistant Settings).

### Page `barcode-label-studio`
- **Top bar:** Price List, Label Size, Customer Group (optional), "Price includes IVA"
  + Tax Category, Company (logo/name source), and a "Fields" dropdown of on/off switches.
- **Add items:** an item search, a scan box (a barcode resolves to that exact barcode row and
  its UOM), and "Add by filter" (Item Group, Brand; max 500 items). Each item adds **one row per
  barcode** it has; an item with none gets a "no barcode" row with a **Generate EAN-13** button.
- **Rows table:** item, barcode, UOM, price, discount %, final price (all live from the server),
  copies (default 1), remove. Bulk "copies for all". Rows whose price is missing are flagged
  (orange) and still printable without a price.
- **Preview:** one label drawn at the true aspect ratio from the same server HTML as the PDF.
- **Print PDF:** posts the rows and options; the server returns the PDF, opened in a new tab
  for printing. The request is a POST, never a GET with names in the URL (4094-byte gunicorn
  limit), capped at 2,000 labels per PDF (copies included) to stay well inside the 120 s timeout.

### Server `isoft_customization/barcode_labels/`
- `encoder.py`: `encode(value, kind=None) -> list of bar widths` + `to_svg(...)`. EAN-13/UPC-A/
  EAN-8 when the value is the right length of digits with a valid check digit, otherwise
  Code 128 (subset B, switching to C for digit runs). `ean13_check_digit()`.
- `pricing.py`: for each (item, uom) call ERPNext `get_item_details` (doctype "Sales Invoice"
  semantics: selling price list, company, transaction_date today, qty 1, uom and its
  conversion_factor, customer empty, customer_group = picked or root, territory = root,
  warehouse = picked or none). Take `price_list_rate`,
  `discount_percentage`/`discount_amount` and the resulting rate; apply the barcode discount;
  then optional IVA from the item's tax template for the tax category, or the
  category's default template.
- `api.py` (whitelisted): `get_page_defaults`, `search_items`, `resolve_scan`, `rows_for_items`,
  `rows_for_filter`, `price_rows`, `generate_barcode(item_code)`, `preview_html`, `make_pdf`.
- `generate_barcode`: the EAN-13 prefix is a setting (default `200`, the GS1 in-store range,
  so it never collides with a manufacturer code). The next free 9-digit sequence + check digit
  is checked unique across `tabItem Barcode`, then appended to the Item and saved.
- Label HTML: a Jinja template with absolute mm sizing, the SVG barcode scaled to the label
  width, long item names clamped to two lines; the price struck through when a discount applies.

### Tests
- `tests/barcode_encoder_check.py`: check digits and bar patterns against published examples
  (EAN-13 5901234123457, UPC-A 036000291452, Code 128 "Wikipedia"); width/quiet zone.
- `tests/barcode_label_pricing_check.py`: on dev, an item with a price-list price and a pricing
  rule shows the discounted price; an "All Customer Groups" rule applies with no group picked;
  a customer-only rule is ignored; a specific customer-group rule is used only when that group is
  picked; a warehouse rule applies only with that warehouse; a Box barcode prints the Box price;
  the barcode discount replaces the rule's. All
  rolled back, nothing saved.
- `tests/browser_barcode_label_studio.py`: Playwright as Administrator: add by scan, toggle
  fields, preview, and the PDF has N pages of the chosen size (PyPDF2 mediabox).

## Left to the builder

Exact page styling within the Invenza look; the Code 128 subset-switch heuristic; how many rows
before the table virtualises; preview debounce timing; Portuguese strings in `translations/pt.csv`.
