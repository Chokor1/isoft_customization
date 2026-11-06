// Barcode Label Studio  (/app/barcode-label-studio)
//
// Build a list of labels (scan, search, or by item group/brand), pick the label size,
// price list, store, customer group and the fields to show, then print one PDF with
// one label per page. Prices and discounts come from the server, which runs ERPNext's
// own pricing for "today, quantity 1, no customer" (isoft_customization/barcode_labels).

(function () {
	'use strict';

	const PAGE = 'barcode-label-studio';
	const API = 'isoft_customization.barcode_labels.api.';
	const FIELDS = [
		['company', __('Company')], ['item_name', __('Item name')], ['item_code', __('Item code')],
		['uom', __('UOM')], ['barcode', __('Barcode bars')], ['barcode_digits', __('Barcode digits')],
		['price', __('Price')], ['discount', __('Discount')]
	];
	const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));

	const S = {
		rows: [],          // {key, item_code, item_name, barcode, uom, copies, priced}
		opts: {},          // price_list, company, warehouse, customer_group, include_tax, tax_category, size, show
		settings: null,
		defaults: null,
		selected: null,
		seq: 0,
		ctl: {},
		$: null,
	};

	frappe.pages[PAGE].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({ parent: wrapper, title: __('Barcode Label Studio'), single_column: true });
		S.$ = $('<div class="bls-host"></div>').appendTo(page.main);
		frappe.pages[PAGE].bls = S;
		S.add_items = add_items;
		frappe.call({ method: API + 'get_page_defaults' }).then((r) => {
			S.defaults = r.message;
			S.settings = r.message.settings;
			const def = S.settings.sizes.find((z) => z.is_default) || S.settings.sizes[0];
			S.opts = {
				price_list: r.message.price_list,
				company: r.message.company,
				warehouse: r.message.warehouse,
				customer_group: null,
				include_tax: S.settings.include_tax,
				tax_category: S.settings.tax_category,
				size: remembered('size', def.label_name, S.settings.sizes.map((z) => z.label_name)),
				show: Object.assign({}, S.settings.show),
			};
			render_shell();
		});
	};

	function remembered(key, fallback, allowed) {
		try {
			const v = localStorage.getItem('isoft_bls_' + key);
			if (v && (!allowed || allowed.includes(v))) return v;
		} catch (e) { /* private window */ }
		return fallback;
	}
	function remember(key, value) {
		try { localStorage.setItem('isoft_bls_' + key, value); } catch (e) { /* ignore */ }
	}

	// ------------------------------------------------------------------ layout
	function render_shell() {
		S.$.html(`
<div class="bls">
	<header class="bls-head">
		<div class="bls-title"><i class="fa fa-barcode"></i> <span>${__('Barcode Label Studio')}</span>
			<small>${__('One label per page · prices from today\'s price list and pricing rules')}</small></div>
		<div class="bls-head-actions">
			<button class="btn btn-default btn-sm" id="bls-gear" title="${__('Settings')}"><i class="fa fa-cog"></i></button>
			<button class="btn btn-primary btn-sm" id="bls-print"><i class="fa fa-print"></i> ${__('Print PDF')} <span id="bls-count" class="bls-count">0</span></button>
		</div>
	</header>
	<section class="bls-bar" id="bls-controls"></section>
	<div class="bls-main">
		<section class="bls-list">
			<div class="bls-add">
				<div class="bls-scan-wrap"><i class="fa fa-barcode"></i>
					<input id="bls-scan" class="form-control input-sm" autocomplete="off" placeholder="${__('Scan a barcode or type an item code, then Enter')}"></div>
				<div class="bls-item-ctl" id="bls-item"></div>
				<button class="btn btn-default btn-sm" id="bls-add-filter"><i class="fa fa-filter"></i> ${__('Add by group / brand')}</button>
				<span class="bls-spacer"></span>
				<label class="bls-all">${__('Copies for all')} <input type="number" min="1" id="bls-copies-all" class="form-control input-sm" value="1"></label>
				<button class="btn btn-default btn-sm" id="bls-copies-apply">${__('Apply')}</button>
				<button class="btn btn-default btn-sm" id="bls-clear" title="${__('Remove all rows')}"><i class="fa fa-trash"></i></button>
			</div>
			<div class="bls-table-wrap">
				<table class="bls-table">
					<thead><tr>
						<th>${__('Item')}</th><th>${__('Barcode')}</th><th>${__('UOM')}</th>
						<th class="num">${__('Price')}</th><th class="num">${__('Discount')}</th><th class="num">${__('Final')}</th>
						<th class="num">${__('Copies')}</th><th></th>
					</tr></thead>
					<tbody id="bls-rows"></tbody>
				</table>
				<div class="bls-empty" id="bls-empty"><i class="fa fa-barcode"></i>
					<p>${__('Scan a barcode, search an item, or add a whole item group or brand.')}</p></div>
			</div>
		</section>
		<aside class="bls-side">
			<div class="bls-side-head"><span>${__('Preview')}</span><span id="bls-size-note"></span></div>
			<div id="bls-preview" class="bls-preview"><div class="bls-paper"><iframe title="${__('Label preview')}" sandbox=""></iframe></div></div>
			<p class="bls-side-hint" id="bls-preview-hint">${__('Click a row to preview its label.')}</p>
		</aside>
	</div>
</div>`);
		make_controls();
		bind();
		render_rows();
		update_size_note();
	}

	function make_controls() {
		const $bar = S.$.find('#bls-controls');
		const add = (fieldname, df) => {
			const $w = $(`<div class="bls-ctl" data-ctl="${fieldname}"></div>`).appendTo($bar);
			const c = frappe.ui.form.make_control({
				parent: $w,
				df: Object.assign({ fieldname }, df, {
					change() {
						const v = c.get_value();
						if ((S.opts[fieldname] || null) === (v || null)) return;
						S.opts[fieldname] = v || null;
						if (fieldname === 'include_tax') $bar.find('[data-ctl="tax_category"]').toggle(!!v);
						reprice();
					},
				}),
				render_input: true,
			});
			c.set_value(S.opts[fieldname] == null ? '' : S.opts[fieldname]);
			S.ctl[fieldname] = c;
			return c;
		};
		const $size = $(`<div class="bls-ctl"><label class="control-label">${__('Label size')}</label>
			<select id="bls-size" class="form-control input-sm">${S.settings.sizes.map((z) =>
				`<option value="${esc(z.label_name)}">${esc(z.label_name)}</option>`).join('')}</select></div>`).appendTo($bar);
		$size.find('select').val(S.opts.size);
		add('price_list', { fieldtype: 'Link', options: 'Price List', label: __('Price List'), reqd: 1,
			get_query: () => ({ filters: { selling: 1, enabled: 1 } }) });
		add('warehouse', { fieldtype: 'Link', options: 'Warehouse', label: __('Store'),
			description: __('Store-only pricing rules apply to this store'),
			get_query: () => ({ filters: S.opts.company ? { company: S.opts.company } : {} }) });
		add('customer_group', { fieldtype: 'Link', options: 'Customer Group', label: __('Customer group'),
			placeholder: __('Everyone') });
		add('company', { fieldtype: 'Link', options: 'Company', label: __('Company') });
		add('include_tax', { fieldtype: 'Check', label: __('Add IVA') });
		add('tax_category', { fieldtype: 'Link', options: 'Tax Category', label: __('Tax category') });
		$bar.find('[data-ctl="tax_category"]').toggle(!!S.opts.include_tax);

		const $f = $(`<div class="bls-ctl bls-fields-ctl dropdown">
			<label class="control-label">${__('On the label')}</label>
			<button class="btn btn-default btn-sm dropdown-toggle" id="bls-fields" data-toggle="dropdown" aria-haspopup="true">
				<span id="bls-fields-n"></span> <i class="fa fa-caret-down"></i></button>
			<div class="dropdown-menu bls-fields-menu">${FIELDS.map(([k, l]) =>
				`<label class="dropdown-item" data-show="${k}"><input type="checkbox" ${S.opts.show[k] ? 'checked' : ''}> ${esc(l)}</label>`).join('')}
			</div></div>`).appendTo($bar);
		$f.find('.dropdown-menu').on('click', (e) => e.stopPropagation());
		$f.on('change', 'input', function () {
			S.opts.show[$(this).closest('[data-show]').data('show')] = this.checked ? 1 : 0;
			update_fields_n();
			preview();
		});
		update_fields_n();
	}

	function update_fields_n() {
		const n = FIELDS.filter(([k]) => S.opts.show[k]).length;
		S.$.find('#bls-fields-n').text(__('{0} of {1} fields', [n, FIELDS.length]));
	}

	function update_size_note() {
		const z = size();
		S.$.find('#bls-size-note').text(z ? `${z.width_mm} × ${z.height_mm} mm` : '');
	}

	function size() {
		return S.settings.sizes.find((z) => z.label_name === S.opts.size) || S.settings.sizes[0];
	}

	function bind() {
		const $c = S.$;
		$c.off(); // render_shell runs again after a settings save
		$c.on('change', '#bls-size', function () {
			S.opts.size = $(this).val();
			remember('size', S.opts.size);
			update_size_note();
			preview();
		});
		$c.on('keydown', '#bls-scan', function (e) {
			if (e.key !== 'Enter') return;
			e.preventDefault();
			const code = $(this).val().trim();
			if (!code) return;
			$(this).val('');
			frappe.call({ method: API + 'resolve_scan', args: { code } }).then((r) => {
				const hit = r.message || {};
				if (!hit.item_code) {
					frappe.show_alert({ message: __('Nothing found for {0}', [esc(code)]), indicator: 'orange' });
					return;
				}
				if (hit.barcode) add_rows([hit]);
				else add_items([hit.item_code]);
			});
		});
		const item = frappe.ui.form.make_control({
			parent: $c.find('#bls-item'),
			df: { fieldtype: 'Link', options: 'Item', fieldname: 'bls_item', placeholder: __('Search an item…'),
				get_query: () => ({ filters: { disabled: 0, has_variants: 0 } }),
				change() {
					const v = item.get_value();
					if (!v) return;
					item.set_value('');
					add_items([v]);
				} },
			render_input: true,
		});
		$c.on('click', '#bls-add-filter', add_by_filter);
		$c.on('click', '#bls-copies-apply', () => {
			const n = Math.max(1, parseInt($c.find('#bls-copies-all').val(), 10) || 1);
			S.rows.forEach((r) => { r.copies = n; });
			render_rows();
		});
		$c.on('click', '#bls-clear', () => {
			if (!S.rows.length) return;
			frappe.confirm(__('Remove all {0} rows?', [S.rows.length]), () => { S.rows = []; S.selected = null; render_rows(); preview(); });
		});
		$c.on('click', '.bls-row', function (e) {
			if ($(e.target).closest('input, button').length) return;
			S.selected = $(this).data('key');
			S.$.find('.bls-row').removeClass('is-sel');
			$(this).addClass('is-sel');
			preview();
		});
		$c.on('change', '.bls-copies', function () {
			const r = row_by_key($(this).closest('.bls-row').data('key'));
			if (r) r.copies = Math.max(1, parseInt($(this).val(), 10) || 1);
			$(this).val(r ? r.copies : 1);
			update_count();
		});
		$c.on('click', '.bls-del', function () {
			const key = $(this).closest('.bls-row').data('key');
			S.rows = S.rows.filter((r) => r.key !== key);
			if (S.selected === key) S.selected = S.rows.length ? S.rows[0].key : null;
			render_rows();
			preview();
		});
		$c.on('click', '.bls-gen', function () {
			const r = row_by_key($(this).closest('.bls-row').data('key'));
			if (!r) return;
			frappe.confirm(__('Create a new EAN-13 barcode for {0} and save it on the item?', [esc(r.item_code)]), () => {
				frappe.call({ method: API + 'generate_barcode', args: { item_code: r.item_code }, freeze: true }).then((res) => {
					r.barcode = res.message.barcode;
					r.uom = res.message.uom || r.uom;
					frappe.show_alert({ message: __('Barcode {0} saved on {1}', [res.message.barcode, esc(r.item_code)]), indicator: 'green' });
					reprice([r]);
				});
			});
		});
		$c.on('click', '#bls-print', print_pdf);
		$c.on('click', '#bls-gear', open_settings);
	}

	// ------------------------------------------------------------------ rows
	function row_by_key(key) { return S.rows.find((r) => r.key === key); }

	function add_items(codes) {
		return frappe.call({ method: API + 'rows_for_items', args: { item_codes: JSON.stringify(codes) } })
			.then((r) => add_rows(r.message || []));
	}

	function add_rows(list) {
		const added = [];
		list.forEach((x) => {
			const dup = S.rows.find((r) => r.item_code === x.item_code && (r.barcode || null) === (x.barcode || null));
			if (dup) { dup.copies = (dup.copies || 1) + (list.length === 1 ? 1 : 0); return; }
			const row = { key: 'r' + (++S.seq), item_code: x.item_code, item_name: x.item_name || '', barcode: x.barcode || null,
				uom: x.uom || null, copies: 1, priced: null };
			S.rows.push(row);
			added.push(row);
		});
		if (!S.selected && S.rows.length) S.selected = S.rows[0].key;
		if (list.length === 1 && !added.length) frappe.show_alert({ message: __('Already in the list: one more copy'), indicator: 'blue' });
		render_rows();
		return added.length ? reprice(added) : Promise.resolve();
	}

	function add_by_filter() {
		const d = new frappe.ui.Dialog({
			title: __('Add items by group or brand'),
			fields: [
				{ fieldname: 'item_group', fieldtype: 'Link', options: 'Item Group', label: __('Item Group') },
				{ fieldname: 'brand', fieldtype: 'Link', options: 'Brand', label: __('Brand') },
				{ fieldtype: 'HTML', options: `<p class="text-muted small">${__('Sales items only, up to 500 items; one row per barcode.')}</p>` },
			],
			primary_action_label: __('Add'),
			primary_action(v) {
				if (!v.item_group && !v.brand) { frappe.msgprint(__('Pick an Item Group or a Brand')); return; }
				d.hide();
				frappe.call({ method: API + 'rows_for_filter', args: v, freeze: true, freeze_message: __('Finding items…') })
					.then((r) => {
						const list = r.message || [];
						if (!list.length) frappe.show_alert({ message: __('No items found'), indicator: 'orange' });
						return add_rows(list);
					});
			},
		});
		S.dialog = d;
		d.show();
	}

	let price_token = 0;
	function reprice(only) {
		const rows = only || S.rows;
		if (!rows.length || !S.opts.price_list) { render_rows(); preview(); return Promise.resolve(); }
		const token = ++price_token;
		rows.forEach((r) => { r.loading = true; });
		render_rows();
		return frappe.call({
			method: API + 'price',
			args: { rows: JSON.stringify(rows.map((r) => ({ item_code: r.item_code, barcode: r.barcode, uom: r.uom }))), opts: JSON.stringify(api_opts()) },
		}).then((res) => {
			const out = res.message || [];
			if (!only && token !== price_token) return; // a newer full reprice is on its way
			rows.forEach((r, i) => {
				r.loading = false;
				r.priced = out[i] || null;
				if (r.priced) r.item_name = r.priced.item_name;
			});
			render_rows();
			preview();
		}, () => { rows.forEach((r) => { r.loading = false; }); render_rows(); });
	}

	function money(v) {
		if (v == null) return '';
		const d = parseInt(S.settings.price_decimals, 10);
		return format_number(v, null, isNaN(d) ? 2 : d);
	}

	function render_rows() {
		const $tb = S.$.find('#bls-rows');
		S.$.find('#bls-empty').toggle(!S.rows.length);
		$tb.html(S.rows.map((r) => {
			const p = r.priced;
			const no_price = p && !p.has_price;
			const gen = !r.barcode && S.defaults.can_generate
				? `<button class="btn btn-xs btn-default bls-gen"><i class="fa fa-magic"></i> ${__('Generate EAN-13')}</button>`
				: (!r.barcode ? `<span class="bls-muted">${__('No barcode')}</span>` : '');
			const pct = p && p.discount_percentage ? `-${format_number(p.discount_percentage, null, 2).replace(/[.,]00$/, '')}%` : '';
			const src = p && p.discount_source === 'barcode' ? ` <span class="bls-tag" title="${__('Discount set on this barcode')}">${__('barcode')}</span>` : '';
			const sym = esc(S.settings.currency_symbol || '');
			return `<tr class="bls-row ${S.selected === r.key ? 'is-sel' : ''} ${no_price ? 'is-noprice' : ''}" data-key="${r.key}" data-item="${esc(r.item_code)}">
				<td><div class="bls-code">${esc(r.item_code)}</div><div class="bls-name">${esc(r.item_name || (p && p.item_name) || '')}</div></td>
				<td class="bls-bc">${r.barcode ? `<code>${esc(r.barcode)}</code>` : gen}</td>
				<td class="bls-uom">${esc((p && p.uom) || r.uom || '')}</td>
				<td class="num">${r.loading ? '<span class="bls-muted">…</span>' : (p && p.has_price ? money(p.price_list_rate) : (no_price ? `<span class="bls-warn" title="${__('No price in this price list')}">${__('no price')}</span>` : ''))}</td>
				<td class="num">${pct}${src}</td>
				<td class="num bls-final">${p && p.has_price ? `<b>${money(p.final_price)}</b> ${sym}` : ''}</td>
				<td class="num"><input type="number" min="1" class="form-control input-xs bls-copies" value="${r.copies}"></td>
				<td class="num"><button class="btn btn-xs btn-link bls-del" title="${__('Remove')}">&times;</button></td>
			</tr>`;
		}).join(''));
		update_count();
	}

	function update_count() {
		const n = S.rows.reduce((a, r) => a + (parseInt(r.copies, 10) || 1), 0);
		S.$.find('#bls-count').text(n);
		S.$.find('#bls-print').prop('disabled', !n);
	}

	function api_opts() {
		return {
			price_list: S.opts.price_list, company: S.opts.company, warehouse: S.opts.warehouse,
			customer_group: S.opts.customer_group, include_tax: S.opts.include_tax ? 1 : 0,
			tax_category: S.opts.tax_category, size: S.opts.size, show: S.opts.show,
		};
	}

	// ------------------------------------------------------------------ preview
	let preview_timer = null, preview_token = 0;
	function preview() {
		clearTimeout(preview_timer);
		preview_timer = setTimeout(do_preview, 150);
	}
	function do_preview() {
		const z = size();
		const $box = S.$.find('#bls-preview');
		const $paper = $box.find('.bls-paper');
		const px = 96 / 25.4;
		const w = z.width_mm * px, h = z.height_mm * px;
		const k = Math.min(($box.width() - 24) / w, 420 / h, 4);
		$paper.css({ width: w * k, height: h * k });
		$paper.find('iframe').css({ width: w, height: h, transform: `scale(${k})` });
		const r = row_by_key(S.selected) || S.rows[0];
		S.$.find('#bls-preview-hint').toggle(!r);
		if (!r) { $paper.find('iframe').attr('srcdoc', ''); return; }
		const token = ++preview_token;
		frappe.call({
			method: API + 'preview_html',
			args: { row: JSON.stringify({ item_code: r.item_code, barcode: r.barcode, uom: r.uom }), opts: JSON.stringify(api_opts()) },
		}).then((res) => {
			if (token !== preview_token) return;
			$paper.find('iframe').attr('srcdoc', res.message || '');
		});
	}

	// ------------------------------------------------------------------ print / settings
	function print_pdf() {
		if (!S.rows.length) return;
		if (!S.opts.price_list && S.opts.show.price) { frappe.msgprint(__('Pick a Price List first')); return; }
		const rows = S.rows.map((r) => ({ item_code: r.item_code, barcode: r.barcode, uom: r.uom, copies: parseInt(r.copies, 10) || 1 }));
		const total = rows.reduce((a, r) => a + r.copies, 0);
		if (total > 2000) { frappe.msgprint(__('{0} labels: one PDF holds at most 2000. Split the list.', [total])); return; }
		open_url_post('/api/method/' + API + 'make_pdf', { rows: JSON.stringify(rows), opts: JSON.stringify(api_opts()) }, true);
	}

	function open_settings() {
		const s = S.settings;
		const d = new frappe.ui.Dialog({
			title: __('Barcode Label Settings'),
			size: 'large',
			fields: [
				{ fieldname: 'sizes', fieldtype: 'Table', label: __('Label sizes'), in_place_edit: true, cannot_add_rows: false,
					data: s.sizes.map((z) => Object.assign({}, z)),
					fields: [
						{ fieldname: 'label_name', fieldtype: 'Data', label: __('Name'), in_list_view: 1, reqd: 1, columns: 2 },
						{ fieldname: 'width_mm', fieldtype: 'Float', label: __('Width (mm)'), in_list_view: 1, reqd: 1, columns: 2 },
						{ fieldname: 'height_mm', fieldtype: 'Float', label: __('Height (mm)'), in_list_view: 1, reqd: 1, columns: 2 },
						{ fieldname: 'padding_mm', fieldtype: 'Float', label: __('Padding (mm)'), in_list_view: 1, columns: 1 },
						{ fieldname: 'font_size_pt', fieldtype: 'Float', label: __('Font (pt)'), in_list_view: 1, columns: 1 },
						{ fieldname: 'is_default', fieldtype: 'Check', label: __('Default'), in_list_view: 1, columns: 1 },
					] },
				{ fieldtype: 'Section Break' },
				{ fieldname: 'default_price_list', fieldtype: 'Link', options: 'Price List', label: __('Default price list'), default: s.default_price_list },
				{ fieldname: 'ean_prefix', fieldtype: 'Data', label: __('Prefix for generated EAN-13'), default: s.ean_prefix,
					description: __('200–299 is the GS1 in-store range: it never collides with a manufacturer barcode.') },
				{ fieldtype: 'Column Break' },
				{ fieldname: 'currency_symbol', fieldtype: 'Data', label: __('Currency symbol'), default: s.currency_symbol },
				{ fieldname: 'symbol_position', fieldtype: 'Select', options: 'After\nBefore', label: __('Symbol position'), default: s.symbol_position },
				{ fieldname: 'price_decimals', fieldtype: 'Select', options: '0\n2', label: __('Decimals'), default: String(s.price_decimals) },
				{ fieldtype: 'Section Break' },
				{ fieldname: 'include_tax', fieldtype: 'Check', label: __('Add IVA by default'), default: s.include_tax },
				{ fieldname: 'tax_category', fieldtype: 'Link', options: 'Tax Category', label: __('Default tax category'), default: s.tax_category },
				{ fieldtype: 'Column Break' },
				{ fieldtype: 'HTML', options: `<p class="text-muted small">${__('The fields chosen in "On the label" are saved as the default for everyone.')}</p>` },
			],
			primary_action_label: s.can_write ? __('Save') : __('Close'),
			primary_action(v) {
				if (!s.can_write) { d.hide(); return; }
				const payload = Object.assign({}, v, { sizes: (v.sizes || []).filter((z) => z.label_name), show: S.opts.show });
				frappe.call({ method: 'isoft_customization.barcode_labels.settings.save_settings', args: { settings: JSON.stringify(payload) }, freeze: true })
					.then((r) => {
						S.settings = r.message;
						if (!S.settings.sizes.some((z) => z.label_name === S.opts.size)) S.opts.size = (S.settings.sizes.find((z) => z.is_default) || S.settings.sizes[0]).label_name;
						d.hide();
						frappe.show_alert({ message: __('Settings saved'), indicator: 'green' });
						const keep = S.rows;
						render_shell();
						S.rows = keep;
						reprice();
					});
			},
		});
		if (!s.can_write) d.$wrapper.find('input, select, textarea').prop('disabled', true);
		d.show();
	}
})();
