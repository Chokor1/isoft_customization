// Queued-state handling for large Purchase Invoices.
//
// Server side (isoft_customization/background_submit.py) hands the submit or
// cancel of a document with many rows to a background worker and marks the
// form's __onload with isoft_background_queued while the job is pending. Here
// we hide the primary action so a second click cannot queue a duplicate job, and
// say what is going on. The worker's save publishes doc_update, which makes the
// desk reload the form on its own, and this script then restores the button.
//
// Layered on with doctype_js, which Frappe merges across apps, so it stacks with
// ERPNext's own purchase_invoice.js.

frappe.ui.form.on('Purchase Invoice', {
	refresh: function (frm) {
		const onload = frm.doc.__onload || {};
		const queued = !!onload.isoft_background_queued;
		const stale = cint(onload.isoft_background_stale_minutes);

		if (queued) {
			frm.disable_save();
			frm.set_intro(
				__('A background job is processing this document. Submit and Cancel are unavailable until it finishes; the form refreshes automatically.'),
				'orange'
			);
			frm.__isoft_background_queued = true;
		} else if (stale) {
			// The job never reached a worker. Give the button back so the next click
			// clears the orphaned lock and either re-queues or runs in the foreground.
			frm.enable_save();
			frm.set_intro(
				__('The background job queued {0} minutes ago never started. Check that the background workers are running, then Submit or Cancel again to retry.', [stale]),
				'red'
			);
			frm.__isoft_background_queued = true;
		} else if (frm.__isoft_background_queued) {
			frm.enable_save();
			frm.set_intro('');
			frm.__isoft_background_queued = false;
		}
	},
});
