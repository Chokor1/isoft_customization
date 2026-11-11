// Search box on form child tables (any doctype, draft or submitted).
//
// Frappe v13 pages a table at 50 rows with no way to find one, so removing one item from a
// Pricing Rule's long "Apply Rule On" list meant paging through it. Typing here keeps only the
// matching rows, across all pages; the table's own row checkboxes, "select all" and Delete then
// work on those rows, and on a submitted document it is just a way to find and read rows.
//
// How: the grid reads its rows from Grid.get_data() for rendering, paging and select-all, so a
// filter there narrows everything at once. Form grids only (dialog tables keep their rows in
// df.data and their delete path rewrites it from get_data()). While a search is on, drag
// re-ordering is hidden (it renumbers from what is on screen), and adding a row clears the
// search so the new empty row is not filtered away.
frappe.provide("isoft.grid_search");

(function () {
	const ns = isoft.grid_search;
	const MIN_ROWS = 11; // the box shows on tables longer than this, or while a search is on
	const EXTRA_FIELDS = ["item_code", "item_name", "description", "item_group", "brand", "uom"];

	ns.patched = false;

	function all_rows(grid) {
		return (grid.frm && grid.frm.doc && grid.frm.doc[grid.df.fieldname]) || [];
	}

	function query(grid) {
		// a search belongs to one document: reopening another one starts clean
		if (!grid.__isoft_q || !grid.frm || grid.__isoft_q_doc !== grid.frm.docname) return "";
		return grid.__isoft_q;
	}

	function haystack(grid, row) {
		const fields = new Set(EXTRA_FIELDS);
		(grid.visible_columns || []).forEach((col) => col && col[0] && fields.add(col[0].fieldname));
		const parts = [String(row.idx || "")];
		fields.forEach((f) => {
			const v = row[f];
			if (v !== undefined && v !== null && v !== "") parts.push(String(v));
		});
		return parts.join(" \u0001 ").toLowerCase();
	}

	function matches(grid, row, q) {
		const text = haystack(grid, row);
		return q.toLowerCase().split(/\s+/).filter(Boolean).every((word) => text.includes(word));
	}

	ns.patch = function (grid) {
		if (ns.patched || !grid) return;
		const proto = Object.getPrototypeOf(grid);
		if (!proto || !proto.get_data || !proto.refresh) return;
		ns.patched = true;

		const get_data = proto.get_data;
		proto.get_data = function () {
			const data = get_data.apply(this, arguments);
			const q = this.frm ? query(this) : "";
			return q ? (data || []).filter((row) => matches(this, row, q)) : data;
		};

		const refresh = proto.refresh;
		proto.refresh = function () {
			const out = refresh.apply(this, arguments);
			try { ns.render_box(this); } catch (e) { /* never break a form over the search box */ }
			return out;
		};

		const add_new_row = proto.add_new_row;
		proto.add_new_row = function () {
			if (this.frm && query(this)) ns.set_query(this, "", true);
			return add_new_row.apply(this, arguments);
		};
	};

	ns.set_query = function (grid, q, silent) {
		grid.__isoft_q = (q || "").trim();
		grid.__isoft_q_doc = grid.frm && grid.frm.docname;
		if (grid.grid_pagination) grid.grid_pagination.page_index = 1;
		const $grid = $(grid.wrapper).find(".form-grid").addBack(".form-grid").first();
		$grid.parent().toggleClass("isoft-grid-filtered", !!grid.__isoft_q);
		if (silent) {
			$grid.prevAll(".isoft-grid-search").find("input").val(grid.__isoft_q);
		}
		grid.refresh();
	};

	ns.render_box = function (grid) {
		if (!grid.frm || !grid.wrapper) return;
		const total = all_rows(grid).length;
		const q = query(grid);
		// grid.wrapper is a jQuery set of several elements: anchor to the one table element
		const $grid = $(grid.wrapper).find(".form-grid").addBack(".form-grid").first();
		if (!$grid.length) return;
		const $w = $grid.parent();
		let $box = $grid.prevAll(".isoft-grid-search").first();
		if (total < MIN_ROWS && !q) {
			$box.remove();
			$w.removeClass("isoft-grid-filtered");
			return;
		}
		$box.slice(1).remove();
		if (!$box.length) {
			$box = $(`<div class="isoft-grid-search">
				<span class="isoft-grid-search-field">
					${frappe.utils.icon("search", "sm")}
					<input type="search" class="form-control input-xs" autocomplete="off"
						placeholder="${__("Search rows…")}" aria-label="${__("Search rows")}">
				</span>
				<span class="isoft-grid-search-count text-muted small"></span>
			</div>`).insertBefore($grid);
			let timer = null;
			$box.find("input")
				.on("input", function () {
					const v = this.value;
					clearTimeout(timer);
					timer = setTimeout(() => ns.set_query(grid, v), 200);
				})
				.on("keydown", function (e) {
					if (e.key === "Escape" && this.value) {
						e.preventDefault();
						e.stopPropagation(); // not the form's Escape
						this.value = "";
						ns.set_query(grid, "");
					}
					if (e.key === "Enter") e.preventDefault(); // never submit/save the form
				});
		}
		const $input = $box.find("input");
		if (!$input.is(":focus") && $input.val() !== q) $input.val(q);
		$w.toggleClass("isoft-grid-filtered", !!q);
		const shown = q ? (grid.data || []).length : total;
		$box.find(".isoft-grid-search-count").text(q ? __("{0} of {1} rows", [shown, total]) : __("{0} rows", [total]));
	};

	// The Grid class is not exposed in v13: patch it through the first form that shows a table.
	$(document).on("form-refresh", function (e, frm) {
		if (ns.patched || !frm || !frm.fields_dict) return;
		const table = Object.values(frm.fields_dict).find((f) => f && f.grid);
		if (table) {
			ns.patch(table.grid);
			Object.values(frm.fields_dict).forEach((f) => f && f.grid && f.grid.refresh());
		}
	});
})();
