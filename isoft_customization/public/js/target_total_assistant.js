// Pricing Assistant (internally target_total): fit the free item lines of a draft Quotation /
// Delivery Note / Sales Invoice so the Grand Total or Net Total lands on a
// typed target. Pure arithmetic lives in target_total_math.js; this file owns
// the pieces that touch the form.
//
// The panel previews on frm.doc itself and drives ERPNext's own client
// calculator, so inclusive taxes, item tax templates, the document discount
// and rounding come out exactly as the form will show them. Nothing is saved:
// Apply only closes the dialog and marks the form dirty.

frappe.provide('isoft.target_total');

(function (ns) {
	const SNAP_FIELDS = ['rate', 'price_list_rate', 'discount_percentage', 'discount_amount',
		'margin_type', 'margin_rate_or_amount', 'rate_with_margin'];

	// Per-row copy of the price fields, by row position.
	ns.snapshot = function (frm) {
		return (frm.doc.items || []).map(function (it) {
			const s = {};
			SNAP_FIELDS.forEach(function (f) { s[f] = it[f]; });
			return s;
		});
	};

	ns.restore = function (frm, snap) {
		(frm.doc.items || []).forEach(function (it, i) {
			if (!snap[i]) return;
			SNAP_FIELDS.forEach(function (f) { it[f] = snap[i][f]; });
		});
	};

	function clear_discount(it) {
		it.discount_percentage = 0;
		it.discount_amount = 0;
	}

	function clear_margin(it) {
		it.margin_type = '';
		it.margin_rate_or_amount = 0;
		it.rate_with_margin = 0;
	}

	// Writes new_rate on the row in the given mode. Returns {margin: true} when
	// Rate mode had to express an increase as a margin (above price list rate).
	ns.write_rate = function (item, new_rate, mode) {
		new_rate = flt(new_rate, precision('rate', item));
		if (new_rate < 0) new_rate = 0;
		const plr = flt(item.price_list_rate);

		if (mode === 'Rate' && plr > 0) {
			item.rate = new_rate;
			if (new_rate <= plr) {
				clear_margin(item);
				item.discount_amount = flt(plr - new_rate, precision('discount_amount', item));
				item.discount_percentage = flt((plr - new_rate) / plr * 100, precision('discount_percentage', item));
				return { margin: false };
			}
			clear_discount(item);
			item.margin_type = 'Amount';
			item.margin_rate_or_amount = flt(new_rate - plr, precision('margin_rate_or_amount', item));
			item.rate_with_margin = new_rate;
			return { margin: true };
		}

		// Price List Rate mode, and Rate mode on a row without a price list rate.
		// An existing discount (typed by hand or from a pricing rule) is kept: the
		// price list rate is raised so that the same discount lands on new_rate.
		const pct = flt(item.discount_percentage);
		const amt = flt(item.discount_amount);
		clear_margin(item);
		item.rate = new_rate;
		if (pct > 0 && pct < 100) {
			item.price_list_rate = flt(new_rate / (1 - pct / 100), precision('price_list_rate', item));
			item.discount_amount = flt(item.price_list_rate - new_rate, precision('discount_amount', item));
		} else if (amt > 0) {
			item.price_list_rate = flt(new_rate + amt, precision('price_list_rate', item));
		} else {
			item.price_list_rate = new_rate;
			clear_discount(item);
		}
		return { margin: false };
	};

	// calculate_taxes_and_totals() without the refresh_fields() at its end, so the
	// solver can iterate without re-rendering the form each pass.
	ns.recalc_silent = function (frm) {
		const c = frm.cscript;
		c.discount_amount_applied = false;
		c._calculate_taxes_and_totals();
		c.calculate_discount_amount();
		if (frm.doc.apply_discount_on == 'Grand Total' && frm.doc.is_cash_or_non_trade_discount) {
			frm.doc.grand_total -= frm.doc.discount_amount;
			frm.doc.base_grand_total -= frm.doc.base_discount_amount;
		}
	};

	ns.current = function (frm, kind) {
		return kind === 'Grand Total' ? flt(frm.doc.grand_total) : flt(frm.doc.net_total);
	};

	// ---------------------------------------------------------------- solver

	const TOL = 0.005;       // solver tolerance
	const WARN = 0.01;       // shown as a warning above this
	const MAX_SECANT = 12;
	const MAX_RESIDUE = 3;
	const RESIDUE_ROWS = 4;   // free rows searched in the residue pass
	const RESIDUE_STEPS = 2;  // rate units tried either side per row
	const MODES = ['Fixed', 'Rate', 'Price List Rate'];

	function item_of(frm, row) { return frm.doc.items[row.idx]; }

	function is_free(frm, row) {
		return row.mode !== 'Fixed' && flt(item_of(frm, row).qty) !== 0;
	}

	function flag_margins(frm, rows) {
		rows.forEach(function (r) {
			const it = item_of(frm, r);
			const mode = r.mode === 'Fixed' ? r.typed_mode : r.mode;
			r.margin = mode === 'Rate' && flt(it.price_list_rate) > 0 && flt(it.rate) > flt(it.price_list_rate);
		});
	}

	// Puts every row back to the opening snapshot, then re-applies typed rates.
	function reset_lines(frm, state) {
		ns.restore(frm, state.snap);
		state.rows.forEach(function (r) {
			if (r.mode === 'Fixed' && r.typed_rate !== null) {
				ns.write_rate(item_of(frm, r), r.typed_rate, r.typed_mode || state.default_mode);
			}
		});
	}

	// Fits the free rows so current(frm, state.kind) equals state.target.
	// Returns {ok, diff, reason?, min_total?}. Operates on frm.doc in place.
	ns.fit = function (frm, state) {
		const math = ns.math;
		const target = flt(state.target);
		reset_lines(frm, state);
		const free = state.rows.filter(function (r) { return is_free(frm, r); });

		function finish(ok, extra) {
			ns.recalc_silent(frm);
			flag_margins(frm, state.rows);
			return Object.assign({ ok: ok, diff: flt(target - ns.current(frm, state.kind), 2) }, extra || {});
		}

		if (!free.length) return finish(false, { reason: __('All lines are fixed') });
		if (free.every(function (r) { return r.original_rate * flt(item_of(frm, r).qty) === 0; })) {
			return finish(false, { reason: __('Free lines have no amount; type a rate on at least one line') });
		}

		const rule = state.rounding && ns._settings && flt(ns._settings.base) ? ns._settings : null;
		function rate_at(r, k) {
			return math.scaled_rate(r.original_rate, k, precision('rate', item_of(frm, r)), rule);
		}

		// Adjust-by-percent mode: every free line moves by the same percentage (and
		// is rounded to the step when one is set). No target to hit.
		if (state.mode === 'Percent') {
			const k = Math.max(0, 1 + flt(state.percent) / 100);
			free.forEach(function (r) { ns.write_rate(item_of(frm, r), rate_at(r, k), r.mode); });
			return finish(true, { percent: true });
		}

		function S(k) {
			free.forEach(function (r) { ns.write_rate(item_of(frm, r), rate_at(r, k), r.mode); });
			ns.recalc_silent(frm);
			return ns.current(frm, state.kind);
		}

		// S(0) is the fixed part: with positive quantities every reachable total is
		// above it, on a return (negative qty) every reachable total is below it.
		const s_min = S(0);
		let k0 = 1, s0 = S(1);
		const dir = Math.sign(s0 - s_min) || 1;
		if ((target - s_min) * dir < -TOL) {
			reset_lines(frm, state);
			return finish(false, {
				reason: dir > 0
					? __('Target too low: lowest reachable total is {0}', [format_currency(s_min, frm.doc.currency)])
					: __('Target too high: highest reachable total is {0}', [format_currency(s_min, frm.doc.currency)]),
				min_total: s_min
			});
		}

		if (!math.converged(s0, target, TOL)) {
			let k1 = s0 ? target / s0 : 2, s1 = S(k1), n = 0;
			while (!math.converged(s1, target, TOL) && n++ < MAX_SECANT) {
				const k2 = math.secant_next(k0, s0, k1, s1, target);
				k0 = k1; s0 = s1; k1 = k2; s1 = S(k2);
			}
		}

		// Residue: rounded rates times quantities cannot always land on an exact
		// cent with one move (taxes are kept at 3 decimals), but a pair of moves in
		// opposite directions usually can. Try every single and pair move of a few
		// rate units on the largest free rows and keep whichever lands closest.
		const candidates = free.slice().sort(function (a, b) {
			return Math.abs(item_of(frm, b).amount) - Math.abs(item_of(frm, a).amount);
		}).slice(0, RESIDUE_ROWS);
		const moves = [];
		candidates.forEach(function (r) {
			const it = item_of(frm, r);
			if (rule) {
				// Only moves that land on another rounded price are allowed.
				math.landing_deltas(flt(it.rate), rule, RESIDUE_STEPS).forEach(function (delta) { moves.push({ row: r, delta: delta }); });
				return;
			}
			const unit = 1 / Math.pow(10, precision('rate', it));
			for (let n = -RESIDUE_STEPS; n <= RESIDUE_STEPS; n++) if (n) moves.push({ row: r, delta: n * unit });
		});
		function apply_moves(list, base_rates) {
			list.forEach(function (m) {
				const it = item_of(frm, m.row);
				ns.write_rate(it, Math.max(0, base_rates[m.row.idx] + m.delta), m.row.mode);
			});
			ns.recalc_silent(frm);
			return Math.abs(target - ns.current(frm, state.kind));
		}
		for (let pass = 0; pass < MAX_RESIDUE; pass++) {
			const base_rates = {};
			candidates.forEach(function (r) { base_rates[r.idx] = flt(item_of(frm, r).rate); });
			let best = { diff: Math.abs(target - ns.current(frm, state.kind)), list: null };
			if (best.diff <= TOL) break;
			const combos = moves.map(function (m) { return [m]; });
			for (let i = 0; i < moves.length; i++) {
				for (let j = i + 1; j < moves.length; j++) {
					if (moves[i].row !== moves[j].row) combos.push([moves[i], moves[j]]);
				}
			}
			combos.forEach(function (list) {
				const diff = apply_moves(list, base_rates);
				if (diff < best.diff - 1e-9) best = { diff: diff, list: list };
				apply_moves([], base_rates);
				list.forEach(function (m) { ns.write_rate(item_of(frm, m.row), base_rates[m.row.idx], m.row.mode); });
			});
			if (!best.list) { ns.recalc_silent(frm); break; }
			apply_moves(best.list, base_rates);
		}

		const diff = flt(target - ns.current(frm, state.kind), 2);
		// With rounding on the user accepts landing on the nearest rounded prices: still ok, flagged.
		if (rule && Math.abs(diff) > WARN) return finish(true, { rounded: true });
		return finish(Math.abs(diff) <= WARN);
	};

	// ---------------------------------------------------------------- dialog

	const ICON = '<svg class="isoft-tt-icon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
		'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/>' +
		'<path d="M12 3v2M12 19v2M3 12h2M19 12h2"/></svg>';
	const GEAR = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>';
	const LOCK = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';

	// Toolbar button with the target icon. Called from the three doctype_js files.
	ns.add_button = function (frm) {
		const $btn = frm.add_custom_button(__('Pricing Assistant'), function () { ns.open(frm); });
		if ($btn && $btn.length && !$btn.hasClass('isoft-tt-btn')) {
			$btn.addClass('isoft-tt-btn').html(ICON + '<span>' + __('Pricing Assistant') + '</span>');
		}
		return $btn;
	};

	function nf() { return frappe.boot.sysdefaults.number_format || '#,###.##'; }
	function money(v, frm) { return format_currency(v, frm.doc.currency); }
	function num(v, p) { return format_number(flt(v), nf(), p === undefined ? 2 : p); }
	function parse(v) { return flt(v, 9, nf()); }
	function rate_str(v, it) { return flt(v, precision('rate', it)).toString(); }
	function esc(v) { return frappe.utils.escape_html(v || ''); }

	function debounce(fn, wait, track) {
		let t;
		return function () {
			const args = arguments, ctx = this;
			clearTimeout(t);
			t = setTimeout(function () { fn.apply(ctx, args); }, wait);
			track && track(t);
		};
	}

	function seg(cls, options, value) {
		return '<div class="isoft-tt-seg ' + cls + '">' + options.map(function (o) {
			return '<button type="button" class="isoft-tt-seg-btn' + (o.value === value ? ' is-on' : '') +
				'" data-value="' + o.value + '">' + o.label + '</button>';
		}).join('') + '</div>';
	}

	// Loads Pricing Assistant Settings, then builds the dialog.
	ns.open = function (frm) {
		if (ns._dialog || ns._opening) return ns._dialog;
		ns._opening = true;
		return frappe.call({ method: 'isoft_customization.pricing_assistant.get_settings' }).then(function (r) {
			ns._settings = r.message || {};
			return ns._build_dialog(frm);
		}).always(function () { ns._opening = false; });
	};

	ns._build_dialog = function (frm) {
		if (ns._dialog) return ns._dialog;
		const cfg = ns._settings || {};
		const kind0 = cfg.default_target_kind === 'Net Total' ? 'Net Total' : 'Grand Total';
		const line_mode0 = cfg.default_line_mode === 'Rate' ? 'Rate' : 'Price List Rate';
		const state = {
			kind: kind0,
			target: ns.current(frm, kind0),
			mode: 'Target',          // 'Target' | 'Percent'
			percent: 0,
			rounding: !!cint(cfg.apply_rounding_by_default),  // rule from Pricing Assistant Settings
			default_mode: line_mode0,
			snap: ns.snapshot(frm),
			rows: (frm.doc.items || []).map(function (it, i) {
				const locked = flt(it.qty) === 0;
				return { idx: i, mode: locked ? 'Fixed' : line_mode0, locked: locked,
					original_rate: flt(it.rate), typed_rate: null, typed_mode: null, margin: false };
			})
		};
		const open_totals = { net: flt(frm.doc.net_total), tax: flt(frm.doc.total_taxes_and_charges), grand: flt(frm.doc.grand_total) };
		let applied = false, closed = false, pending = null;

		const d = new frappe.ui.Dialog({
			title: __('Pricing Assistant'),
			size: 'extra-large',
			fields: [{ fieldname: 'body', fieldtype: 'HTML' }],
			primary_action_label: __('Apply'),
			primary_action: function () { applied = true; frm.dirty(); d.hide(); },
			secondary_action_label: __('Reset'),
			secondary_action: function () {
				state.rows.forEach(function (r) { r.typed_rate = null; r.typed_mode = null; r.mode = r.locked ? 'Fixed' : state.default_mode; });
				state.mode = 'Target'; state.percent = 0; state.rounding = !!cint(cfg.apply_rounding_by_default);
				ns.restore(frm, state.snap); ns.recalc_silent(frm);
				state.target = ns.current(frm, state.kind);
				build(); refit();
			}
		});
		d.add_custom_action(__('Cancel'), function () { d.hide(); }, 'isoft-tt-cancel');
		d.$wrapper.addClass('isoft-tt-modal');
		d.onhide = function () {
			closed = true;
			clearTimeout(pending);
			$(window).off('resize.isoft-tt');
			if (!applied) { ns.restore(frm, state.snap); }
			frm.refresh_field('items');
			frm.cscript.calculate_taxes_and_totals();
			if (ns._dialog === d) ns._dialog = null;
			d.$wrapper.remove();
		};
		ns._dialog = d;

		const $body = $(d.fields_dict.body.wrapper);

		function build() {
			const rows_html = state.rows.map(function (r) {
				const it = item_of(frm, r);
				const options = MODES.map(function (m) {
					return '<option value="' + m + '"' + (m === r.mode ? ' selected' : '') + '>' + __(m) + '</option>';
				}).join('');
				const dis = r.locked ? ' disabled' : '';
				return '<tr data-idx="' + r.idx + '">' +
					'<td class="tt-idx">' + (r.idx + 1) + '</td>' +
					'<td class="tt-item"><div class="tt-code">' + esc(it.item_code) + '</div>' +
						'<div class="tt-name">' + esc(it.item_name) + '</div></td>' +
					'<td class="tt-num">' + num(it.qty, precision('qty', it)) + '</td>' +
					'<td class="tt-num tt-cur">' + num(state.snap[r.idx].rate) + '</td>' +
					'<td class="tt-num tt-cur">' + num(state.snap[r.idx].rate * flt(it.qty)) + '</td>' +
					'<td class="tt-mode-cell"><span class="tt-lock">' + LOCK + '</span>' +
						'<select class="tt-mode"' + dis + ' title="' + __('Mode') + '">' + options + '</select></td>' +
					'<td class="tt-rate-cell"><input type="number" step="any" class="tt-rate"' + dis + ' value="' + rate_str(it.rate, it) + '">' +
						'<div class="tt-delta"></div></td>' +
					'<td class="tt-num tt-new-amount"></td>' +
					'<td class="tt-num tt-disc"></td>' +
				'</tr>';
			}).join('');

			$body.html(
				'<div class="isoft-tt">' +
					'<div class="isoft-tt-bar">' +
						seg('tt-mode-switch', [{ value: 'Target', label: __('Target total') }, { value: 'Percent', label: __('Adjust by %') }], state.mode) +
						'<div class="isoft-tt-only-target">' +
							seg('tt-kind', [{ value: 'Grand Total', label: __('Grand Total') }, { value: 'Net Total', label: __('Net Total') }], state.kind) +
							'<div class="isoft-tt-target-wrap" title="' + __('Target') + '"><span class="isoft-tt-ccy">' + esc(frm.doc.currency) + '</span>' +
								'<input type="text" class="isoft-tt-target" inputmode="decimal" value="' + num(state.target) + '"></div>' +
						'</div>' +
						'<div class="isoft-tt-only-percent">' +
							'<div class="isoft-tt-target-wrap isoft-tt-percent-wrap" title="' + __('Increase or decrease all free lines by this percentage') + '">' +
								'<button type="button" class="isoft-tt-stepbtn tt-pct-minus" title="-1%">&minus;</button>' +
								'<input type="text" class="isoft-tt-percent" inputmode="decimal" value="' + num(state.percent) + '">' +
								'<span class="isoft-tt-ccy">%</span>' +
								'<button type="button" class="isoft-tt-stepbtn tt-pct-plus" title="+1%">+</button>' +
							'</div>' +
						'</div>' +
						'<label class="isoft-tt-switch" title="' + __('Round every free line with the rule from the settings') + '">' +
							'<input type="checkbox" class="tt-round-toggle"' + (state.rounding ? ' checked' : '') + '>' +
							'<span class="isoft-tt-switch-track"></span><span class="isoft-tt-switch-label">' + __('Rounding') + '</span>' +
						'</label>' +
						'<button type="button" class="isoft-tt-iconbtn tt-settings" title="' + __('Pricing Assistant Settings') + '">' + GEAR + '</button>' +
						'<div class="isoft-tt-bar-mode"><span class="isoft-tt-bar-label">' + __('Free lines') + '</span>' +
							seg('tt-default-mode', [{ value: 'Price List Rate', label: __('Price List Rate') }, { value: 'Rate', label: __('Rate') }], state.default_mode) + '</div>' +
						'<span class="isoft-tt-spacer"></span>' +
						'<span class="isoft-tt-pill isoft-tt-status"></span>' +
					'</div>' +
					'<div class="isoft-tt-stats">' +
						'<span>' + __('Current') + ' <b class="tt-kpi-current"></b></span>' +
						'<span>' + __('Difference') + ' <b class="tt-kpi-diff"></b></span>' +
						'<span class="tt-kpi-diff-sub"></span>' +
						'<span class="tt-kpi-status-sub"></span>' +
					'</div>' +
					'<div class="isoft-tt-card">' +
						'<div class="isoft-tt-card-head">' +
							'<b>' + __('Lines') + '</b><span class="tt-free-count"></span>' +
							'<span class="isoft-tt-spacer"></span>' +
							'<button type="button" class="isoft-tt-chip tt-free-all">' + __('Free all') + '</button>' +
							'<button type="button" class="isoft-tt-chip tt-fix-all">' + __('Fix all') + '</button>' +
						'</div>' +
						'<div class="isoft-tt-scroll"><table class="isoft-tt-table"><thead><tr>' +
							'<th>#</th><th>' + __('Item') + '</th><th class="tt-num">' + __('Qty') + '</th>' +
							'<th class="tt-num">' + __('Current rate') + '</th><th class="tt-num">' + __('Current amount') + '</th>' +
							'<th>' + __('Mode') + '</th><th class="tt-num">' + __('New rate') + '</th>' +
							'<th class="tt-num">' + __('New amount') + '</th><th class="tt-num">' + __('Discount %') + '</th>' +
						'</tr></thead><tbody>' + rows_html + '</tbody></table></div>' +
					'</div>' +

					'<div class="isoft-tt-footer">' +
						'<div class="isoft-tt-totals">' +
							'<span>' + __('Net Total') + ' <b class="tt-net"></b></span>' +
							'<span>' + __('Taxes') + ' <b class="tt-tax"></b></span>' +
							'<span class="is-grand">' + __('Grand Total') + ' <b class="tt-grand"></b></span>' +
						'</div>' +
						'<div class="isoft-tt-note"></div>' +
					'</div>' +
				'</div>'
			);
		}

		function pct(a, b) { return b ? (a - b) / Math.abs(b) * 100 : 0; }
		function signed(v, p) { return (v > 0 ? '+' : '') + num(v, p); }

		// Updates cells in place so a rate the user is typing is never wiped.
		function render(result) {
			const active = document.activeElement;
			let free = 0;
			$body.find('tbody tr').each(function () {
				const $tr = $(this), r = state.rows[cint($tr.attr('data-idx'))], it = item_of(frm, r);
				const fixed = r.mode === 'Fixed';
				if (!fixed) free++;
				$tr.find('.tt-mode').val(r.mode);
				const $rate = $tr.find('.tt-rate');
				if ($rate[0] !== active) $rate.val(rate_str(it.rate, it));
				const change = pct(flt(it.rate), state.snap[r.idx].rate);
				$tr.find('.tt-delta').text(Math.abs(change) >= 0.005 ? signed(change, 2) + '%' : '')
					.toggleClass('is-up', change > 0).toggleClass('is-down', change < 0);
				$tr.find('.tt-new-amount').text(num(it.amount));
				$tr.find('.tt-disc').text(flt(it.discount_percentage) ? num(it.discount_percentage, 2) + '%' : '');
				$tr.toggleClass('tt-fixed', fixed).toggleClass('tt-typed', fixed && r.typed_rate !== null);
				$tr.toggleClass('tt-margin', !!r.margin);
				$tr.attr('title', r.margin ? __('Above price list rate: creates a margin (rejected by AGT on invoices). Use Price List Rate.') : '');
			});
			$body.find('.tt-free-count').text(__('{0} free of {1}', [free, state.rows.length]));

			const percent_mode = state.mode === 'Percent';
			$body.find('.isoft-tt-only-target').toggle(!percent_mode);
			$body.find('.isoft-tt-only-percent').toggle(percent_mode);
			$body.find('.tt-round-toggle').prop('checked', !!state.rounding);

			const cur = ns.current(frm, state.kind);
			const was = state.kind === 'Grand Total' ? open_totals.grand : open_totals.net;
			$body.find('.tt-kpi-current').text(money(cur, frm)).attr('title', __('{0} when opened', [money(was, frm)]));
			const diff = state.target - cur;
			$body.find('.tt-kpi-diff').text(money(diff, frm)).toggleClass('is-zero', Math.abs(diff) <= TOL).parent().toggle(!percent_mode);
			$body.find('.tt-kpi-diff-sub').text(__('{0} vs when opened', [signed(pct(percent_mode ? cur : state.target, was), 2) + '%']));

			const $st = $body.find('.isoft-tt-status').removeClass('tt-ok tt-warn tt-bad');
			const $sub = $body.find('.tt-kpi-status-sub').text('');
			const step_note = state.rounding ? ' \u00b7 ' + __('rounded') : '';
			if (result.reason) {
				$st.addClass('tt-bad').text(result.reason);
			} else if (result.percent) {
				$st.addClass('tt-ok').text(__('Prices {0}', [signed(flt(state.percent), 2) + '%']) + step_note);
				$sub.text(__('Apply to keep these prices'));
			} else if (result.rounded) {
				$st.addClass('tt-warn').text(__('Off by {0}: prices rounded', [money(result.diff, frm)]));
				$sub.text(__('Closest total with every free line rounded'));
			} else if (Math.abs(result.diff) <= TOL) {
				$st.addClass('tt-ok').text(__('On target') + step_note);
				$sub.text(__('Apply to keep these prices'));
			} else if (Math.abs(result.diff) <= WARN) {
				$st.addClass('tt-warn').text(__('Off by {0} (rounding)', [money(result.diff, frm)]));
				$sub.text(__('No two-decimal rates reach this exact cent'));
			} else {
				$st.addClass('tt-bad').text(__('Could not reach the target exactly: off by {0}', [money(result.diff, frm)]));
			}

			$body.find('.tt-net').text(money(frm.doc.net_total, frm)).attr('title', __('was {0}', [money(open_totals.net, frm)]));
			$body.find('.tt-tax').text(money(frm.doc.total_taxes_and_charges, frm)).attr('title', __('was {0}', [money(open_totals.tax, frm)]));
			$body.find('.tt-grand').text(money(frm.doc.grand_total, frm)).attr('title', __('was {0}', [money(open_totals.grand, frm)]));

			const $note = $body.find('.isoft-tt-note').empty();
			if (state.rows.some(function (r) { return r.margin; })) {
				$note.append('<span class="isoft-tt-badge is-warn">' + __('Margin') + '</span> ' +
					__('Above price list rate: creates a margin (rejected by AGT on invoices). Use Price List Rate.'));
			}
			d.get_primary_btn().prop('disabled', !!result.reason);
		}

		function refit() {
			if (closed) return;
			const result = ns.fit(frm, state);
			render(result);
			fit_height();
			frm.refresh_field('items');
			frm.cscript.calculate_taxes_and_totals();
		}

		// Keeps the whole modal inside the viewport: only the lines table scrolls,
		// never the page. Re-run on every render and on window resize.
		function fit_height() {
			const $scroll = $body.find('.isoft-tt-scroll');
			const $dialog = d.$wrapper.find('.modal-dialog');
			if (!$scroll.length || !$dialog.length || !$dialog.is(':visible')) return;
			$scroll.css('max-height', '');
			const top = Math.max(0, $dialog[0].getBoundingClientRect().top);
			const overflow = $dialog.outerHeight() + 2 * top - window.innerHeight + 2;  // +2: never a 1px page scroll from rounding
			if (overflow > 0) $scroll.css('max-height', Math.max(110, $scroll.height() - overflow) + 'px');
		}
		$(window).on('resize.isoft-tt', fit_height);

		function set_seg($seg, value) {
			$seg.find('.isoft-tt-seg-btn').each(function () { $(this).toggleClass('is-on', $(this).data('value') === value); });
		}

		// Small API, also used by the browser checks.
		d.tt = {
			set_target: function (v) { state.target = flt(v); $body.find('.isoft-tt-target').val(num(state.target)); refit(); },
			set_kind: function (k) { state.kind = k; set_seg($body.find('.tt-kind'), k); d.tt.set_target(ns.current(frm, k)); },
			set_mode: function (m) { state.mode = m; set_seg($body.find('.tt-mode-switch'), m); refit(); },
			set_percent: function (p) { state.percent = flt(p); $body.find('.isoft-tt-percent').val(num(state.percent)); refit(); },
			set_rounding: function (on) { state.rounding = !!on; refit(); },
			open_settings: function () { ns.open_settings(function () { refit(); }); },
			set_default_mode: function (m) {
				state.default_mode = m; set_seg($body.find('.tt-default-mode'), m);
				state.rows = ns.math.set_default_mode(state.rows, m);
				state.rows.forEach(function (r) { if (r.locked) r.mode = 'Fixed'; });
				refit();
			},
			state: state
		};

		$body.on('click', '.tt-mode-switch .isoft-tt-seg-btn', function () { d.tt.set_mode($(this).data('value')); });
		$body.on('change', '.isoft-tt-percent', function () { d.tt.set_percent(parse($(this).val())); });
		$body.on('keydown', '.isoft-tt-percent', function (e) { if (e.key === 'Enter') { e.preventDefault(); $(this).blur(); } });
		$body.on('focus', '.isoft-tt-percent', function () { $(this).select(); });
		$body.on('click', '.tt-pct-minus', function () { d.tt.set_percent(flt(state.percent) - 1); });
		$body.on('click', '.tt-pct-plus', function () { d.tt.set_percent(flt(state.percent) + 1); });
		$body.on('change', '.tt-round-toggle', function () { d.tt.set_rounding($(this).prop('checked')); });
		$body.on('click', '.tt-settings', function () { d.tt.open_settings(); });
		$body.on('click', '.tt-kind .isoft-tt-seg-btn', function () { d.tt.set_kind($(this).data('value')); });
		$body.on('click', '.tt-default-mode .isoft-tt-seg-btn', function () { d.tt.set_default_mode($(this).data('value')); });
		$body.on('change', '.isoft-tt-target', function () { d.tt.set_target(parse($(this).val())); });
		$body.on('keydown', '.isoft-tt-target', function (e) { if (e.key === 'Enter') { e.preventDefault(); $(this).blur(); } });
		$body.on('focus', '.isoft-tt-target', function () { $(this).select(); });
		$body.on('click', '.tt-fix-all', function () { state.rows.forEach(function (r) { r.mode = 'Fixed'; }); refit(); });
		$body.on('click', '.tt-free-all', function () {
			state.rows.forEach(function (r) { if (!r.locked) { r.mode = state.default_mode; r.typed_rate = null; r.typed_mode = null; } });
			refit();
		});
		$body.on('change', '.tt-mode', function () {
			const r = state.rows[cint($(this).closest('tr').attr('data-idx'))];
			r.mode = $(this).val();
			if (r.mode !== 'Fixed') { r.typed_rate = null; r.typed_mode = null; }
			refit();
		});
		$body.on('input', '.tt-rate', debounce(function () {
			const $tr = $(this).closest('tr'), r = state.rows[cint($tr.attr('data-idx'))];
			const v = $(this).val();
			if (v === '') { r.typed_rate = null; r.typed_mode = null; r.mode = r.locked ? 'Fixed' : state.default_mode; }
			else {
				if (r.mode !== 'Fixed') r.typed_mode = r.mode;
				else if (!r.typed_mode) r.typed_mode = state.default_mode;
				r.typed_rate = flt(v);
				r.mode = 'Fixed';
			}
			refit();
		}, 150, function (t) { pending = t; }));
		$body.on('keydown', '.tt-rate', function (e) {
			// Enter moves to the next line's rate, like a grid.
			if (e.key === 'Enter') { e.preventDefault(); $(this).closest('tr').next().find('.tt-rate:not(:disabled)').focus().select(); }
		});

		build();
		d.show();
		refit();
		d.$wrapper.one('shown.bs.modal', fit_height);
		setTimeout(function () { $body.find('.isoft-tt-target').focus().select(); }, 300);
		return d;
	};

	// ------------------------------------------------------- settings dialog

	const SAMPLES = [1030, 1015, 1070, 22390];

	function rules_from_dom($w) {
		return {
			base: parse($w.find('.tt-set-base').val()),
			rules: $w.find('.tt-rule-row').map(function () {
				return { upto: parse($(this).find('.tt-rule-upto').val()), to: parse($(this).find('.tt-rule-to').val()) };
			}).get()
		};
	}

	function validate_rules(cfg) {
		if (!(cfg.base > 0)) return __('Block size must be greater than zero');
		for (let i = 0; i < cfg.rules.length; i++) {
			const r = cfg.rules[i];
			if (!(r.upto > 0 && r.upto <= cfg.base) || !(r.to >= 0 && r.to <= cfg.base)) {
				return __('Thresholds must be between 0 and the block size');
			}
		}
		return null;
	}

	ns.open_settings = function (on_saved) {
		if (ns._settings_dialog) return ns._settings_dialog;
		const cfg = ns._settings || {};
		const can_write = !!cfg.can_write;
		const d = new frappe.ui.Dialog({
			title: __('Pricing Assistant Settings'),
			size: 'large',
			fields: [{ fieldname: 'body', fieldtype: 'HTML' }],
			primary_action_label: __('Save'),
			primary_action: function () {
				const next = rules_from_dom($w);
				const err = validate_rules(next);
				if (err) { frappe.msgprint(err); return; }
				next.rules.sort(function (a, b) { return a.upto - b.upto; });
				next.default_target_kind = $w.find('.tt-set-kind .is-on').data('value');
				next.default_line_mode = $w.find('.tt-set-mode .is-on').data('value');
				next.apply_rounding_by_default = $w.find('.tt-set-default-on').prop('checked') ? 1 : 0;
				frappe.call({
					method: 'isoft_customization.pricing_assistant.save_settings',
					args: { settings: next },
					freeze: true
				}).then(function (r) {
					ns._settings = r.message || next;
					d.hide();
					on_saved && on_saved();
				});
			}
		});
		d.$wrapper.addClass('isoft-tt-settings isoft-tt-modal');
		d.onhide = function () { if (ns._settings_dialog === d) ns._settings_dialog = null; d.$wrapper.remove(); };
		ns._settings_dialog = d;
		const $w = $(d.fields_dict.body.wrapper);
		const dis = can_write ? '' : ' disabled';

		function row_html(r) {
			return '<div class="tt-rule-row">' +
				'<span class="tt-rule-text">' + __('Remainder below') + '</span><input type="text" inputmode="decimal" class="tt-rule-upto"' + dis + ' value="' + num(r.upto, 2) + '">' +
				'<span class="tt-rule-text">' + __('round to') + '</span><input type="text" inputmode="decimal" class="tt-rule-to"' + dis + ' value="' + num(r.to, 2) + '">' +
				(can_write ? '<button type="button" class="isoft-tt-iconbtn tt-rule-del" title="' + __('Remove') + '">&times;</button>' : '') +
			'</div>';
		}

		$w.html(
			'<div class="isoft-tt isoft-tt-set">' +
				(can_write ? '' : '<div class="isoft-tt-set-note">' + __('Only System Manager or Sales Manager can change these settings') + '</div>') +
				'<div class="isoft-tt-set-card">' +
					'<div class="isoft-tt-set-head"><b>' + __('Rounding rule') + '</b>' +
						'<span class="isoft-tt-set-sub">' + __('Prices are split into blocks of the block size; the remainder decides where the price lands.') + '</span></div>' +
					'<div class="isoft-tt-set-base"><span class="isoft-tt-bar-label">' + __('Block size') + '</span>' +
						'<input type="text" inputmode="decimal" class="tt-set-base"' + dis + ' value="' + num(cfg.base || 100, 2) + '"></div>' +
					'<div class="tt-rules">' + (cfg.rules || []).map(row_html).join('') + '</div>' +
					(can_write ? '<button type="button" class="isoft-tt-chip tt-rule-add">+ ' + __('Add threshold') + '</button>' : '') +
					'<div class="isoft-tt-set-preview"><span class="isoft-tt-bar-label">' + __('Examples') + '</span> <span class="tt-rule-preview"></span></div>' +
					'<div class="isoft-tt-set-hint">' + __('Above every threshold the price goes up to the next block. Prices on multiples of 50 give whole-number IVA at 14%.') + '</div>' +
				'</div>' +
				'<div class="isoft-tt-set-card">' +
					'<div class="isoft-tt-set-head"><b>' + __('Defaults when the assistant opens') + '</b></div>' +
					'<div class="isoft-tt-set-grid">' +
						'<div><span class="isoft-tt-bar-label">' + __('Target kind') + '</span>' +
							seg('tt-set-kind', [{ value: 'Grand Total', label: __('Grand Total') }, { value: 'Net Total', label: __('Net Total') }], cfg.default_target_kind || 'Grand Total') + '</div>' +
						'<div><span class="isoft-tt-bar-label">' + __('Free lines mode') + '</span>' +
							seg('tt-set-mode', [{ value: 'Price List Rate', label: __('Price List Rate') }, { value: 'Rate', label: __('Rate') }], cfg.default_line_mode || 'Price List Rate') + '</div>' +
						'<label class="isoft-tt-switch"><input type="checkbox" class="tt-set-default-on"' + dis + (cint(cfg.apply_rounding_by_default) ? ' checked' : '') + '>' +
							'<span class="isoft-tt-switch-track"></span><span class="isoft-tt-switch-label">' + __('Rounding on when the assistant opens') + '</span></label>' +
					'</div>' +
				'</div>' +
			'</div>'
		);
		if (!can_write) { d.get_primary_btn().hide(); $w.find('.isoft-tt-seg-btn').prop('disabled', true); }

		function preview() {
			const next = rules_from_dom($w);
			const err = validate_rules(next);
			$w.find('.tt-rule-preview').text(err ? err : SAMPLES.map(function (v) {
				return num(v, 0) + ' → ' + num(ns.math.round_rule(v, next), 0);
			}).join('   ·   ')).toggleClass('is-err', !!err);
		}
		$w.on('input', '.tt-set-base, .tt-rule-upto, .tt-rule-to', preview);
		$w.on('click', '.tt-rule-add', function () { $w.find('.tt-rules').append(row_html({ upto: 0, to: 0 })); $w.find('.tt-rule-row:last .tt-rule-upto').focus(); preview(); });
		$w.on('click', '.tt-rule-del', function () { $(this).closest('.tt-rule-row').remove(); preview(); });
		$w.on('click', '.isoft-tt-seg-btn', function () {
			if (!can_write) return;
			const $seg = $(this).closest('.isoft-tt-seg');
			$seg.find('.isoft-tt-seg-btn').removeClass('is-on'); $(this).addClass('is-on');
		});
		preview();
		d.show();
		return d;
	};
})(isoft.target_total);
