// Adds a bulk "Stop" action to the Material Request list view.
// Loaded after erpnext's material_request_list.js, so it extends the existing
// listview_settings instead of replacing them.

frappe.provide("frappe.listview_settings");

(function () {
	const settings = (frappe.listview_settings["Material Request"] =
		frappe.listview_settings["Material Request"] || {});

	function report(listview, r) {
		const stopped = (r.stopped || []).length;
		const skipped = r.skipped || [];
		const failed = r.failed || [];

		let message = __("Stopped {0} Material Request(s).", [stopped]);

		const detail = (rows) =>
			"<ul>" +
			rows
				.map((d) => `<li>${frappe.utils.escape_html(d.name)} &mdash; ${frappe.utils.escape_html(d.reason || "")}</li>`)
				.join("") +
			"</ul>";

		if (skipped.length) {
			message += `<br><br><b>${__("Skipped")}</b>${detail(skipped)}`;
		}
		if (failed.length) {
			message += `<br><br><b>${__("Failed")}</b>${detail(failed)}`;
		}

		frappe.msgprint({
			title: __("Bulk Stop"),
			message: message,
			indicator: failed.length ? "red" : stopped ? "green" : "orange",
		});

		// drop the selection, then reload so the new statuses show
		listview.$result.find(".list-row-checkbox:checked").prop("checked", false);
		listview.$result.find(".list-check-all").prop("checked", false);
		listview.on_row_checked();
		listview.refresh();
	}

	function bulk_stop(listview) {
		const items = listview.get_checked_items();
		if (!items.length) {
			frappe.msgprint(__("Please select at least one Material Request"));
			return;
		}

		const eligible = items.filter((d) => cint(d.docstatus) === 1 && d.status !== "Stopped");
		const ignored = items.length - eligible.length;

		if (!eligible.length) {
			frappe.msgprint({
				title: __("Nothing to Stop"),
				message: __("None of the selected Material Requests are submitted and open."),
				indicator: "orange",
			});
			return;
		}

		let message = __("Stop {0} Material Request(s)?", [eligible.length]);
		if (ignored) {
			message +=
				"<br>" +
				__("{0} selected document(s) will be ignored (draft, cancelled or already stopped).", [
					ignored,
				]);
		}

		frappe.confirm(message, () => {
			frappe.call({
				method: "isoft_customization.material_request.bulk_stop",
				args: { names: eligible.map((d) => d.name) },
				freeze: true,
				freeze_message: __("Stopping Material Requests..."),
				callback: (r) => {
					if (r.message) report(listview, r.message);
				},
			});
		});
	}

	const original_onload = settings.onload;

	settings.onload = function (listview) {
		original_onload && original_onload(listview);

		if (!frappe.model.can_write("Material Request")) return;

		const action = {
			label: __("Stop", null, "Button in list view actions menu"),
			action: () => bulk_stop(listview),
			standard: true,
		};

		// the Actions dropdown is built before onload runs, so add to it directly
		listview.page.add_actions_menu_item(action.label, action.action, action.standard);

		// the selection bar builds its buttons from this list on first selection
		listview.actions_menu_items = listview.actions_menu_items || [];
		listview.actions_menu_items.push(action);
	};
})();
