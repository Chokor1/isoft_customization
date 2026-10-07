// Target Total Assistant: fit the free item lines of a draft Quotation /
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
		item.price_list_rate = new_rate;
		item.rate = new_rate;
		clear_discount(item);
		clear_margin(item);
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

		function S(k) {
			free.forEach(function (r) {
				const it = item_of(frm, r);
				ns.write_rate(it, math.scaled_rate(r.original_rate, k, precision('rate', it)), r.mode);
			});
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
		return finish(Math.abs(diff) <= WARN);
	};

	// ---------------------------------------------------------------- dialog

	function money(v, frm) { return format_currency(v, frm.doc.currency); }

	function rate_str(v, it) { return flt(v, precision('rate', it)).toString(); }

	// Debounce whose pending timer is handed to `track` so the caller can cancel it.
	function debounce(fn, wait, track) {
		let t;
		return function () {
			const args = arguments, ctx = this;
			clearTimeout(t);
			t = setTimeout(function () { fn.apply(ctx, args); }, wait);
			track && track(t);
		};
	}

	ns.open = function (frm) {
		const state = {
			kind: 'Grand Total',
			target: ns.current(frm, 'Grand Total'),
			default_mode: 'Price List Rate',
			snap: ns.snapshot(frm),
			rows: (frm.doc.items || []).map(function (it, i) {
				const locked = flt(it.qty) === 0;
				return { idx: i, mode: locked ? 'Fixed' : 'Price List Rate', locked: locked,
					original_rate: flt(it.rate), typed_rate: null, typed_mode: null, margin: false };
			})
		};
		let applied = false, closed = false, pending = null;

		const d = new frappe.ui.Dialog({
			title: __('Target Total Assistant'),
			size: 'extra-large',
			fields: [
				{ fieldname: 'kind', fieldtype: 'Select', label: __('Target kind'),
					options: ['Grand Total', 'Net Total'].map(function (o) { return { value: o, label: __(o) }; }),
					default: 'Grand Total', change: function () { state.kind = d.get_value('kind'); state.target = ns.current(frm, state.kind); d.set_value('target', state.target); } },
				{ fieldname: 'cb1', fieldtype: 'Column Break' },
				{ fieldname: 'target', fieldtype: 'Currency', label: __('Target'), options: 'currency',
					default: state.target, change: function () { state.target = flt(d.get_value('target')); refit(); } },
				{ fieldname: 'cb2', fieldtype: 'Column Break' },
				{ fieldname: 'default_mode', fieldtype: 'Select', label: __('Default mode for free lines'),
					options: ['Price List Rate', 'Rate'].map(function (o) { return { value: o, label: __(o) }; }),
					default: 'Price List Rate', change: function () {
						state.default_mode = d.get_value('default_mode');
						state.rows = ns.math.set_default_mode(state.rows, state.default_mode);
						state.rows.forEach(function (r) { if (r.locked) r.mode = 'Fixed'; });
						build_table(); refit();
					} },
				{ fieldname: 'sb', fieldtype: 'Section Break' },
				{ fieldname: 'lines', fieldtype: 'HTML' }
			],
			primary_action_label: __('Apply'),
			primary_action: function () { applied = true; frm.dirty(); d.hide(); },
			secondary_action_label: __('Reset'),
			secondary_action: function () {
				state.rows.forEach(function (r) { r.typed_rate = null; r.typed_mode = null; r.mode = r.locked ? 'Fixed' : state.default_mode; });
				state.target = ns.current(frm, state.kind);
				// current() must read the original totals: restore first.
				ns.restore(frm, state.snap); ns.recalc_silent(frm);
				state.target = ns.current(frm, state.kind);
				d.set_value('target', state.target);
				build_table(); refit();
			}
		});
		d.add_custom_action(__('Cancel'), function () { d.hide(); });
		d.onhide = function () {
			closed = true;
			clearTimeout(pending);
			if (!applied) { ns.restore(frm, state.snap); }
			frm.refresh_field('items');
			frm.cscript.calculate_taxes_and_totals();
			if (ns._dialog === d) ns._dialog = null;
			d.$wrapper.remove();
		};
		ns._dialog = d;

		const $body = $(d.fields_dict.lines.wrapper);

		function build_table() {
			const rows_html = state.rows.map(function (r) {
				const it = item_of(frm, r);
				const options = MODES.map(function (m) {
					return '<option value="' + m + '"' + (m === r.mode ? ' selected' : '') + '>' + __(m) + '</option>';
				}).join('');
				const dis = r.locked ? ' disabled' : '';
				return '<tr data-idx="' + r.idx + '">' +
					'<td class="tt-idx">' + (r.idx + 1) + '</td>' +
					'<td class="tt-item"><div>' + frappe.utils.escape_html(it.item_code || '') + '</div>' +
						'<div class="text-muted small">' + frappe.utils.escape_html(it.item_name || '') + '</div></td>' +
					'<td class="text-right">' + flt(it.qty) + '</td>' +
					'<td class="text-right">' + money(state.snap[r.idx].rate, frm) + '</td>' +
					'<td class="text-right tt-cur-amount">' + money(state.snap[r.idx].rate * flt(it.qty), frm) + '</td>' +
					'<td><select class="form-control input-sm tt-mode"' + dis + '>' + options + '</select></td>' +
					'<td><input type="number" step="any" class="form-control input-sm text-right tt-rate"' + dis + ' value="' + rate_str(it.rate, it) + '"></td>' +
					'<td class="text-right tt-new-amount"></td>' +
					'<td class="text-right tt-disc"></td>' +
				'</tr>';
			}).join('');
			$body.html(
				'<div class="isoft-tt-wrap">' +
				'<table class="table table-bordered isoft-tt-table"><thead><tr>' +
					'<th>#</th><th>' + __('Item') + '</th><th class="text-right">' + __('Qty') + '</th>' +
					'<th class="text-right">' + __('Current rate') + '</th><th class="text-right">' + __('Current amount') + '</th>' +
					'<th>' + __('Mode') + '</th><th class="text-right">' + __('New rate') + '</th>' +
					'<th class="text-right">' + __('New amount') + '</th><th class="text-right">' + __('Discount %') + '</th>' +
				'</tr></thead><tbody>' + rows_html + '</tbody></table>' +
				'<div class="isoft-tt-footer">' +
					'<div class="isoft-tt-totals"></div>' +
					'<div class="isoft-tt-status"></div>' +
				'</div></div>'
			);
		}

		// Updates cells in place so a rate the user is typing is never wiped.
		function render(result) {
			const active = document.activeElement;
			$body.find('tbody tr').each(function () {
				const $tr = $(this), r = state.rows[cint($tr.attr('data-idx'))], it = item_of(frm, r);
				$tr.find('.tt-mode').val(r.mode);
				const $rate = $tr.find('.tt-rate');
				if ($rate[0] !== active) $rate.val(rate_str(it.rate, it));
				$tr.find('.tt-new-amount').text(money(it.amount, frm));
				$tr.find('.tt-disc').text(flt(it.discount_percentage) ? flt(it.discount_percentage, 2) + '%' : '');
				$tr.toggleClass('tt-fixed', r.mode === 'Fixed');
				$tr.toggleClass('tt-margin', !!r.margin);
				$tr.attr('title', r.margin ? __('Above price list rate: creates a margin (rejected by AGT on invoices). Use Price List Rate.') : '');
			});
			const cur = ns.current(frm, state.kind);
			$body.find('.isoft-tt-totals').html(
				'<span>' + __('Net Total') + ': <b>' + money(frm.doc.net_total, frm) + '</b></span>' +
				'<span>' + __('Taxes') + ': <b>' + money(frm.doc.total_taxes_and_charges, frm) + '</b></span>' +
				'<span>' + __('Grand Total') + ': <b>' + money(frm.doc.grand_total, frm) + '</b></span>' +
				'<span>' + __('Target') + ' (' + __(state.kind) + '): <b>' + money(state.target, frm) + '</b></span>' +
				'<span>' + __('Difference') + ': <b>' + money(state.target - cur, frm) + '</b></span>'
			);
			const $st = $body.find('.isoft-tt-status').removeClass('tt-ok tt-warn tt-bad');
			if (result.reason) {
				$st.addClass('tt-bad').text(result.reason);
			} else if (Math.abs(result.diff) <= TOL) {
				$st.addClass('tt-ok').text(__('On target'));
			} else if (Math.abs(result.diff) <= WARN) {
				$st.addClass('tt-warn').text(__('Off by {0} (rounding)', [money(result.diff, frm)]));
			} else {
				$st.addClass('tt-bad').text(__('Could not reach the target exactly: off by {0}', [money(result.diff, frm)]));
			}
			if (state.rows.some(function (r) { return r.margin; })) {
				$st.append('<div class="tt-margin-note">' +
					__('Above price list rate: creates a margin (rejected by AGT on invoices). Use Price List Rate.') + '</div>');
			}
		}

		function refit() {
			if (closed) return;
			const result = ns.fit(frm, state);
			render(result);
			frm.refresh_field('items');
			frm.cscript.calculate_taxes_and_totals();
		}

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

		build_table();
		d.show();
		refit();
		return d;
	};
})(isoft.target_total);
