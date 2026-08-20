// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Party Account Replacement Tool", {
	setup: function (frm) {
		frm.set_query("new_account", function () {
			return { filters: account_query_filters(frm) };
		});
		frm.set_query("old_account", function () {
			return { filters: account_query_filters(frm) };
		});
	},

	refresh: function (frm) {
		frm.disable_save();

		frm.add_custom_button(__("Fetch Transactions"), function () {
			if (!frm.doc.company || !frm.doc.party_type || !frm.doc.party) {
				frappe.msgprint(__("Please set Company, Party Type and Party first."));
				return;
			}
			frappe.call({
				method: "fetch_transactions",
				doc: frm.doc,
				freeze: true,
				freeze_message: __("Fetching transactions..."),
				callback: function () {
					frm.reload_doc();
				},
			});
		}).addClass("btn-primary");

		frm.add_custom_button(__("Replace Account"), function () {
			if (!frm.doc.new_account) {
				frappe.msgprint(__("Please select a New Account."));
				return;
			}
			if (!(frm.doc.transactions || []).length) {
				frappe.msgprint(__("Fetch transactions first."));
				return;
			}
			frappe.confirm(
				__(
					"This will rewrite the party account on the selected submitted vouchers <b>and their posted GL entries</b> to {0}. There is no balancing journal entry. Continue?",
					[frm.doc.new_account.bold()]
				),
				function () {
					frappe.call({
						method: "replace_accounts",
						doc: frm.doc,
						freeze: true,
						freeze_message: __("Replacing party account..."),
						callback: function () {
							frm.reload_doc();
						},
					});
				}
			);
		});
	},

	company: function (frm) {
		clear_party_and_accounts(frm);
	},

	party_type: function (frm) {
		clear_party_and_accounts(frm);
	},
});

function account_query_filters(frm) {
	const account_type = frm.doc.party_type === "Supplier" ? "Payable" : "Receivable";
	const filters = { is_group: 0, account_type: account_type };
	if (frm.doc.company) {
		filters.company = frm.doc.company;
	}
	return filters;
}

function clear_party_and_accounts(frm) {
	frm.set_value("party", null);
	frm.set_value("old_account", null);
	frm.set_value("new_account", null);
	frm.clear_table("transactions");
	frm.refresh_field("transactions");
}
