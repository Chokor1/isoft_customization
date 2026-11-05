// Barcode UOM on scan in selling documents (server: isoft_customization/barcode_uom.py).
//
// ERPNext's scan (erpnext.TransactionController) adds or increments a row by item
// code only and leaves it in the item's default UOM. For a barcode that carries a
// UOM in the Item Barcode table this:
//   * matches an existing row by item AND that UOM (a Box barcode never bumps the
//     PCS row of the same item, and vice versa);
//   * lets ERPNext add the row exactly as before, waits until its item-details
//     calls have finished, then sets the barcode's UOM on the row - the same thing a
//     user does by changing the UOM, so ERPNext fetches the conversion factor and
//     that UOM's price itself.
// Anything else (barcodes without a UOM, serial and batch scans, other doctypes such
// as Stock Entry) goes through ERPNext's original methods untouched.
//
// erpnext.min.js loads after this app's scripts, so the prototype is patched on app_ready.

frappe.provide('isoft.barcode_uom');

(function (ns) {
	const DOCTYPES = ['Sales Order', 'Delivery Note', 'Sales Invoice', 'POS Invoice'];
	const PENDING = '__isoft_scan_uom';   // UOM a row is about to receive (fast repeated scans)

	function applies(ctrl, data) {
		return !!(ctrl && ctrl.frm && DOCTYPES.includes(ctrl.frm.doctype) && data && data.uom &&
			data.item_code && !data.batch_no && !data.serial_no);
	}

	function row_uom(row) { return row[PENDING] || row.uom; }

	// Resolves once no request has been in flight for ~300 ms (ERPNext chains several
	// calls after an item is set); never waits longer than 15 s.
	function settled() {
		return new Promise(function (resolve) {
			let quiet = 0, waited = 0;
			(function tick() {
				quiet = frappe.request.ajax_count ? 0 : quiet + 1;
				waited += 100;
				if (quiet >= 3 || waited >= 15000) return resolve();
				setTimeout(tick, 100);
			})();
		});
	}

	ns.patch = function () {
		const C = window.erpnext && erpnext.TransactionController;
		if (!C || C.prototype.__isoft_barcode_uom) return;
		const proto = C.prototype;
		const original_row = proto.get_row_to_modify_on_scan;
		const original_set = proto.set_scanned_values;

		proto.get_row_to_modify_on_scan = function (row_to_modify, data) {
			if (!applies(this, data)) return original_row.apply(this, arguments);
			const items = this.frm.doc.items || [];
			return items.find(function (d) { return d.item_code === data.item_code && row_uom(d) === data.uom; })
				|| items.find(function (d) { return !d.item_code; })
				|| row_to_modify;
		};

		proto.set_scanned_values = function (row, data, scan_barcode_field) {
			if (!applies(this, data)) return original_set.apply(this, arguments);
			const needs_uom = row_uom(row) !== data.uom || row.item_code !== data.item_code;
			if (needs_uom) row[PENDING] = data.uom;
			original_set.apply(this, arguments);
			if (!needs_uom) return;
			const cdt = row.doctype, cdn = row.name, frm = this.frm;
			return settled().then(function () {
				const r = locals[cdt] && locals[cdt][cdn];
				if (!r) return;
				delete r[PENDING];
				if (r.item_code !== data.item_code || r.uom === data.uom) return;
				return frappe.model.set_value(cdt, cdn, 'uom', data.uom).then(settled).then(function () {
					// ERPNext refetches the price only when the conversion factor changes; a UOM
					// with the same factor as the previous one (e.g. 1 and 1) would keep the old
					// UOM's price. Re-run its own conversion-factor step, which fetches the price.
					const now = locals[cdt] && locals[cdt][cdn];
					if (now && now.uom === data.uom) return frm.script_manager.trigger('conversion_factor', cdt, cdn);
				});
			});
		};

		proto.__isoft_barcode_uom = true;
	};

	ns.patch();
	$(document).on('app_ready', ns.patch);
})(isoft.barcode_uom);
