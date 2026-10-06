// Keep the prices of the Delivery Note / Purchase Receipt on the invoice made from it.
//
// Controlled by two switches per side on Selling / Buying Settings (shipped in boot) and
// enforced in isoft_customization/linked_document_prices.py:
//
// * Keep <source> Prices. ERPNext already refuses to re-price a document that was just
//   mapped from another one: the mapper sets __onload.ignore_price_list and the
//   currency, exchange rate and pricing rule triggers all honour it. __onload does not
//   survive a save though, so a saved draft is re-priced by the first such edit. This
//   keeps the flag alive on every draft that has source rows, and stops the two
//   triggers core leaves unguarded: the price list and a row's UOM / conversion factor.
// * Do Not Apply Pricing Rules on Rows from a <source>. Only the pricing rule trigger
//   is stopped, and only for source rows; everything else, including typing a new
//   rate, still works.
//
// Loaded with app_include_js so one file serves both invoices; the handlers run after
// ERPNext's controller has been mixed into frm.cscript, which is what gets wrapped.

(function () {
	const LINKS = {
		"Sales Invoice": { ref: "dn_detail", keep: "isoft_keep_delivery_note_prices", no_rules: "isoft_no_pricing_rules_from_delivery_note" },
		"Purchase Invoice": { ref: "pr_detail", keep: "isoft_keep_purchase_receipt_prices", no_rules: "isoft_no_pricing_rules_from_purchase_receipt" },
	};

	const PRICE_FIELDS = [
		"price_list_rate", "discount_percentage", "discount_amount", "margin_type",
		"margin_rate_or_amount", "rate_with_margin", "rate", "pricing_rules",
	];

	function source_rows(frm) {
		const link = LINKS[frm.doctype];
		if (frm.doc.docstatus !== 0) return [];
		return (frm.doc.items || []).filter((d) => d[link.ref]);
	}

	function keeps_prices(frm) {
		return cint(frappe.boot[LINKS[frm.doctype].keep]) && source_rows(frm).length > 0;
	}

	function no_pricing_rules(frm) {
		return cint(frappe.boot[LINKS[frm.doctype].no_rules]) && source_rows(frm).length > 0;
	}

	function arm(frm) {
		if (!keeps_prices(frm)) return;
		frm.doc.__onload = frm.doc.__onload || {};
		frm.doc.__onload.ignore_price_list = true;
	}

	function wrap(frm) {
		const cscript = frm.cscript;
		const ref = LINKS[frm.doctype].ref;
		if (cscript.isoft_core_apply_price_list) return;

		cscript.isoft_core_apply_price_list = cscript.apply_price_list;
		cscript.apply_price_list = function (item) {
			const rows = item ? [item] : (this.frm.doc.items || []);
			if (keeps_prices(this.frm) && rows.length && rows.every((d) => d[ref])) {
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
			if (item && item[ref]) {
				if (calculate_taxes_and_totals) this.calculate_taxes_and_totals();
				return;
			}
			// Whole document, or a row that is not from the source: let the other rows
			// have their rules, then put the source rows back.
			const kept = {};
			(this.frm.doc.items || []).forEach((d) => {
				if (d[ref]) kept[d.name] = Object.fromEntries(PRICE_FIELDS.map((f) => [f, d[f]]));
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
	}

	Object.keys(LINKS).forEach((doctype) => {
		frappe.ui.form.on(doctype, { setup: wrap, onload: arm, refresh: arm });
	});
})();
