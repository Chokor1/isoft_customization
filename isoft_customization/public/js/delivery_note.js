// Target Total Assistant button on the Delivery Note form.
//
// Opens the panel from public/js/target_total_assistant.js, which fits the free
// item lines so the Grand Total or Net Total lands on a typed target. Drafts
// with at least one item only.
//
// Layered on with doctype_js, which Frappe merges across apps, so this stacks
// with ERPNext's own delivery_note.js.

frappe.ui.form.on('Delivery Note', {
	refresh: function (frm) {
		if (frm.doc.docstatus !== 0 || !(frm.doc.items || []).length) return;
		isoft.target_total.add_button(frm);
	}
});
