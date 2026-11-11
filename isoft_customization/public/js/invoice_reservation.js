// Invoice stock reservation: what a submitted Sales / Purchase Invoice still reserves or orders,
// and the Stop / Resume buttons. See isoft_customization/invoice_reservation.py.
frappe.provide("isoft.invoice_reservation");

(function () {
	const API = "isoft_customization.invoice_reservation.";

	const texts = (doctype) =>
		doctype === "Sales Invoice"
			? {
					box: "isoft_reserve_stock",
					pending: "Reserving {0} units until delivered",
					stopped: __("Reservation stopped"),
					group: __("Reservation"),
					stop: __("Stop reserving"),
					resume: __("Resume reserving"),
					confirm_stop: __("Stop reserving the undelivered quantities of this invoice? They will no longer count as Reserved."),
					confirm_resume: __("Count the undelivered quantities of this invoice as Reserved again?"),
			  }
			: {
					box: "isoft_order_stock",
					pending: "Ordering {0} units until received",
					stopped: __("Ordering stopped"),
					group: __("Ordering"),
					stop: __("Stop ordering"),
					resume: __("Resume ordering"),
					confirm_stop: __("Stop ordering the unreceived quantities of this invoice? They will no longer count as Ordered."),
					confirm_resume: __("Count the unreceived quantities of this invoice as Ordered again?"),
			  };

	const set_stopped = (frm, stopped, message) =>
		frappe.confirm(message, () =>
			frappe.call({
				method: API + "set_stopped",
				args: { doctype: frm.doctype, name: frm.doc.name, stopped: stopped ? 1 : 0 },
				freeze: true,
				callback: () => frm.reload_doc(),
			})
		);

	isoft.invoice_reservation.render = function (frm, summary) {
		const t = texts(frm.doctype);
		frm.remove_custom_button(t.stop, t.group);
		frm.remove_custom_button(t.resume, t.group);
		if (!summary || !summary.enabled) return;
		if (summary.stopped) {
			frm.dashboard.set_headline_alert(t.stopped, "gray");
			frm.add_custom_button(t.resume, () => set_stopped(frm, false, t.confirm_resume), t.group);
		} else if (flt(summary.pending_qty) > 0) {
			const qty = flt(summary.pending_qty, 3);
			frm.dashboard.set_headline_alert(__(t.pending, [format_number(qty, null, qty % 1 ? 3 : 0)]), "blue");
			frm.add_custom_button(t.stop, () => set_stopped(frm, true, t.confirm_stop), t.group);
		}
	};

	const refresh = (frm) => {
		const t = texts(frm.doctype);
		if (frm.doc.docstatus !== 1 || !frm.doc[t.box]) return;
		frappe.call({
			method: API + "pending_summary",
			args: { doctype: frm.doctype, name: frm.doc.name },
			callback: (r) => isoft.invoice_reservation.render(frm, r.message),
		});
	};

	["Sales Invoice", "Purchase Invoice"].forEach((doctype) => frappe.ui.form.on(doctype, { refresh }));
})();
