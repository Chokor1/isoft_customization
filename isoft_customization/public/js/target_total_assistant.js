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
})(isoft.target_total);
