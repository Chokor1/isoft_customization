// Copyright (c) 2026, Isoft and contributors
// POS Customer Contacts: who bought where, and how to reach them.

frappe.query_reports["POS Customer Contacts"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company"), reqd: 1 },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -12), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "pos_profiles", label: __("POS Profiles"), fieldtype: "MultiSelectList",
			get_data: (txt) => frappe.db.get_link_options("POS Profile", txt, {
				company: frappe.query_report.get_filter_value("company") }) },
		{ fieldname: "show", label: __("Show per POS Profile"), fieldtype: "Select",
			options: ["Amount", "Qty", "Yes/No"], default: "Amount" },
		{ fieldname: "contact", label: __("Contact"), fieldtype: "Select",
			options: ["Phone or Email", "Phone", "Email", "Any"], default: "Phone or Email" },
		{ fieldname: "customer_group", label: __("Customer Group"), fieldtype: "Link", options: "Customer Group" },
		{ fieldname: "include_desk", label: __("Include desk / B2B invoices"), fieldtype: "Check", default: 1,
			depends_on: "eval:!(doc.pos_profiles && doc.pos_profiles.length)" },
		{ fieldname: "net_of_returns", label: __("Net of returns"), fieldtype: "Check", default: 1 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname && column.fieldname.startsWith("pos_") && data && data[column.fieldname] === __("Yes")) {
			return `<span style="color: var(--green-600, #15803d); font-weight: 600">${value}</span>`;
		}
		if (column.fieldname && column.fieldname.startsWith("pos_") && data && data[column.fieldname] === __("No")) {
			return `<span style="color: var(--text-muted, #94a3b8)">${value}</span>`;
		}
		if (column.fieldname === "phone" && data && data.phone) {
			return `<a href="tel:${encodeURIComponent(data.phone)}">${value}</a>`;
		}
		if (column.fieldname === "email" && data && data.email) {
			return `<a href="mailto:${encodeURIComponent(data.email)}">${value}</a>`;
		}
		return value;
	},
};
