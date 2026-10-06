// Keep Delivery Note prices on the Sales Invoice made from it.
//
// Controlled by two Selling Settings switches (shipped in boot) and enforced in
// isoft_customization/delivery_note_prices.py:
//
// * Keep Delivery Note Prices on Sales Invoice. ERPNext already refuses to re-price a
//   document that was just mapped from another one: make_sales_invoice sets
//   __onload.ignore_price_list and the currency, posting date, exchange rate and
//   pricing rule triggers all honour it. __onload does not survive a save though, so
//   a saved draft is re-priced by the first edit. This keeps the flag alive on every
//   draft that has Delivery Note rows, and stops the two triggers core leaves
//   unguarded: the price list and a row's UOM / conversion factor.
// * Do Not Apply Pricing Rules on Rows from a Delivery Note. Only the pricing rule
//   trigger is stopped, and only for Delivery Note rows; everything else, including
//   typing a new rate, still works.

(function () {
	function has_dn_rows(frm) {
		return frm.doc.docstatus === 0 && (frm.doc.items || []).some((d) => d.dn_detail);
	}

	function keeps_prices(frm) {
		return cint(frappe.boot.isoft_keep_delivery_note_prices) && has_dn_rows(frm);
	}

	function no_pricing_rules(frm) {
		return cint(frappe.boot.isoft_no_pricing_rules_from_delivery_note) && has_dn_rows(frm);
	}

	function arm(frm) {
		if (!keeps_prices(frm)) return;
		frm.doc.__onload = frm.doc.__onload || {};
		frm.doc.__onload.ignore_price_list = true;
	}

	const PRICE_FIELDS = [
		"price_list_rate", "discount_percentage", "discount_amount", "margin_type",
		"margin_rate_or_amount", "rate_with_margin", "rate", "pricing_rules",
	];

	frappe.ui.form.on("Sales Invoice", {
		setup(frm) {
			const cscript = frm.cscript;
			if (cscript.isoft_core_apply_price_list) return;

			cscript.isoft_core_apply_price_list = cscript.apply_price_list;
			cscript.apply_price_list = function (item) {
				const rows = item ? [item] : (this.frm.doc.items || []);
				if (keeps_prices(this.frm) && rows.length && rows.every((d) => d.dn_detail)) {
					this.calculate_taxes_and_totals();
					return;
				}
				return cscript.isoft_core_apply_price_list.apply(this, arguments);
			};

			cscript.isoft_core_apply_pricing_rule = cscript.apply_pricing_rule;
			cscript.apply_pricing_rule = function (item, calculate_taxes_and_totals) {
				// The first switch already stops this through ignore_price_list.
				if (keeps_prices(this.frm) || !no_pricing_rules(this.frm)) {
					return cscript.isoft_core_apply_pricing_rule.apply(this, arguments);
				}
				if (item && item.dn_detail) {
					if (calculate_taxes_and_totals) this.calculate_taxes_and_totals();
					return;
				}
				// Whole document, or a row that is not from a Delivery Note: let the
				// other rows have their rules, then put the Delivery Note rows back.
				const kept = {};
				(this.frm.doc.items || []).forEach((d) => {
					if (d.dn_detail) kept[d.name] = Object.fromEntries(PRICE_FIELDS.map((f) => [f, d[f]]));
				});
				const me = this;
				return $.when(cscript.isoft_core_apply_pricing_rule.apply(this, arguments)).then(() => {
					(me.frm.doc.items || []).forEach((d) => {
						if (kept[d.name]) Object.assign(d, kept[d.name]);
					});
					me.frm.refresh_field("items");
					me.calculate_taxes_and_totals();
				});
			};
		},

		onload: arm,
		refresh: arm,
	});
})();
