// Copyright (c) 2026, Isoft and contributors
// For license information, please see license.txt

/*	The Naming Series column is a Data field in the schema because a Select's
	options are fixed per DocType, and every row here may point at a different
	Document Type. Frappe v13 keeps a private docfield copy per grid row
	(frappe.meta.docfield_copy[child][row.name]), so each row can carry its own
	option list: the column is flipped to Select once, and the options are set
	row by row from the row's Document Type.
*/

const CHILD = "Isoft Company Naming Series";
const METHOD = "isoft_customization.isoft_customization.doctype.isoft_naming_series_settings.isoft_naming_series_settings";

frappe.ui.form.on("Isoft Naming Series Settings", {
	setup(frm) {
		frm.__series_options = {};

		frm.set_query("reference_doctype", "series", function () {
			return { filters: { name: ["in", frm.__doctypes_with_naming_series || []] } };
		});

		frappe.call({
			method: METHOD + ".get_doctypes_with_naming_series",
			callback(r) {
				frm.__doctypes_with_naming_series = r.message || [];
			},
		});
	},

	refresh(frm) {
		const grid = frm.fields_dict.series.grid;
		grid.update_docfield_property("naming_series", "fieldtype", "Select");

		const doctypes = (frm.doc.series || []).map((d) => d.reference_doctype).filter(Boolean);
		frm.events.load_series_options(frm, doctypes).then(() => {
			(frm.doc.series || []).forEach((row) => frm.events.set_row_options(frm, row.name));
		});
	},

	// Fetch the option lists that are not cached yet, in one round trip.
	load_series_options(frm, doctypes) {
		const missing = [...new Set(doctypes)].filter((dt) => dt && !frm.__series_options[dt]);
		if (!missing.length) return Promise.resolve();

		return frappe
			.call({ method: METHOD + ".get_naming_series_options_map", args: { doctypes: missing } })
			.then((r) => {
				Object.assign(frm.__series_options, r.message || {});
				missing.forEach((dt) => {
					if (!frm.__series_options[dt]) frm.__series_options[dt] = [];
				});
			});
	},

	// Give one row's Naming Series dropdown the options of that row's Document Type.
	set_row_options(frm, cdn) {
		const row = frappe.get_doc(CHILD, cdn);
		if (!row) return;
		const options = (frm.__series_options[row.reference_doctype] || []).join("\n");

		const df = frappe.meta.get_docfield(CHILD, "naming_series", cdn);
		if (df) {
			df.fieldtype = "Select";
			df.options = options;
		}

		const grid_row = frm.fields_dict.series.grid.grid_rows_by_docname[cdn];
		if (grid_row) grid_row.refresh_field("naming_series");
	},
});

frappe.ui.form.on(CHILD, {
	form_render(frm, cdt, cdn) {
		frm.events.set_row_options(frm, cdn);
	},

	reference_doctype(frm, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		frappe.model.set_value(cdt, cdn, "naming_series", "");
		frm.events.load_series_options(frm, [row.reference_doctype]).then(() => {
			frm.events.set_row_options(frm, cdn);
		});
	},
});
