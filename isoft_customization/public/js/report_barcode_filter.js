// Adds the "Include Barcode" filter to five ERPNext stock reports, from this app.
//
// Frappe v13 has no server-side seam for this. frappe.desk.query_report.get_script()
// reads a report's .js straight off disk and only falls back to the Report DocType's
// `javascript` field when no file exists, so an app cannot contribute a filter to
// another app's Script Report the usual way.
//
// What it can do is watch for the moment ERPNext's report script assigns its object.
// Each report .js does `frappe.query_reports["Stock Balance"] = {...}` at load time,
// so a property definition placed here -- this file loads at desk boot, well before
// any report script -- intercepts that assignment and appends the filter.
//
// The column itself is added server-side; see isoft_customization/stock_barcode.py.

(function () {
	const REPORTS = [
		'Stock Balance',
		'Stock Projected Qty',
		'Warehouse wise Item Balance Age and Value',
		'Stock Analytics',
		'Stock Ledger',
	];

	const FILTER = {
		fieldname: 'include_barcode',
		label: __('Include Barcode'),
		fieldtype: 'Check',
	};

	function add_filter(config) {
		if (!config || !Array.isArray(config.filters)) return config;
		if (config.filters.some((f) => f && f.fieldname === 'include_barcode')) return config;
		config.filters.push(Object.assign({}, FILTER));
		return config;
	}

	// Stock Analytics plots the period columns of whichever row you tick, and finds
	// them by a fixed offset -- data.slice(7) -- which the extra Barcode column would
	// shift by one. Rather than have ERPNext know about the column, drop that cell
	// before its handler sees the row.
	const ANALYTICS_BARCODE_CELL = 7; // 5 report columns + checkbox + serial-no cell

	function fix_analytics_row_offset(config) {
		if (!config || typeof config.get_datatable_options !== 'function') return config;
		const original = config.get_datatable_options;
		config.get_datatable_options = function (options) {
			const opts = original.call(this, options);
			const on_check = opts && opts.events && opts.events.onCheckRow;
			if (!on_check || on_check.__barcode_aware) return opts;

			const wrapped = function (data) {
				if (!frappe.query_report.get_filter_value('include_barcode')) {
					return on_check.call(this, data);
				}
				const without_barcode = data
					.slice(0, ANALYTICS_BARCODE_CELL)
					.concat(data.slice(ANALYTICS_BARCODE_CELL + 1));
				return on_check.call(this, without_barcode);
			};
			wrapped.__barcode_aware = true;
			opts.events.onCheckRow = wrapped;
			return opts;
		};
		return config;
	}

	function apply(name, config) {
		config = add_filter(config);
		if (name === 'Stock Analytics') config = fix_analytics_row_offset(config);
		return config;
	}

	frappe.query_reports = frappe.query_reports || {};

	REPORTS.forEach(function (name) {
		// Already loaded (this file re-running, or the report opened first): patch in place.
		if (Object.prototype.hasOwnProperty.call(frappe.query_reports, name)) {
			apply(name, frappe.query_reports[name]);
			return;
		}

		let value;
		try {
			Object.defineProperty(frappe.query_reports, name, {
				configurable: true,
				enumerable: true,
				get: function () {
					return value;
				},
				set: function (config) {
					value = apply(name, config);
				},
			});
		} catch (e) {
			// Never let a failed intercept break the desk; the report still works,
			// just without the filter.
			// eslint-disable-next-line no-console
			console.warn('isoft_customization: could not attach barcode filter to', name, e);
		}
	});
})();
