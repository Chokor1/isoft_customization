// Copyright (c) 2026, Isoft and Contributors
// MIT License. See license.txt
//
// Adds an "Excel" button to every child table grid.
//
// The core Download button emits a bulk-edit CSV template - six rows of
// instructions stacked above the data, one column per field whether you want it
// or not. This asks which columns you want (mandatory + currently visible ones
// pre-ticked) and hands back a formatted sheet instead.
//
// Grid is a module-local class in frappe/public/js/frappe/form/grid.js, so it
// cannot be reached by name. We patch its prototype off the first live instance,
// which ControlTable hands us.

frappe.provide("isoft_customization");

// fields that make no sense in a spreadsheet even though they hold a value
const SKIPPED_FIELDTYPES = ["Password", "Signature", "Geolocation", "JSON"];
// how many columns to tick when a table has neither mandatory nor list-view fields
const FALLBACK_COLUMN_COUNT = 8;

Object.assign(isoft_customization, {
	patch_grid_prototype(grid) {
		const proto = Object.getPrototypeOf(grid);
		if (!proto || proto.__isoft_excel_patched) return;
		proto.__isoft_excel_patched = true;

		// setup_toolbar runs on every grid refresh, so the button survives
		// re-renders and follows the row count
		const original = proto.setup_toolbar;
		proto.setup_toolbar = function () {
			const out = original.apply(this, arguments);
			try {
				isoft_customization.render_button(this);
			} catch (e) {
				console.error("[isoft_customization] could not add Excel button", e);
			}
			return out;
		};
	},

	// grid.wrapper is a collection of the template's top-level nodes and
	// .grid-footer is one of them, not a descendant - so .find() alone misses it
	// (core's own this.wrapper.find('.grid-footer') is a no-op for this reason)
	get_footer(grid) {
		if (!grid.wrapper) return $();
		return grid.wrapper.filter(".grid-footer").add(grid.wrapper.find(".grid-footer")).first();
	},

	render_button(grid) {
		if (!grid.wrapper || !grid.df || !grid.df.options) return;

		const $footer = isoft_customization.get_footer(grid);
		const $area = $footer.find(".text-right").first();
		if (!$area.length) return;

		let $btn = $area.find(".grid-excel-download");
		if (!$btn.length) {
			$btn = $(
				`<a href="#" class="btn btn-xs btn-secondary grid-excel-download"
					style="margin-right: 4px;"
					title="${__("Download as a formatted Excel file")}">${__("Excel")}</a>`
			);
			$area.prepend($btn);
			$btn.on("click", () => {
				isoft_customization.show_dialog(grid);
				return false;
			});
		}

		isoft_customization.take_over_bulk_edit(grid, $footer);

		const has_rows = isoft_customization.get_rows(grid).length > 0;
		$btn.toggleClass("hidden", !has_rows);

		// core hides the whole footer on read-only grids that fit on one page,
		// which is exactly where exporting is most useful - put it back
		if (has_rows) $footer.toggle(true);
	},

	// ---------------------------------------------------------------------
	// Bulk edit: the core Download / Upload pair, in Excel instead of CSV
	// ---------------------------------------------------------------------

	// Core binds these in Grid.make(), we run on every setup_toolbar - which is
	// after make - so unbind first and rebind ours each time. Cheap, and it does
	// not depend on which of the two ran first.
	take_over_bulk_edit(grid, $footer) {
		if (!grid.frm || !grid.df) return;

		const docfield = grid.frm.get_docfield && grid.frm.get_docfield(grid.df.fieldname);
		if (!docfield || !docfield.allow_bulk_edit) return;

		const $download = $footer.find(".grid-download");
		const $upload = $footer.find(".grid-upload");
		if (!$download.length || !$upload.length) return;

		$download
			.off("click")
			.attr("title", __("Download an Excel file of these rows to edit"))
			.on("click", () => {
				isoft_customization.download_template(grid);
				return false;
			});

		$upload
			.off("click")
			.attr("title", __("Replace these rows with an edited Excel file"))
			.on("click", () => {
				isoft_customization.upload_template(grid);
				return false;
			});
	},

	download_template(grid) {
		const rows = isoft_customization.get_rows(grid);
		const title = __(grid.df.label || frappe.model.unscrub(grid.df.fieldname));

		const fields = [
			{
				fieldtype: "Select",
				fieldname: "scope",
				label: __("Columns"),
				default: "visible",
				options: [
					{ value: "visible", label: __("The columns you normally fill") },
					{ value: "all", label: __("Every editable column") },
				],
			},
		];

		if (rows.length) {
			fields.push({
				fieldtype: "Check",
				fieldname: "include_rows",
				label: __("Start from the rows already in the table"),
				description: isoft_customization.row_count(rows.length),
				default: 1,
			});
		}

		fields.push({
			fieldtype: "HTML",
			fieldname: "note",
			options: `<p class="text-muted small">${__(
				"Edit the sheet, then use Upload to put it back. The hidden row above the headers is what identifies the columns - leave it alone."
			)}</p>`,
		});

		const dialog = new frappe.ui.Dialog({
			title: __("Download {0} for editing", [title]),
			fields: fields,
			primary_action_label: __("Download"),
			primary_action(values) {
				open_url_post(frappe.request.url, {
					cmd: "isoft_customization.api.export_grid_template",
					doctype: grid.df.options,
					parent_doctype: (grid.frm && grid.frm.doctype) || "",
					parent_name: (grid.frm && grid.frm.docname) || "",
					title: title,
					scope: values.scope || "visible",
					data: JSON.stringify(values.include_rows ? rows : []),
				});
				dialog.hide();
			},
		});

		dialog.show();
	},

	upload_template(grid) {
		// core sets this before its own uploader; realtime progress on a file we
		// never store just leaves a stuck progress bar
		frappe.flags.no_socketio = true;

		const uploader = new frappe.ui.FileUploader({
			as_dataurl: true,
			allow_multiple: false,
			disable_file_browser: true,
			upload_notes: __("Excel (.xlsx, .xls) or CSV"),
			restrictions: { allowed_file_types: [".xlsx", ".xlsm", ".xls", ".csv"] },
			on_success(file) {
				if (uploader && uploader.dialog) uploader.dialog.hide();

				frappe
					.call({
						method: "isoft_customization.api.import_grid_rows",
						args: {
							doctype: grid.df.options,
							filedata: file.dataurl,
							filename: file.name,
							parent_doctype: (grid.frm && grid.frm.doctype) || "",
							parent_name: (grid.frm && grid.frm.docname) || "",
						},
						freeze: true,
						freeze_message: __("Reading {0}...", [file.name]),
					})
					.then((r) => isoft_customization.confirm_import(grid, r.message, file.name));
			},
		});
	},

	// "1 rows" reads like a bug report
	row_count(n) {
		return n === 1 ? __("1 row") : __("{0} rows", [n]);
	},

	// frappe.bold is python-side only; the desk has no equivalent
	bold(value) {
		return "<b>" + frappe.utils.escape_html(String(value)) + "</b>";
	},

	confirm_import(grid, result, filename) {
		if (!result) return;

		const incoming = result.rows || [];
		const existing = isoft_customization.get_rows(grid).length;
		const title = __(grid.df.label || frappe.model.unscrub(grid.df.fieldname));

		if (!incoming.length) {
			frappe.msgprint({
				title: __("Nothing to import"),
				message: __("No data rows were found in {0}.", [isoft_customization.bold(filename)]),
				indicator: "orange",
			});
			return;
		}

		let message = `<p>${__("{0} read from {1}.", [
			isoft_customization.bold(isoft_customization.row_count(incoming.length)),
			isoft_customization.bold(filename),
		])}</p>`;

		if (existing) {
			message += `<p class="text-danger">${__("The {0} currently in {1} will be replaced.", [
				isoft_customization.bold(isoft_customization.row_count(existing)),
				title,
			])}</p>`;
		}

		if ((result.skipped_columns || []).length) {
			message += `<p class="text-muted small">${__("Columns ignored: {0}", [
				result.skipped_columns.join(", "),
			])}</p>`;
		}

		if ((result.warnings || []).length) {
			message += `<p class="text-muted small">${result.warnings.join("<br>")}</p>`;
		}

		message += `<p class="text-muted small">${__(
			"Nothing is saved yet - check the table and save the document as usual."
		)}</p>`;

		frappe.confirm(message, () => isoft_customization.apply_rows(grid, incoming));
	},

	apply_rows(grid, incoming) {
		const fieldname = grid.df.fieldname;
		const frm = grid.frm;

		frm.clear_table(fieldname);
		incoming.forEach((row) => {
			const child = frm.add_child(fieldname);
			Object.keys(row).forEach((key) => {
				child[key] = row[key];
			});
		});

		frm.refresh_field(fieldname);
		frm.dirty();

		frappe.show_alert({
			message: __("{0} loaded into {1}", [
				isoft_customization.row_count(incoming.length),
				__(grid.df.label || frappe.model.unscrub(fieldname)),
			]),
			indicator: "green",
		});
	},

	get_rows(grid) {
		if (grid.frm && grid.frm.doc && grid.df) {
			return grid.frm.doc[grid.df.fieldname] || [];
		}
		if (typeof grid.get_data === "function") {
			try {
				return grid.get_data() || [];
			} catch (e) {
				// get_data leans on frm for some grids; fall through
			}
		}
		return grid.data || [];
	},

	get_exportable_fields(doctype) {
		const meta = frappe.get_meta(doctype);
		if (!meta) return [];

		return (meta.fields || []).filter(
			(df) =>
				frappe.model.is_value_type(df.fieldtype) &&
				!SKIPPED_FIELDTYPES.includes(df.fieldtype)
		);
	},

	get_default_fieldnames(fields) {
		// "mandatory ticked by default" - plus whatever the grid already shows,
		// so the sheet matches the table the user is looking at
		let defaults = fields
			.filter((df) => df.reqd || (df.in_list_view && !df.hidden))
			.map((df) => df.fieldname);

		if (!defaults.length) {
			defaults = fields
				.filter((df) => !df.hidden)
				.slice(0, FALLBACK_COLUMN_COUNT)
				.map((df) => df.fieldname);
		}

		return defaults;
	},

	show_dialog(grid) {
		const doctype = grid.df.options;
		const fields = isoft_customization.get_exportable_fields(doctype);

		if (!fields.length) {
			frappe.msgprint({
				title: __("Nothing to Export"),
				message: __("{0} has no exportable fields.", [__(doctype)]),
				indicator: "orange",
			});
			return;
		}

		const rows = isoft_customization.get_rows(grid);
		const title = __(grid.df.label || frappe.model.unscrub(grid.df.fieldname));
		const defaults = isoft_customization.get_default_fieldnames(fields);

		const options = [
			{
				label: __("Row No."),
				value: "idx",
				checked: true,
				description: __("Position of the row in the table"),
			},
		].concat(
			fields.map((df) => ({
				label: df.label || frappe.model.unscrub(df.fieldname),
				value: df.fieldname,
				checked: defaults.includes(df.fieldname),
				danger: false,
				description: df.reqd
					? __("Mandatory")
					: __("{0} · {1}", [df.fieldname, __(df.fieldtype)]),
				_reqd: !!df.reqd,
			}))
		);

		const selected_rows = isoft_customization.get_selected_docnames(grid);

		const dialog_fields = [
			{
				fieldtype: "Data",
				fieldname: "search",
				label: __("Find a column"),
			},
			{
				fieldtype: "MultiCheck",
				fieldname: "columns",
				options: options,
				columns: 2,
				select_all: true,
			},
			{ fieldtype: "Section Break" },
			{
				fieldtype: "Check",
				fieldname: "add_totals",
				label: __("Add a totals row"),
				default: 1,
				description: __("Sums Currency, Float and Int columns"),
			},
		];

		if (selected_rows.length) {
			dialog_fields.push(
				{ fieldtype: "Column Break" },
				{
					fieldtype: "Check",
					fieldname: "only_selected",
					label: __("Only the {0} selected rows", [selected_rows.length]),
					default: 1,
				}
			);
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Download {0} as Excel", [title]),
			size: "large",
			fields: dialog_fields,
			primary_action_label: __("Download"),
			primary_action(values) {
				const fieldnames = values.columns || [];
				if (!fieldnames.length) {
					frappe.msgprint(__("Select at least one column."));
					return;
				}

				let export_rows = rows;
				if (values.only_selected && selected_rows.length) {
					export_rows = rows.filter((row) => selected_rows.includes(row.name));
				}

				isoft_customization.download(grid, {
					doctype: doctype,
					title: title,
					fieldnames: fieldnames,
					rows: export_rows,
					add_totals: values.add_totals ? 1 : 0,
				});
				dialog.hide();
			},
		});

		dialog.show();
		isoft_customization.setup_dialog(dialog);
	},

	get_selected_docnames(grid) {
		if (typeof grid.get_selected !== "function") return [];
		try {
			return grid.get_selected() || [];
		} catch (e) {
			return [];
		}
	},

	setup_dialog(dialog) {
		const control = dialog.fields_dict.columns;
		if (!control || !control.options) return;

		// MultiCheck runs labels through __() in its own template, so the
		// mandatory marker has to be painted on afterwards rather than baked
		// into the label - otherwise it breaks the translation lookup
		control.options.forEach((option) => {
			if (option._reqd && option.$checkbox) {
				option.$checkbox
					.find(".label-area")
					.append(' <span class="text-danger">*</span>');
			}
		});

		// doctypes like Sales Invoice Item have 80+ fields; let the list scroll
		// on its own so the options below it stay reachable
		if (control.$checkbox_area) {
			control.$checkbox_area.css({
				"max-height": "45vh",
				"overflow-y": "auto",
				"padding-right": "5px",
			});
		}

		// the control's own `change` hook only fires on blur, which is too late
		// to feel like a search box
		const $search = dialog.fields_dict.search.$input;
		if ($search) {
			$search.on(
				"input",
				frappe.utils.debounce(
					() => isoft_customization.filter_options(dialog, $search.val()),
					150
				)
			);
		}
	},

	filter_options(dialog, term) {
		const control = dialog.fields_dict.columns;
		if (!control || !control.options) return;

		const needle = (term || "").toLowerCase().trim();
		control.options.forEach((option) => {
			if (!option.$checkbox) return;
			const haystack = (option.label + " " + option.value).toLowerCase();
			option.$checkbox.toggle(!needle || haystack.includes(needle));
		});
	},

	download(grid, opts) {
		// only ship the columns that were asked for
		const data = opts.rows.map((row) => {
			const out = {};
			opts.fieldnames.forEach((fieldname) => {
				out[fieldname] = row[fieldname];
			});
			return out;
		});

		open_url_post(frappe.request.url, {
			cmd: "isoft_customization.api.export_grid",
			doctype: opts.doctype,
			parent_doctype: (grid.frm && grid.frm.doctype) || "",
			parent_name: (grid.frm && grid.frm.docname) || "",
			title: opts.title,
			fieldnames: JSON.stringify(opts.fieldnames),
			add_totals: opts.add_totals,
			data: JSON.stringify(data),
		});
	},
});

(function install() {
	function patch() {
		const ControlTable = frappe.ui && frappe.ui.form && frappe.ui.form.ControlTable;
		if (!ControlTable) return false;

		const proto = ControlTable.prototype;
		if (proto.__isoft_excel_patched) return true;
		proto.__isoft_excel_patched = true;

		const original = proto.make;
		proto.make = function () {
			const out = original.apply(this, arguments);
			if (this.grid) isoft_customization.patch_grid_prototype(this.grid);
			return out;
		};

		return true;
	}

	if (!patch()) {
		$(document).on("app_ready", patch);
	}
})();
