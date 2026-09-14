// Reason prompts for cancelling selling documents and submitting credit notes.
//
// Controlled by the "Document Reasons" checkboxes on Selling Settings and enforced in
// isoft_customization/document_reasons.py. The server only asks once the document has
// passed validation (FE Angola, accounting periods, ERPNext): it raises
// CancellationReasonRequired / CreditNoteReasonRequired right before it would write.
// This file catches exactly those errors on the three desk requests that can raise
// them, asks the user, and replays the same request. A refused cancel therefore never
// asks for a reason, and closing the prompt leaves the document as it was.
//
// A request-level error handler also stops core from showing the server message, so
// the user sees the prompt instead of an error.

(function () {
	const METHOD = "isoft_customization.document_reasons.";
	const core_call = frappe.call;

	function ask_reason(title, label, value) {
		return new Promise((resolve) => {
			let reason = null;
			const dialog = new frappe.ui.Dialog({
				title: title,
				fields: [
					{ fieldname: "reason", fieldtype: "Small Text", label: label, reqd: 1, default: value || "" },
				],
				primary_action_label: __("Continue"),
				primary_action(values) {
					const text = (values.reason || "").trim();
					if (!text) {
						frappe.msgprint(__("Please enter a reason."));
						return;
					}
					reason = text;
					dialog.hide();
				},
			});
			dialog.onhide = () => resolve(reason);
			dialog.show();
		});
	}

	function parse(value) {
		return typeof value === "string" ? JSON.parse(value) : value;
	}

	function replay_cancel(opts, doctype, name, links, label) {
		ask_reason(__("Reason for Cancellation"), label).then((reason) => {
			if (!reason) {
				frappe.show_alert({ message: __("Not cancelled: a reason is required."), indicator: "orange" });
				return;
			}
			frappe.xcall(METHOD + "stash_cancel_reason", { doctype, name, reason, links })
				.then(() => frappe.call(opts));
		});
	}

	const HANDLERS = {
		"frappe.desk.form.save.cancel": (opts) => ({
			CancellationReasonRequired() {
				const args = opts.args || {};
				replay_cancel(opts, args.doctype, args.name, [],
					__("Why is {0} being cancelled?", [args.name]));
			},
		}),

		// Runs before the parent's own cancel. The reason covers the parent and every
		// linked document, so the parent's request that follows does not ask again.
		"frappe.desk.form.linked_with.cancel_all_linked_docs": (opts) => {
			const frm = window.cur_frm;
			if (!frm) return {};
			return {
				CancellationReasonRequired() {
					replay_cancel(opts, frm.doctype, frm.docname, parse(opts.args.docs),
						__("Why are {0} and its linked documents being cancelled?", [frm.docname]));
				},
			};
		},

		"frappe.desk.form.save.savedocs": (opts) => ({
			CreditNoteReasonRequired() {
				const doc = parse(opts.args.doc);
				ask_reason(__("Credit Note Reason"), __("Why is this credit note being issued?"), doc.return_reason)
					.then((reason) => {
						if (!reason) {
							frappe.show_alert({ message: __("Not submitted: a reason is required."), indicator: "orange" });
							return;
						}
						doc.return_reason = reason;
						opts.args.doc = doc;
						if (window.cur_frm && cur_frm.doc === doc) cur_frm.refresh_field("return_reason");
						frappe.call(opts);
					});
			},
		}),
	};

	frappe.call = function (opts) {
		const make = opts && typeof opts === "object" && HANDLERS[opts.method];
		if (make) {
			opts.error_handlers = Object.assign({}, opts.error_handlers, make(opts));
		}
		return core_call.apply(this, arguments);
	};
})();
