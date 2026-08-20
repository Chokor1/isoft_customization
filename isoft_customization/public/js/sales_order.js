// Create > Quotation on Sales Order, moved here from ERPNext's sales_order.js.
//
// ERPNext maps a Sales Order forward but offers no way back to a Quotation. The
// button appears while the order is not fully billed, matching the condition the
// core version used.
//
// Layered on with doctype_js, which Frappe merges across apps, so this stacks with
// ERPNext's own sales_order.js rather than replacing it.

frappe.ui.form.on('Sales Order', {
	refresh: function (frm) {
		if (frm.doc.docstatus !== 1) return;
		if (flt(frm.doc.per_billed, 6) >= 100) return;

		frm.add_custom_button(__('Quotation'), function () {
			frappe.model.open_mapped_doc({
				method: 'isoft_customization.sales_order.make_quotation',
				frm: frm
			});
		}, __('Create'));
	}
});
