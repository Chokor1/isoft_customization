// Credit Note Assistant
//
// The customer sends a list of items and quantities to credit. The page is four steps,
// top to bottom:
//   1 Customer     company, customer and optional date range
//   2 Items        search only offers items this customer can still credit; picking one
//                  adds it at once (qty 1) and puts the cursor on its quantity
//   3 Invoice      refreshed automatically: the customer's invoices that still hold
//                  returnable quantity for the listed items
//   4 Credit note  the chosen invoice's lines pre-filled up to what is still to credit;
//                  opens an unsaved credit note with only those lines and quantities
// One credit note per invoice: pick the next invoice for whatever is left.
// Server side: isoft_customization/credit_note_assistant.py
//
// Every dropdown on the page gets a z-index above the step cards, and no control sits
// inside a scrolling container, so a list can never open underneath another section.

const CNBI_METHOD = "isoft_customization.credit_note_assistant.";
const CNBI_STORE = "isoft_cnbi_state";

frappe.pages["credit-note-assistant"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Credit Note Assistant"),
		single_column: true,
	});
	wrapper.cnbi = new CreditNoteByItems(page);
};

frappe.pages["credit-note-assistant"].on_page_show = function (wrapper) {
	// back from a credit note form: quantities may have changed
	if (wrapper.cnbi) wrapper.cnbi.on_show();
};

// A credit note opened from this page is saved in the Sales Invoice form (saft_xml
// submits it on that first save). Offer the way back, and have the page refresh its
// invoice list as soon as it is shown again.
frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		const tool = CreditNoteByItems.instance;
		if (tool) tool.on_invoice_form(frm);
	},
});

class CreditNoteByItems {
	constructor(page) {
		this.page = page;
		this.state = Object.assign(
			{ company: "", customer: "", from_date: "", to_date: "", items: [], since: null,
				selected: null, reason: "", warehouse: "" },
			this.load_state()
		);
		this.state.items = (this.state.items || []).filter((r) => r.item_code);
		if (!this.state.from_date && !this.state.to_date) this.set_default_dates();
		CreditNoteByItems.instance = this;
		this.dirty = false;
		this.opened = null; // {invoice, customer} of the credit note last opened from here
		this.result = null;
		this.alloc = {};
		this.request_no = 0;
		this.sugg_no = 0;
		this.suggestions_by_code = {};
		this.make_styles();
		this.make_layout();
		this.make_customer_step();
		this.make_item_search();
		this.make_credit_note_step();
		this.page.set_secondary_action(__("New List"), () => this.new_list(), "refresh");
		this.render_all();
		if (this.ready() && this.state.items.length) this.search();

		// any Sales Invoice saved anywhere (another tab, another user): refresh the list
		frappe.realtime.on("list_update", (data) => {
			if (!data || data.doctype !== "Sales Invoice") return;
			if (this.is_visible()) this.schedule_search();
			else this.dirty = true;
		});
	}

	set_default_dates() {
		// last 30 days, today included
		this.state.to_date = frappe.datetime.get_today();
		this.state.from_date = frappe.datetime.add_days(this.state.to_date, -30);
	}

	is_visible() {
		return frappe.get_route_str() === "credit-note-assistant";
	}

	on_show() {
		if (!this.ready() || !this.state.items.length) return;
		clearTimeout(this.search_timer);
		this.search().then(() => {
			if (this.saved_credit_note) {
				frappe.show_alert({
					message: __("Credit note {0} saved. The invoice list is updated.", [this.saved_credit_note]),
					indicator: "green",
				}, 6);
				this.saved_credit_note = null;
			}
		});
		this.dirty = false;
	}

	on_invoice_form(frm) {
		const d = frm.doc;
		if (!this.opened || !cint(d.is_return) || d.return_against !== this.opened.invoice) return;
		if (d.docstatus === 1) {
			this.dirty = true;
			this.saved_credit_note = d.name;
		}
		frm.add_custom_button(__("Back to Credit Note Assistant"), () => frappe.set_route("credit-note-assistant"));
	}

	// ---------------------------------------------------------------- state

	load_state() {
		try {
			return JSON.parse(localStorage.getItem(CNBI_STORE) || "{}") || {};
		} catch (e) {
			return {};
		}
	}

	save_state() {
		try {
			localStorage.setItem(CNBI_STORE, JSON.stringify(this.state));
		} catch (e) {
			// private window or blocked storage: the page still works, it just forgets
		}
	}

	ready() {
		return !!(this.state.company && this.state.customer);
	}

	// a document link that opens in a new tab, so the page keeps its place
	link(doctype, name, css) {
		return `<a class="cnbi-link ${css || ""}" href="${frappe.utils.get_form_link(doctype, name)}" target="_blank"
			title="${__("Open {0} in a new tab", [frappe.utils.escape_html(name)])}">${frappe.utils.escape_html(name)}</a>`;
	}

	scope() {
		const f = { company: this.state.company, customer: this.state.customer };
		if (this.state.from_date) f.from_date = this.state.from_date;
		if (this.state.to_date) f.to_date = this.state.to_date;
		return f;
	}

	clean_items() {
		return this.state.items
			.filter((r) => r.item_code && flt(r.qty) > 0)
			.map((r) => ({ item_code: r.item_code, qty: flt(r.qty) }));
	}

	// ---------------------------------------------------------------- layout

	make_styles() {
		if (document.getElementById("cnbi-styles")) document.getElementById("cnbi-styles").remove();
		const css = `
		.cnbi-wrap { max-width: 1400px; margin: 0 auto 40px; }
		.cnbi-step { background: var(--card-bg, #fff); border: 1px solid var(--border-color, #e2e6ea);
			border-radius: 12px; padding: 18px 20px; margin-bottom: 16px; }
		.cnbi-step.is-locked > :not(.cnbi-step-head) { opacity: .45; pointer-events: none; }
		.cnbi-step-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
		.cnbi-step-head h5 { margin: 0; font-size: 15px; font-weight: 600; }
		.cnbi-step-sub { color: var(--text-muted, #8d99a6); font-size: 12px; }
		.cnbi-step-head .cnbi-right { margin-left: auto; display: flex; align-items: center; gap: 8px; }
		.cnbi-num { width: 26px; height: 26px; border-radius: 50%; display: inline-flex; align-items: center;
			justify-content: center; font-weight: 700; font-size: 13px; flex: none;
			background: var(--blue-500, #2490ef); color: #fff; }
		.cnbi-step.is-locked .cnbi-num { background: var(--gray-300, #d1d8dd); color: var(--gray-700, #4c5a67); }
		.cnbi-step.is-done .cnbi-num { background: var(--green-500, #2ea043); }
		.cnbi-muted { color: var(--text-muted, #8d99a6); font-size: 12px; }
		.cnbi-wrap a.cnbi-link { color: var(--blue-600, #1a73e8); text-decoration: none; }
		.cnbi-wrap a.cnbi-link:hover { text-decoration: underline; }

		/* dropdowns above every card, whatever opens them */
		.cnbi-wrap .awesomplete > ul { z-index: 1030 !important; }

		.cnbi-scope { display: grid; grid-template-columns: 1fr 1.4fr 1fr 1fr; gap: 14px; }
		@media (max-width: 900px) { .cnbi-scope { grid-template-columns: 1fr 1fr; } }
		@media (max-width: 520px) { .cnbi-scope { grid-template-columns: 1fr; } }
		.cnbi-scope .frappe-control, .cnbi-scope .form-group { margin-bottom: 0; }

		.cnbi-lock { padding: 10px 12px; margin-bottom: 12px; border-radius: 8px; font-weight: 600;
			background: var(--yellow-50, #fffbeb); color: var(--yellow-800, #8a6100); }

		.cnbi-search-box { position: relative; margin-bottom: 14px; }
		.cnbi-search-box .awesomplete { display: block; }
		.cnbi-search-box input.cnbi-search { height: 40px; font-size: 14px; padding-left: 36px;
			background: var(--card-bg, #fff); border: 1px solid var(--border-color, #d1d8dd); }
		.cnbi-search-box input.cnbi-search:focus { border-color: var(--blue-500, #2490ef);
			box-shadow: 0 0 0 2px rgba(36, 144, 239, .15); }
		.cnbi-search-icon { position: absolute; left: 12px; top: 11px; color: var(--text-muted, #8d99a6);
			pointer-events: none; z-index: 1; }
		.cnbi-search-box .awesomplete > ul { max-height: 360px; overflow-y: auto; }
		.cnbi-sugg { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; }
		.cnbi-sugg b { white-space: nowrap; }
		.cnbi-sugg .cnbi-sugg-name { color: var(--text-muted, #6c7680); font-size: 12px; flex: 1; min-width: 0;
			overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
		.cnbi-sugg .cnbi-sugg-qty { font-size: 12px; white-space: nowrap; color: var(--green-700, #2d7a46); font-weight: 600; }
		.cnbi-sugg.is-listed .cnbi-sugg-qty { color: var(--text-muted, #8d99a6); }

		.cnbi-table-wrap { overflow: auto; border: 1px solid var(--border-color, #e2e6ea); border-radius: 8px;
			position: relative; z-index: 0; }
		.cnbi-scroll { max-height: 46vh; }
		table.cnbi-table { width: 100%; border-collapse: collapse; font-size: 13px; }
		table.cnbi-table th, table.cnbi-table td { padding: 8px 10px; border-bottom: 1px solid var(--border-color, #edf0f2);
			text-align: left; vertical-align: middle; }
		table.cnbi-table thead th { background: var(--subtle-fg, #f4f5f6); font-weight: 600;
			color: var(--text-muted, #6c7680); white-space: nowrap; position: sticky; top: 0; z-index: 1; }
		table.cnbi-table td.num, table.cnbi-table th.num { text-align: right; white-space: nowrap; }
		table.cnbi-table tr:last-child td { border-bottom: 0; }
		table.cnbi-table td.cnbi-code { font-weight: 600; white-space: nowrap; }
		table.cnbi-table input.cnbi-qty { width: 96px; text-align: right; margin-left: auto; display: inline-block;
			background: var(--card-bg, #fff); border: 1px solid var(--border-color, #d1d8dd); }
		table.cnbi-table input.cnbi-qty:focus { border-color: var(--blue-500, #2490ef); }
		.cnbi-name { color: var(--text-muted, #8d99a6); font-size: 11px; margin-top: 2px; }
		.cnbi-x { cursor: pointer; color: var(--text-muted, #8d99a6); font-size: 18px; line-height: 1; padding: 0 4px; }
		.cnbi-x:hover { color: var(--red-500, #e24c4c); }
		.cnbi-empty { padding: 26px 12px; text-align: center; color: var(--text-muted, #8d99a6); }
		tr.cnbi-active td { background: rgba(46, 160, 67, 0.07); }
		tr.cnbi-flash td { background: rgba(36, 144, 239, 0.14); transition: background .6s; }

		.cnbi-pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px;
			font-weight: 600; white-space: nowrap; }
		.cnbi-pill.on { background: var(--green-100, #e4f5e9); color: var(--green-700, #2d7a46); }
		.cnbi-pill.off { background: var(--gray-100, #f4f5f6); color: var(--text-muted, #8d99a6); }
		.cnbi-pill.warn { background: var(--yellow-100, #fff5d6); color: var(--yellow-800, #8a6100); }
		.cnbi-pill.bad { background: var(--red-100, #fde8e8); color: var(--red-600, #c53030); }

		.cnbi-inv-list { max-height: 440px; overflow: auto; border: 1px solid var(--border-color, #e2e6ea); border-radius: 8px; }
		.cnbi-inv { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; gap: 10px; align-items: start;
			padding: 10px 14px; border-bottom: 1px solid var(--border-color, #edf0f2); cursor: pointer; }
		.cnbi-inv:last-child { border-bottom: 0; }
		.cnbi-inv:hover { background: var(--subtle-fg, #f7f8f9); }
		.cnbi-inv.selected { background: var(--blue-50, #edf5ff); box-shadow: inset 3px 0 0 var(--blue-500, #2490ef); }
		.cnbi-inv-title { font-weight: 600; }
		.cnbi-inv-items { margin-top: 4px; display: flex; flex-wrap: wrap; gap: 4px; }
		.cnbi-inv-right { text-align: right; white-space: nowrap; }
		.cnbi-filter { max-width: 220px; }
		.cnbi-loading { font-size: 12px; color: var(--text-muted, #8d99a6); }

		.cnbi-opts { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 14px; }
		@media (max-width: 700px) { .cnbi-opts { grid-template-columns: 1fr; } }
		.cnbi-opts .frappe-control { margin-bottom: 0; }
		.cnbi-reason textarea { height: 64px !important; min-height: 64px; }
		.cnbi-foot { display: flex; gap: 12px; align-items: center; justify-content: space-between;
			flex-wrap: wrap; margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--border-color, #edf0f2); }
		.cnbi-total { font-size: 16px; font-weight: 700; }
		.cnbi-note { font-size: 12px; color: var(--text-muted, #8d99a6); margin-top: 8px; }
		.cnbi-made { margin-top: 14px; font-size: 12px; }
		.cnbi-made a { font-weight: 600; margin-right: 6px; }
		`;
		$(`<style id="cnbi-styles">${css}</style>`).appendTo("head");
	}

	make_layout() {
		this.$body = $(`
			<div class="cnbi-wrap">
				<section class="cnbi-step cnbi-s1">
					<div class="cnbi-step-head">
						<span class="cnbi-num">1</span>
						<h5>${__("Customer")}</h5>
						<span class="cnbi-step-sub">${__("Who the credit note is for. The dates are optional and limit which invoices are used.")}</span>
					</div>
					<div class="cnbi-scope">
						<div class="cnbi-f-company"></div>
						<div class="cnbi-f-customer"></div>
						<div class="cnbi-f-from"></div>
						<div class="cnbi-f-to"></div>
					</div>
				</section>

				<section class="cnbi-step cnbi-s2">
					<div class="cnbi-step-head">
						<span class="cnbi-num">2</span>
						<h5 class="cnbi-items-title">${__("Items to credit")}</h5>
						<span class="cnbi-step-sub">${__("Pick an item and it is added. Then type the quantity and press Enter to pick the next one.")}</span>
						<span class="cnbi-right cnbi-since cnbi-muted"></span>
					</div>
					<div class="cnbi-lock">${__("Choose the customer in step 1 first.")}</div>
					<div class="cnbi-search-box">
						<span class="cnbi-search-icon">${frappe.utils.icon("search", "sm")}</span>
						<input type="text" class="form-control cnbi-search" autocomplete="off"
							placeholder="${__("Search the items this customer can credit: code or name")}">
					</div>
					<div class="cnbi-table-wrap cnbi-scroll">
						<table class="cnbi-table">
							<thead><tr>
								<th style="width:36px">#</th>
								<th>${__("Item")}</th>
								<th>${__("Item Name")}</th>
								<th class="num">${__("Can credit")}</th>
								<th class="num">${__("Qty to credit")}</th>
								<th class="num" title="${__("On credit notes submitted for this customer since the list was started")}">${__("Still to credit")}</th>
								<th>${__("On selected invoice")}</th>
								<th style="width:32px"></th>
							</tr></thead>
							<tbody class="cnbi-items"></tbody>
						</table>
					</div>
				</section>

				<section class="cnbi-step cnbi-s3">
					<div class="cnbi-step-head">
						<span class="cnbi-num">3</span>
						<h5 class="cnbi-inv-title-h">${__("Choose the invoice")}</h5>
						<span class="cnbi-step-sub">${__("Invoices of this customer that still have these items to credit. Most matching items first.")}</span>
						<span class="cnbi-right">
							<span class="cnbi-loading"></span>
							<input type="text" class="form-control input-xs cnbi-filter" placeholder="${__("Filter by invoice number")}">
						</span>
					</div>
					<div class="cnbi-inv-list"></div>
					<div class="cnbi-muted cnbi-trunc" style="margin-top:6px"></div>
				</section>

				<section class="cnbi-step cnbi-s4" style="display:none">
					<div class="cnbi-step-head">
						<span class="cnbi-num">4</span>
						<h5 class="cnbi-sel-title"></h5>
						<span class="cnbi-right cnbi-sel-meta cnbi-muted"></span>
					</div>
					<div class="cnbi-table-wrap">
						<table class="cnbi-table">
							<thead><tr>
								<th style="width:28px"></th>
								<th>${__("Line")}</th>
								<th>${__("Item")}</th>
								<th class="num">${__("Sold")}</th>
								<th class="num">${__("Already credited")}</th>
								<th class="num">${__("Can credit")}</th>
								<th class="num">${__("Credit now")}</th>
								<th class="num">${__("Rate")}</th>
								<th class="num">${__("Amount")}</th>
							</tr></thead>
							<tbody class="cnbi-lines"></tbody>
						</table>
					</div>
					<div class="cnbi-opts">
						<div class="cnbi-reason"></div>
						<div class="cnbi-warehouse"></div>
					</div>
					<div class="cnbi-foot">
						<div><span class="cnbi-muted">${__("Credit value excl. taxes")}</span>
							<div class="cnbi-total"></div></div>
						<button class="btn btn-primary cnbi-open">${__("Open Credit Note")}</button>
					</div>
					<div class="cnbi-note">${__("The credit note opens unsaved. Saving it submits it and sends it to AGT, so check it in the form first.")}</div>
					<div class="cnbi-made" style="display:none"></div>
				</section>
			</div>`).appendTo(this.page.main);

		// The desk router opens every /app link in the same tab and ignores target="_blank";
		// catch the page's own links first so the document opens beside the assistant.
		this.$body.on("click", "a.cnbi-link", (e) => {
			if (e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0) return;
			e.preventDefault();
			e.stopPropagation();
			window.open(e.currentTarget.href, "_blank", "noopener");
		});
		this.$body.find(".cnbi-filter").on("input", () => this.render_invoices());
		this.$body.find(".cnbi-open").on("click", () => this.open_credit_note());
	}

	make_customer_step() {
		const make = (sel, df) => {
			const ctrl = frappe.ui.form.make_control({
				parent: this.$body.find(sel),
				df: Object.assign({}, df, { change: () => this.on_scope_change(df.fieldname, ctrl.get_value()) }),
				render_input: true,
			});
			ctrl.set_value(this.state[df.fieldname] || df.default || "");
			return ctrl;
		};
		if (!this.state.company) this.state.company = frappe.defaults.get_user_default("Company") || "";
		this.f_company = make(".cnbi-f-company", {
			fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1,
		});
		this.f_customer = make(".cnbi-f-customer", {
			fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer", reqd: 1,
		});
		this.f_from = make(".cnbi-f-from", { fieldname: "from_date", label: __("From Date"), fieldtype: "Date" });
		this.f_to = make(".cnbi-f-to", { fieldname: "to_date", label: __("To Date"), fieldtype: "Date" });
	}

	on_scope_change(fieldname, value) {
		value = value || "";
		if ((this.state[fieldname] || "") === value) return;
		this.state[fieldname] = value;
		if (fieldname === "company" || fieldname === "customer") {
			// results and progress belonged to the previous customer
			this.state.selected = null;
			this.state.since = null;
			this.result = null;
			this.alloc = {};
		}
		this.suggestions_by_code = {};
		this.save_state();
		this.render_all();
		this.schedule_search();
		if (fieldname === "customer" && value && !this.state.items.length) {
			setTimeout(() => this.$search.focus(), 200);
		}
	}

	// ---------------------------------------------------------------- step 2: items

	make_item_search() {
		this.$search = this.$body.find("input.cnbi-search");
		this.awesomplete = new Awesomplete(this.$search.get(0), {
			minChars: 0,
			maxItems: 50,
			autoFirst: true,
			list: [],
			filter: () => true,
			sort: () => 0,
			replace: () => {}, // the box is cleared once the item is added
			item: (text) => {
				const code = String(text.value !== undefined ? text.value : text);
				const d = this.suggestions_by_code[code] || {};
				const listed = this.state.items.some((r) => r.item_code === code);
				const right = listed ? __("on the list") : __("can credit {0}", [format_number(d.creditable)]);
				return $(`<li><a><div class="cnbi-sugg ${listed ? "is-listed" : ""}">
					<b>${frappe.utils.escape_html(code)}</b>
					<span class="cnbi-sugg-name">${frappe.utils.escape_html(d.item_name || "")}</span>
					<span class="cnbi-sugg-qty">${right}</span></div></a></li>`).get(0);
			},
		});

		const load = frappe.utils.debounce(() => this.load_suggestions(), 250);
		this.$search.on("input", load);
		this.$search.on("focus", () => this.ready() && this.load_suggestions());
		this.$search.on("awesomplete-selectcomplete", (e) => {
			const t = e.originalEvent && e.originalEvent.text;
			const code = t && (t.value !== undefined ? t.value : t);
			this.$search.val("");
			if (code) this.add_item(String(code));
		});
	}

	load_suggestions() {
		if (!this.ready()) return;
		const txt = this.$search.val() || "";
		const no = ++this.sugg_no;
		frappe.call({
			method: CNBI_METHOD + "search_items",
			args: Object.assign({ txt }, this.scope()),
			no_spinner: true,
			callback: (r) => {
				if (no !== this.sugg_no) return; // an older request answered late
				const rows = r.message || [];
				rows.forEach((d) => (this.suggestions_by_code[d.item_code] = d));
				this.awesomplete.list = rows.map((d) => d.item_code);
				if (!rows.length) {
					this.awesomplete.close();
					if (txt) {
						frappe.show_alert({
							message: __("No item matching {0} is left to credit for this customer.", [frappe.utils.escape_html(txt)]),
							indicator: "orange",
						}, 4);
					}
					return;
				}
				if (document.activeElement === this.$search.get(0)) this.awesomplete.evaluate();
			},
		});
	}

	add_item(code) {
		if (!this.ready()) return;
		this.awesomplete.close();
		const existing = this.state.items.find((r) => r.item_code === code);
		if (existing) {
			this.render_items(code);
			this.focus_qty(code);
			frappe.show_alert({ message: __("{0} is already on the list. Change its quantity there.", [code]), indicator: "blue" }, 4);
			return;
		}
		const d = this.suggestions_by_code[code];
		if (!d) return;
		this.state.items.push({ item_code: code, item_name: d.item_name, qty: 1, creditable: flt(d.creditable) });
		this.save_state();
		this.render_all(code);
		this.focus_qty(code);
		this.schedule_search();
	}

	focus_qty(code) {
		const $input = this.$body.find(".cnbi-items tr").filter((i, tr) => tr.dataset.code === code).find("input.cnbi-qty");
		if ($input.length) {
			$input.get(0).scrollIntoView({ block: "nearest" });
			setTimeout(() => $input.focus().select(), 30);
		}
	}

	// Rows are rebuilt only when the list itself changes. A search result arriving while
	// the user types a quantity just refreshes the figures in place, so no keystroke is
	// lost and the cursor stays put.
	render_items(flash_code) {
		const $tb = this.$body.find(".cnbi-items");
		const n = this.state.items.length;
		this.$body.find(".cnbi-items-title").text(n ? __("Items to credit ({0})", [n]) : __("Items to credit"));

		if (!n) {
			$tb.html(`<tr><td colspan="8" class="cnbi-empty">${__("No items yet. Search above and pick an item to add it.")}</td></tr>`);
			return;
		}

		const shown = $tb.find("tr[data-code]").map((i, tr) => tr.dataset.code).get();
		const same = !flash_code && shown.length === n && this.state.items.every((r, i) => r.item_code === shown[i]);
		if (!same) {
			$tb.empty();
			this.state.items.forEach((row, i) => $tb.append(this.make_item_row(row, i, row.item_code === flash_code)));
		}

		const info = {};
		(this.result ? this.result.items : []).forEach((r) => (info[r.item_code] = r));
		const inv = this.selected_invoice();
		$tb.find("tr[data-code]").each((i, tr) => {
			const row = this.state.items[i];
			if (row) this.fill_item_row($(tr), row, info[row.item_code], inv);
		});
	}

	make_item_row(row, i, flash) {
		const $tr = $(`
			<tr class="${flash ? "cnbi-flash" : ""}">
				<td class="cnbi-muted">${i + 1}</td>
				<td class="cnbi-code">${this.link("Item", row.item_code)}</td>
				<td class="cnbi-iname"></td>
				<td class="num cnbi-can"></td>
				<td class="num"><input type="number" min="0" step="any" class="form-control input-xs cnbi-qty"></td>
				<td class="num"><div class="cnbi-remaining"></div><div class="cnbi-name cnbi-credited"></div></td>
				<td class="cnbi-on-inv"></td>
				<td><span class="cnbi-x" title="${__("Remove")}">&times;</span></td>
			</tr>`);
		$tr.get(0).dataset.code = row.item_code;
		if (flash) setTimeout(() => $tr.removeClass("cnbi-flash"), 900);

		const $qty = $tr.find(".cnbi-qty").val(row.qty);
		// every keystroke goes into the state, so a refresh can never drop it
		$qty.on("input", () => {
			row.qty = $qty.val();
			this.save_state();
			this.schedule_search();
		});
		$qty.on("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				this.$search.focus();
			}
		});
		$tr.find(".cnbi-x").on("click", () => {
			const at = this.state.items.findIndex((r) => r.item_code === row.item_code);
			if (at > -1) this.state.items.splice(at, 1);
			this.save_state();
			this.render_all();
			this.schedule_search();
		});
		return $tr;
	}

	fill_item_row($tr, row, r, inv) {
		const can = r ? r.returnable_total : row.creditable;
		$tr.find(".cnbi-iname").text(row.item_name || (r && r.item_name) || "");
		$tr.find(".cnbi-can").text(can != null ? format_number(can) : "");
		$tr.removeClass("cnbi-active");
		const $credited = $tr.find(".cnbi-credited").empty();
		const $remaining = $tr.find(".cnbi-remaining").empty();
		const $on = $tr.find(".cnbi-on-inv").empty();
		if (!r) return;
		if (r.unknown) {
			$on.html(`<span class="cnbi-pill bad">${__("Item not found")}</span>`);
			return;
		}
		if (flt(row.qty) > flt(r.returnable_total) && r.returnable_total > 0) {
			$credited.html(`<span class="cnbi-pill warn">${__("more than can be credited")}</span>`);
		} else if (r.credited) {
			$credited.text(__("{0} credited", [format_number(r.credited)]));
		}
		$remaining.html(r.remaining > 0 ? `<b>${format_number(r.remaining)}</b>` : `<span class="cnbi-pill on">${__("Done")}</span>`);

		let pill;
		if (!r.invoice_count && r.remaining > 0) {
			pill = `<span class="cnbi-pill bad">${__("Nothing left to credit on any invoice")}</span>`;
		} else if (inv) {
			const lines = inv.lines.filter((l) => l.item_code === row.item_code);
			const lcan = lines.reduce((s, l) => s + flt(l.returnable), 0);
			const now = lines.reduce((s, l) => s + flt(this.alloc[l.row] || 0), 0);
			if (!lines.length) pill = `<span class="cnbi-pill off">${__("Not on this invoice")}</span>`;
			else if (lcan <= 0) pill = `<span class="cnbi-pill off">${__("Already credited")}</span>`;
			else if (now > 0) {
				pill = `<span class="cnbi-pill on">${__("Crediting {0} of {1}", [format_number(now), format_number(lcan)])}</span>`;
				$tr.addClass("cnbi-active");
			} else pill = `<span class="cnbi-pill warn">${__("{0} available", [format_number(lcan)])}</span>`;
		} else {
			pill = `<span class="cnbi-muted">${__("{0} on {1} invoices", [format_number(r.returnable_total), r.invoice_count])}</span>`;
		}
		$on.html(pill);
	}

	new_list() {
		frappe.confirm(__("Start a new list? The current items and progress are cleared."), () => {
			Object.assign(this.state, { items: [], since: null, selected: null, reason: "" });
			this.set_default_dates();
			this.f_from.set_value(this.state.from_date);
			this.f_to.set_value(this.state.to_date);
			this.f_reason.set_value("");
			this.result = null;
			this.alloc = {};
			this.save_state();
			this.render_all();
		});
	}

	// ---------------------------------------------------------------- step 3: invoices

	schedule_search() {
		clearTimeout(this.search_timer);
		this.search_timer = setTimeout(() => this.search(), 500);
	}

	search() {
		const items = this.clean_items();
		if (!this.ready() || !items.length) {
			++this.request_no;
			this.result = null;
			this.render_all();
			return Promise.resolve();
		}
		const no = ++this.request_no;
		this.$body.find(".cnbi-loading").text(__("Updating..."));
		return frappe.call({
			method: CNBI_METHOD + "search",
			args: Object.assign({ items: JSON.stringify(items), since: this.state.since }, this.scope()),
			no_spinner: true,
			callback: (r) => {
				if (no !== this.request_no || !r.message) return; // superseded by a newer search
				this.result = r.message;
				if (!this.state.since) this.state.since = r.message.now;
				if (this.state.selected && !this.selected_invoice()) this.state.selected = null;
				r.message.items.forEach((it) => {
					const row = this.state.items.find((x) => x.item_code === it.item_code);
					if (row) {
						if (it.item_name) row.item_name = it.item_name;
						row.creditable = it.returnable_total;
					}
				});
				this.save_state();
				this.default_alloc();
				this.render_all();
			},
			always: () => {
				if (no === this.request_no) this.$body.find(".cnbi-loading").text("");
			},
		});
	}

	selected_invoice() {
		if (!this.result || !this.state.selected) return null;
		return this.result.invoices.find((i) => i.name === this.state.selected) || null;
	}

	render_all(flash_code) {
		const ready = this.ready();
		const has_items = this.state.items.length > 0;
		this.$body.find(".cnbi-s1").toggleClass("is-done", ready);
		this.$body.find(".cnbi-s2").toggleClass("is-locked", !ready).toggleClass("is-done", ready && has_items);
		this.$body.find(".cnbi-s2 .cnbi-lock").toggle(!ready);
		this.$search.prop("disabled", !ready);
		this.$body.find(".cnbi-s3").toggleClass("is-locked", !ready || !has_items)
			.toggleClass("is-done", !!this.selected_invoice());
		const since = this.state.since;
		this.$body.find(".cnbi-since").text(since ? __("List started {0}", [frappe.datetime.str_to_user(since)]) : "");
		this.render_items(flash_code);
		this.render_invoices();
		this.render_selected();
	}

	render_invoices() {
		const $list = this.$body.find(".cnbi-inv-list").empty();
		const $title = this.$body.find(".cnbi-inv-title-h");
		if (!this.result) {
			$title.text(__("Choose the invoice"));
			$list.html(`<div class="cnbi-empty">${this.ready()
				? __("Add items in step 2. The invoices appear here.")
				: __("Choose the customer in step 1 first.")}</div>`);
			this.$body.find(".cnbi-trunc").text("");
			return;
		}
		const q = (this.$body.find(".cnbi-filter").val() || "").trim().toLowerCase();
		const remaining = {};
		this.result.items.forEach((r) => (remaining[r.item_code] = r.remaining));
		const known = this.result.items.filter((i) => !i.unknown).length;
		const invoices = this.result.invoices.filter((i) => !q || i.name.toLowerCase().includes(q));
		$title.text(__("Choose the invoice ({0})", [this.result.invoices.length]));
		this.$body.find(".cnbi-trunc").text(
			this.result.truncated ? __("Only the first {0} invoices are shown. Narrow the dates to see others.", [this.result.invoices.length]) : ""
		);
		if (!invoices.length) {
			$list.html(`<div class="cnbi-empty">${q ? __("No invoice matches the filter.") : __("No invoice of this customer still has these items to credit.")}</div>`);
			return;
		}
		invoices.forEach((inv) => {
			const chips = inv.matched_items
				.map((code) => `<span class="cnbi-pill ${remaining[code] > 0 ? "on" : "off"}">${frappe.utils.escape_html(code)}</span>`)
				.join("");
			const warn = [];
			if (inv.draft_returns && inv.draft_returns.length) {
				warn.push(`<span class="cnbi-pill warn" title="${frappe.utils.escape_html(inv.draft_returns.join(", "))}">${__("Draft credit note exists")}</span>`);
			}
			if (inv.fe_status === "I") warn.push(`<span class="cnbi-pill bad">${__("FE invalid")}</span>`);
			const sel = inv.name === this.state.selected;
			const $row = $(`
				<div class="cnbi-inv ${sel ? "selected" : ""}">
					<input type="radio" name="cnbi-inv" ${sel ? "checked" : ""}>
					<div>
						<div>${this.link("Sales Invoice", inv.name, "cnbi-inv-title")}
							<span class="cnbi-muted">&nbsp;${frappe.datetime.str_to_user(inv.posting_date)} · ${__(inv.status)}</span></div>
						<div class="cnbi-inv-items">${chips}${warn.join("")}</div>
					</div>
					<div class="cnbi-inv-right">
						<div><b>${__("{0} of {1} items", [inv.match_count, known])}</b></div>
						<div class="cnbi-muted">${__("can credit")} ${format_currency(inv.returnable_value, inv.currency)}</div>
						<div class="cnbi-muted">${__("invoice")} ${format_currency(inv.grand_total, inv.currency)}</div>
					</div>
				</div>`).appendTo($list);
			$row.on("click", (e) => {
				if ($(e.target).closest("a").length) return; // the invoice number opens the invoice
				this.select_invoice(inv.name);
			});
		});
	}

	select_invoice(name) {
		this.state.selected = name;
		this.save_state();
		this.default_alloc();
		this.render_all();
		const el = this.$body.find(".cnbi-s4").get(0);
		el && el.scrollIntoView({ behavior: "smooth", block: "start" });
	}

	// For each requested item, fill the selected invoice's lines in line order up to
	// what is still to credit and what each line can still take.
	default_alloc() {
		this.alloc = {};
		const inv = this.selected_invoice();
		if (!inv) return;
		this.result.items.forEach((r) => {
			let left = flt(r.remaining);
			inv.lines
				.filter((l) => l.item_code === r.item_code)
				.forEach((l) => {
					const q = Math.max(Math.min(left, flt(l.returnable)), 0);
					this.alloc[l.row] = q;
					left -= q;
				});
		});
	}

	// ---------------------------------------------------------------- step 4: credit note

	make_credit_note_step() {
		this.f_reason = frappe.ui.form.make_control({
			parent: this.$body.find(".cnbi-reason"),
			df: {
				fieldname: "reason", fieldtype: "Small Text", label: __("Reason"),
				change: () => { this.state.reason = this.f_reason.get_value() || ""; this.save_state(); },
			},
			render_input: true,
		});
		this.f_reason.set_value(this.state.reason || "");
		this.f_warehouse = frappe.ui.form.make_control({
			parent: this.$body.find(".cnbi-warehouse"),
			df: {
				fieldname: "warehouse", fieldtype: "Link", options: "Warehouse", label: __("Return to Warehouse"),
				description: __("Only for invoices that moved stock. Leave empty to choose it in the credit note."),
				get_query: () => {
					const filters = { company: this.state.company, is_group: 0 };
					const allowed = frappe.boot.force_warehouse_selection_on_returns
						&& (frappe.boot.allowed_return_warehouses || {})[this.state.company];
					if (allowed && allowed.length) filters.name = ["in", allowed];
					return { filters };
				},
				change: () => { this.state.warehouse = this.f_warehouse.get_value() || ""; this.save_state(); },
			},
			render_input: true,
		});
		this.f_warehouse.set_value(this.state.warehouse || "");
	}

	render_selected() {
		const $card = this.$body.find(".cnbi-s4");
		const inv = this.selected_invoice();
		if (!inv) {
			$card.hide();
			return;
		}
		$card.show();
		this.$body.find(".cnbi-sel-title").html(
			__("Credit note against {0}", [this.link("Sales Invoice", inv.name)])
		);
		this.$body.find(".cnbi-sel-meta").text(
			`${frappe.datetime.str_to_user(inv.posting_date)} · ${__(inv.status)} · ${__("outstanding")} ${format_currency(inv.outstanding_amount, inv.currency)}`
		);
		this.$body.find(".cnbi-warehouse").toggle(!!cint(inv.update_stock));

		const $tb = this.$body.find(".cnbi-lines").empty();
		inv.lines.forEach((l) => {
			const can = flt(l.returnable);
			const q = flt(this.alloc[l.row] || 0);
			const $tr = $(`
				<tr class="${q > 0 ? "cnbi-active" : ""}">
					<td><input type="checkbox" ${q > 0 ? "checked" : ""} ${can > 0 ? "" : "disabled"}></td>
					<td>#${l.idx}</td>
					<td>${this.link("Item", l.item_code)}
						<div class="cnbi-name">${frappe.utils.escape_html(l.item_name || "")}${l.batch_no ? " · " + __("Batch") + " " + frappe.utils.escape_html(l.batch_no) : ""}${l.has_serial_no ? " · " + __("serial numbers") : ""}</div></td>
					<td class="num">${format_number(l.qty)} ${frappe.utils.escape_html(l.uom || "")}</td>
					<td class="num">${l.returned ? format_number(l.returned) : ""}</td>
					<td class="num">${can > 0 ? format_number(can) : `<span class="cnbi-pill off">${__("None")}</span>`}</td>
					<td class="num"><input type="number" min="0" step="any" class="form-control input-xs cnbi-qty" ${can > 0 ? "" : "disabled"}></td>
					<td class="num">${format_currency(l.rate, inv.currency)}</td>
					<td class="num cnbi-amt"></td>
				</tr>`).appendTo($tb);
			const $qty = $tr.find(".cnbi-qty").val(q || "");
			const $chk = $tr.find("input[type=checkbox]");
			const set = (v) => {
				v = Math.max(flt(v), 0);
				if (v > can) {
					frappe.show_alert({ message: __("Line #{0} can only take {1}.", [l.idx, format_number(can)]), indicator: "orange" });
					v = can;
				}
				this.alloc[l.row] = v;
				$qty.val(v || "");
				$chk.prop("checked", v > 0);
				$tr.toggleClass("cnbi-active", v > 0);
				$tr.find(".cnbi-amt").text(v ? format_currency(v * flt(l.rate), inv.currency) : "");
				this.render_total();
				this.render_items();
			};
			$qty.on("change", () => set($qty.val()));
			$chk.on("change", () => set($chk.prop("checked") ? this.suggest(inv, l) : 0));
			$tr.find(".cnbi-amt").text(q ? format_currency(q * flt(l.rate), inv.currency) : "");
		});
		this.render_total();

		const cns = (this.result && this.result.credit_notes) || [];
		this.$body.find(".cnbi-made").toggle(!!cns.length).html(
			`<span class="cnbi-muted">${__("Credit notes made for this list")}:</span> ` +
			cns.map((c) =>
				this.link("Sales Invoice", c.name)
				+ ` <span class="cnbi-muted">(${__("against")} ${c.return_against ? this.link("Sales Invoice", c.return_against) : ""}, ${format_currency(c.grand_total, c.currency)})</span>`
			).join(" · ")
		);
	}

	// quantity to put on a line when it is ticked by hand
	suggest(inv, line) {
		const r = this.result.items.find((i) => i.item_code === line.item_code);
		const others = inv.lines
			.filter((l) => l.item_code === line.item_code && l.row !== line.row)
			.reduce((s, l) => s + flt(this.alloc[l.row] || 0), 0);
		const left = r ? flt(r.remaining) - others : 0;
		return Math.min(flt(line.returnable), left > 0 ? left : flt(line.returnable));
	}

	render_total() {
		const inv = this.selected_invoice();
		if (!inv) return;
		const total = inv.lines.reduce((s, l) => s + flt(this.alloc[l.row] || 0) * flt(l.rate), 0);
		this.$body.find(".cnbi-total").text(format_currency(total, inv.currency));
		this.$body.find(".cnbi-open").prop("disabled", !inv.lines.some((l) => flt(this.alloc[l.row]) > 0));
	}

	open_credit_note() {
		const inv = this.selected_invoice();
		if (!inv) return;
		const rows = inv.lines
			.filter((l) => flt(this.alloc[l.row]) > 0)
			.map((l) => ({ row: l.row, qty: flt(this.alloc[l.row]) }));
		if (!rows.length) {
			frappe.msgprint(__("Tick at least one line with a quantity to credit."));
			return;
		}
		frappe.call({
			method: CNBI_METHOD + "make_credit_note",
			args: {
				source_name: inv.name,
				rows: JSON.stringify(rows),
				reason: this.state.reason || null,
				warehouse: this.state.warehouse || null,
			},
			freeze: true,
			freeze_message: __("Preparing the credit note..."),
			callback: (r) => {
				if (r.exc || !r.message) return;
				const serial_rows = ((r.message.__onload || {}).isoft_credit_note_serial_rows) || [];
				this.opened = { invoice: inv.name, customer: this.state.customer };
				frappe.model.sync(r.message);
				frappe.set_route("Form", r.message.doctype, r.message.name);
				if (serial_rows.length) {
					frappe.msgprint(
						__("Rows {0} carry serial numbers. Keep only the serial numbers that are coming back before saving.", [serial_rows.join(", ")]),
						__("Check serial numbers")
					);
				}
			},
		});
	}
}
