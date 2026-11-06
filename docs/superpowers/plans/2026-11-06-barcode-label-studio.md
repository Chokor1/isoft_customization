# Barcode Label Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A desk page `/app/barcode-label-studio` that prints item barcode labels as a PDF, one label per page at a chosen size, showing the price and today's pricing-rule discount.

**Architecture:** The server does everything that matters: it draws barcodes as SVG with an in-app encoder, prices each (item, UOM) through ERPNext's own `get_item_details`, renders a Jinja label template and turns it into a PDF with `frappe.utils.pdf.get_pdf`. The desk page only builds the list of rows and options and shows a preview.

**Tech Stack:** Frappe/ERPNext v13 fork, Python 3.8, desk Page (jQuery), wkhtmltopdf 0.12.6, PyPDF2 1.26 (tests only), Playwright (browser check).

**Spec:** `docs/superpowers/specs/2026-11-06-barcode-label-studio-design.md`

## Global Constraints

- No new Python or JS dependency (production deploys with `git pull` + `migrate` only).
- Commit straight to the default branch; every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never save or submit transactions on dev; tests roll back everything they write.
- Never run `bench run-tests` (and never without `--app`); checks are standalone scripts run from `sites/`: `../env/bin/python ../apps/isoft_customization/isoft_customization/tests/<check>.py dev.isoft.ao`.
- Server package: `isoft_customization/barcode_labels/` (beside `discount_limits.py`); DocTypes and the Page live in module `ISOFT Customization` (`isoft_customization/isoft_customization/`).
- PDF: `page-size: Custom`, `page-width`/`page-height` in mm, all four margins `"0mm"`, one label per page.
- Pricing: qty 1, transaction_date today, no customer; customer_group = picked or `"All Customer Groups"` root; territory = `"All Territories"` root; warehouse = picked or none, and with none, a discount that comes from a warehouse-scoped rule is dropped.
- A barcode's own `Item Barcode.discount` replaces the rule's discount (as POS Awesome does).
- IVA switch adds the item's rate on top (Item Tax row for the Tax Category, else the category's default Sales Taxes and Charges Template); never removes tax.
- Max 2,000 labels per PDF (copies included); requests are POST.
- Generated barcodes: EAN-13, prefix setting default `"200"`, unique in `tabItem Barcode`, type `EAN`, `posa_uom` = stock UOM when the field exists.
- Page roles: Stock User, Stock Manager, Sales User, Sales Manager, System Manager, Item Manager; every API method checks `frappe.has_permission("Item", "read")`; generate checks write on that Item. No Page class override.

## Review Focus

- An item **with no price** in the chosen list: the row is flagged and the label prints without price/discount, never "0 Kz". Pinned in Task 3 (`no_price_row`) and Task 4 (`no_price_label_has_no_price`).
- **Long item names / Portuguese accents** ("Acessórios … Proteção"): clamp to 2 lines, accents intact in the PDF. Pinned in Task 4 (`accents_survive_pdf`).
- A **barcode value that is not valid EAN/UPC** (wrong check digit, letters, 12-digit UPC-A with a bad digit): falls back to Code 128 instead of failing. Pinned in Task 1 (`bad_check_digit_falls_back`).
- A **UOM with no conversion row** on the item (like the TESTE-A..E UOMs, factor 1): still priced from the Item Price for that UOM. Pinned in Task 3 (`uom_without_conversion_row`).
- **Copies × rows above 2,000**: a clear message, no PDF attempt (would hit the 120 s worker timeout). Pinned in Task 4 (`label_cap_enforced`).

---

### Task 1: Barcode encoder

**Files:**
- Create: `isoft_customization/barcode_labels/__init__.py`, `isoft_customization/barcode_labels/encoder.py`
- Test: `isoft_customization/tests/barcode_encoder_check.py` (pure Python, no site; run `../env/bin/python ../apps/isoft_customization/isoft_customization/tests/barcode_encoder_check.py`)

**Interfaces:**
- Produces: `ean_check_digit(digits: str) -> int` (for 7/11/12-digit bodies), `detect(value: str) -> str` returning `"EAN13" | "EAN8" | "UPCA" | "CODE128"`, `encode(value: str, kind: str = None) -> list[int]` (module pattern: 1 = bar, 0 = space, including quiet zones), `to_svg(value: str, kind: str = None, height_mm: float = 10, width_mm: float = 40) -> str` (an `<svg>` with `viewBox` in modules, `preserveAspectRatio="none"`, only `<rect>` bars, no text).

- [ ] **Step 1: Write the failing check**
  - `ean_check_digit("590123412345") == 7`; `ean_check_digit("03600029145") == 2`; `ean_check_digit("9638507") == 4`.
  - `detect("5901234123457") == "EAN13"`, `detect("036000291452") == "UPCA"`, `detect("96385074") == "EAN8"`, `detect("Wikipedia") == "CODE128"`.
  - `bad_check_digit_falls_back`: `detect("5901234123458") == "CODE128"` and `detect("ABC-123") == "CODE128"`.
  - EAN-13 `encode("5901234123457")` without quiet zones has 95 modules, starts `101`, has the centre guard `01010` at modules 45–49, ends `101`.
  - UPC-A `036000291452` encodes identically to EAN-13 `0036000291452`.
  - Code 128 "Wikipedia": the symbol sequence is start B (104), the 9 characters, check symbol 1 (sum 1229 mod 103), stop. It is 11 × 11 + 13 = 134 modules.
  - Digit runs: `encode("12345678")` uses code set C (start C = 105) and is shorter than with set B.
  - `to_svg(...)` contains `<svg`, at least 20 `<rect`, no `<text`.
- [ ] **Step 2: Run it, expect FAIL** (ImportError).
- [ ] **Step 3: Implement** the signatures above. Use the standard L/G/R tables and the first-digit parity table for EAN-13, and the standard 107-pattern Code 128 table. Code set C is used for the whole value when it is an even run of 4 or more digits, otherwise set B. Use 10-module quiet zones for EAN/UPC and 10 for Code 128.
- [ ] **Step 4: Run, expect all PASS.**
- [ ] **Step 5: Commit** `Barcode Label Studio: EAN/UPC/Code128 SVG encoder`.

### Task 2: Settings DocTypes + defaults

**Files:**
- Create DocTypes (JSON + `.py`): Single `Barcode Label Settings`, child `Barcode Label Size`, under `isoft_customization/isoft_customization/doctype/`.
- Create: `isoft_customization/barcode_labels/settings.py`
- Test: `isoft_customization/tests/barcode_label_settings_check.py <site>`

**Interfaces:**
- `Barcode Label Size` fields: `label_name` (Data, reqd), `width_mm` (Float, reqd), `height_mm` (Float, reqd), `padding_mm` (Float, default 1.5), `font_size_pt` (Float, default 7), `is_default` (Check).
- `Barcode Label Settings` fields: `sizes` (Table → Barcode Label Size), `default_price_list` (Link Price List), `ean_prefix` (Data, default `200`), `show_company`, `show_item_name`, `show_item_code`, `show_barcode`, `show_barcode_digits`, `show_uom`, `show_price`, `show_discount` (Checks, default 1 except `show_company` 0, `show_uom` 0), `include_tax` (Check 0), `tax_category` (Link Tax Category), `currency_symbol` (Data, default `Kz`), `symbol_position` (Select `After`/`Before`, default After), `price_decimals` (Select `0`/`2`, default `2`). Permissions: System Manager and Stock Manager write; the roles in Global Constraints read.
- Produces: `settings.get_settings() -> dict` (uses `frappe.get_single`; when `sizes` is empty it returns the seeded three: `50×30` default, `30×50`, `50×80`), and whitelisted `settings.save_settings(doc: str JSON) -> dict` (System Manager or Stock Manager only).

- [ ] **Step 1: Write the failing check:** `get_settings()["sizes"]` has three rows with the names `50×30`, `30×50`, `50×80` and exactly one default. `ean_prefix == "200"`. Then `save_settings` with a fourth size `40×25` round-trips (it is rolled back at the end).
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Create the DocTypes** (`bench --site dev.isoft.ao migrate` syncs them; the known `seed_app_catalog` NameError at the end is pre-existing). Implement `settings.py`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `Barcode Label Studio: settings`.

### Task 3: Pricing

**Files:**
- Create: `isoft_customization/barcode_labels/pricing.py`
- Test: `isoft_customization/tests/barcode_label_pricing_check.py <site>`. It creates throwaway Item Prices and Pricing Rules on item `Test-05-11-2026` and its `TESTE-*` UOMs, and on `PAP-A4` (Box/PCS), then ends with `frappe.db.rollback()`.

**Interfaces:**
- Consumes: `settings.get_settings()`.
- Produces: `price_rows(rows: list[dict], opts: dict) -> list[dict]`. Input rows: `{item_code, barcode, uom}`, where `uom` may be None. `opts`: `{price_list, company, customer_group, warehouse, include_tax, tax_category}`. Each output row adds `uom` (resolved: the barcode's `posa_uom`, else stock UOM), `item_name`, `price_list_rate`, `discount_percentage`, `rate`, `tax_rate`, `final_price`, `currency`, `has_price` (bool), `discount_source` (`"rule" | "barcode" | None`).

- [ ] **Step 1: Write the failing checks:**
  - `rule_discount_applied`: price 1000 + a 10% rule (All Customer Groups) gives `final_price == 900` and `discount_source == "rule"`.
  - `customer_only_rule_ignored`: a 20% rule for customer "Abbass" only leaves the 10%.
  - `group_rule_only_when_picked`: a 30% rule for a child customer group applies only with `customer_group` set to it.
  - `warehouse_rule_needs_warehouse`: a 15% rule with a warehouse applies only when `opts.warehouse` is that warehouse. With none it gives `discount_percentage == 0`, or the other rule's discount if one applies.
  - `barcode_uom_price`: the PAP-A4 Box barcode `5602024006119` prices from the Box Item Price, not PCS.
  - `barcode_discount_replaces_rule`: a barcode row with `discount = 5` gives 5%, `discount_source == "barcode"`, even with the 10% rule.
  - `uom_without_conversion_row`: TESTE-B priced 2000 gives 2000.
  - `no_price_row`: an item with no Item Price in the list gives `has_price False` and `final_price None`.
  - `tax_on_top`: `include_tax` with a 14% IVA category on 900 gives `final_price == 1026`.
  - `nothing_written`: no new rows in Sales Invoice, Quotation, or Version for these documents.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Use `erpnext.stock.get_item_details.get_item_details` with these args:
  - `doctype "Sales Invoice"`, `item_code`, `company`, `selling_price_list`, `price_list_currency`, `currency` (both the list's currency), `conversion_rate 1`, `plc_conversion_rate 1`, `qty 1`, `uom`, `conversion_factor` (the item's UOM row, else 1), `transaction_date today`, `customer_group` (picked or root), `territory "All Territories"`, `warehouse`, `ignore_pricing_rule 0`.

  Then:
  - With no warehouse picked, drop the discount when any rule in `out.pricing_rules` has a warehouse.
  - When the barcode has a discount, replace the rule's discount with it.
  - Take the tax rate from Item Tax rows matching the `tax_category`, else from the category's default Sales Taxes and Charges Template.
  - Round with the price list currency precision.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `Barcode Label Studio: pricing through ERPNext get_item_details`.

### Task 4: Label rendering, PDF, barcode generation and API

**Files:**
- Create: `isoft_customization/barcode_labels/render.py`, `isoft_customization/barcode_labels/templates/label.html` (Jinja), `isoft_customization/barcode_labels/api.py`
- Test: `isoft_customization/tests/barcode_label_render_check.py <site>` (rolled back)

**Interfaces:**
- Consumes: `encoder.to_svg`, `encoder.detect`, `pricing.price_rows`, `settings.get_settings`.
- Produces (all `@frappe.whitelist()` in `api.py`, all taking/returning JSON-able values):
  - `get_page_defaults() -> {settings, company, company_logo, price_list, warehouse, currency_symbol}`
  - `search_items(txt: str, limit: int = 20) -> list[{item_code, item_name, barcodes: int}]`
  - `resolve_scan(code: str) -> {item_code, barcode, uom} | {}`
  - `rows_for_items(item_codes: str JSON) -> list[{item_code, barcode | None, uom | None}]` (one row per barcode; one barcode-less row for an item with none)
  - `rows_for_filter(item_group: str = None, brand: str = None) -> same`. Enabled, sales items only, max 500 items.
  - `price(rows: str JSON, opts: str JSON) -> pricing.price_rows output`
  - `preview_html(row: str JSON, opts: str JSON) -> str` (one label's HTML)
  - `make_pdf(rows: str JSON, opts: str JSON)`: sets `frappe.local.response.filecontent`, `filename "barcode-labels.pdf"`, `type "pdf"`. Rows carry `copies`. `opts` adds `size` (label_name) and the `show_*` flags.
  - `generate_barcode(item_code: str) -> {barcode, uom}`
- `render.label_html(row: dict, opts: dict, size: dict) -> str` and `render.document_html(rows, opts, size) -> str`. Each label is a `div` of exactly `width_mm × height_mm` with `page-break-after: always`. The fonts are the system sans used by frappe PDFs. The SVG barcode is sized to the label width minus padding, and to about 35% of the height. A discount shows the struck-through `price_list_rate`, the `-N%` and the `final_price`.

- [ ] **Step 1: Write the failing checks:**
  - `pdf_pages_and_size`: 2 rows × copies (2, 1) at the size 50×30 gives a PDF (PyPDF2) with 3 pages, each mediabox 141.7 × 85.0 pt (±1).
  - `toggles_respected`: with `show_price 0`, the HTML has no currency symbol. With `show_item_code 0`, the item code text is absent.
  - `no_price_label_has_no_price`: a `has_price False` row's HTML has no currency symbol.
  - `accents_survive_pdf`: an item name with "ção" gives PDF text (PyPDF2 `extractText`) containing "ção", or the HTML as passed to `get_pdf` is UTF-8 with `<meta charset="utf-8">`.
  - `label_cap_enforced`: 2,001 copies raises `frappe.ValidationError` before `get_pdf` runs (patch `get_pdf` to assert it is not called).
  - `generate_barcode_unique`: on an item with no barcode the value is 13 digits, starts `200`, has a valid check digit and is not already in `tabItem Barcode`. The item now has it, with type EAN. A second call gives a different value.
  - `generate_needs_write`: as a user without Item write it raises `frappe.PermissionError` (use `frappe.set_user` on an existing Sales User test user. If none exists, skip with a note, and never mint sessions as real people).
  - `permission_checked`: `price` as Guest raises `frappe.PermissionError`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** The barcode sequence is `max(existing 200xxxxxxxxx bodies) + 1`, re-checked for uniqueness in a loop. The Item is saved with `item.append("barcodes", …)` + `item.save()`.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `Barcode Label Studio: labels, PDF and barcode generation`.

### Task 5: The desk page

**Files:**
- Create: `isoft_customization/isoft_customization/page/barcode_label_studio/{__init__.py, barcode_label_studio.json, barcode_label_studio.js, barcode_label_studio.css}`
- Modify: `isoft_customization/translations/pt.csv` (append the page's strings, quoting any with commas)
- Test: `isoft_customization/tests/browser_barcode_label_studio.py` (Playwright, Administrator session via `browser_target_total.mint_session()`, nothing saved except the throwaway barcode generation, which the check removes again)

**Interfaces:**
- Consumes: every `api.py` method from Task 4 and `settings.save_settings` from Task 2.
- Page JSON: name/page_name `barcode-label-studio`, title "Barcode Label Studio", module "ISOFT Customization", the roles in Global Constraints, `modified` set to the commit time. The page JS is cached forever unless developer_mode (see memory `frappe-page-js-localstorage-cache`). Dev has developer_mode on; for production the JSON `modified` must be new.

- [ ] **Step 1: Write the failing browser check:**
  - The page loads with no page errors.
  - Scanning `5602024006119` adds one row PAP-A4 / Box with a price.
  - "Add by filter" with an item group adds rows.
  - Setting copies to 3 makes the label count read 4 or more.
  - Switching "Price" off removes the price from the preview.
  - Changing the size to 30×50 changes the preview aspect to portrait.
  - "Print PDF" opens a response whose `content-type` is `application/pdf`.
  - The gear opens the settings dialog.
- [ ] **Step 2: Run, expect FAIL** (page not found).
- [ ] **Step 3: Build the page:**
  - **Top bar:** Price List, Label Size, Store (Warehouse), Customer Group, IVA switch + Tax Category, a "Fields" dropdown of the `show_*` switches, the gear, and the primary button "Print PDF".
  - **Add bar:** item search (Link Item), a scan box (Enter → `resolve_scan`), "Add by filter" dialog (Item Group, Brand).
  - **Rows table:** item, barcode (or a "Generate EAN-13" button), UOM, price, discount, final, copies, remove; "copies for all"; rows without a price shown orange.
  - **Preview:** of the selected row (default the first), using `preview_html`, debounced.
  - Prices are refreshed through `price` whenever the price list, store, group or IVA options change.
  - Print posts a form to `/api/method/isoft_customization.barcode_labels.api.make_pdf` with `target=_blank` (`open_url_post`).
  - The look follows Invenza (slate palette, compact), like the Pricing Rules Manager page.
- [ ] **Step 4: Run, expect PASS; also run Tasks 1–4 checks again.**
- [ ] **Step 5: Commit** `Barcode Label Studio page`. Then update memory `isoft-customization-app` with one line about the page.
