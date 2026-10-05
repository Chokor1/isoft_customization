// Keep Delivery Note prices on the Sales Invoice made from it.
//
// Controlled by "Keep Delivery Note Prices on Sales Invoice" on Selling Settings
// (shipped in boot) and enforced in isoft_customization/delivery_note_prices.py.
//
// ERPNext already refuses to re-price a document that was just mapped from another
// one: make_sales_invoice sets __onload.ignore_price_list and the currency, posting
// date, exchange rate and pricing rule triggers all honour it. __onload does not
// survive a save though, so a saved draft is re-priced by the first edit. This keeps
// the flag alive on every draft that has Delivery Note rows, and stops the two
// triggers core leaves unguarded: the price list and a row's UOM / conversion factor.

(function () {
	function keeps_prices(frm) {
		return cint(frappe.boot.isoft_keep_delivery_note_prices)
			&& frm.doc.docstatus === 0
			&& (frm.doc.items || []).some((d) => d.dn_detail);
	}

	function arm(frm) {
		if (!keeps_prices(frm)) return;
		frm.doc.__onload = frm.doc.__onload || {};
		frm.doc.__onload.ignore_price_list = true;
	}

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
		},

		onload: arm,
		refresh: arm,
	});
})();
