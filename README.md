# ISOFT Customization

Cross-cutting desk customizations for Frappe / ERPNext that don't belong to any
one business app.

## Features

### Excel export for child tables

Adds an **Excel** button to every child-table grid footer.

Clicking it opens a column picker — mandatory fields (and the columns visible in
the grid) are ticked by default, any other field can be added — and downloads a
properly formatted `.xlsx`:

- title + source line, styled header row, freeze panes and autofilter
- real Excel types: dates as dates, numbers as numbers, checks as Yes/No,
  percent columns as percentages, HTML fields flattened to text
- auto-sized columns, banded rows
- optional totals row (live `SUM` formulas) for numeric columns

Unlike the built-in **Download** button (a bulk-edit CSV template with six rows
of instructions above the data), this produces a sheet meant to be read.

Rows are read from the open form, so unsaved edits are included in the export.

Files: [`public/js/grid_excel.js`](isoft_customization/public/js/grid_excel.js),
[`excel.py`](isoft_customization/excel.py),
[`api.py`](isoft_customization/api.py).

## Install

```bash
bench get-app isoft_customization /path/to/isoft_customization
bench --site your.site install-app isoft_customization
bench build --app isoft_customization
bench restart
```

#### License

MIT
