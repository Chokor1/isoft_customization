// Copyright (c) 2026, Isoft and contributors
// For license information, please see license.txt

frappe.query_reports["Credit Note Register"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "return_against",
			label: __("Return Against"),
			fieldtype: "Link",
			options: "Sales Invoice",
			get_query: () => ({ filters: { is_return: 0, docstatus: 1 } }),
		},
		{
			fieldname: "include_cancelled",
			label: __("Include Cancelled"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "status" && data.docstatus === 2) {
			value = `<span style="color: var(--text-on-red, red)">${value}</span>`;
		}
		// An invoice credited past its own total is a mistake worth seeing.
		if (column.fieldname === "credited_percent" && flt(data.credited_percent) > 100.0001) {
			value = `<span style="color: var(--text-on-red, red); font-weight: 600">${value}</span>`;
		}
		return value;
	},
};
