# Isoft Grid Tools

Adds an **Excel** button to every child-table grid in the Frappe desk.

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

## Install

```bash
bench get-app isoft_grid_tools /path/to/isoft_grid_tools
bench --site your.site install-app isoft_grid_tools
bench build --app isoft_grid_tools
```

#### License

MIT
