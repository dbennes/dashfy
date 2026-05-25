# Component Patterns

## Operational Tables

- Use the DATAFY table pattern from `http://127.0.0.1:8000/` for operational/detail tables.
- The reference is the Excel-like filter system in the DATAFY material rows table: a compact grid where each column has its own filter control inside the table header.
- Filters must live inside the table header as a second `thead` row, using:
  - `tr.dx-column-header-row` for column labels.
  - `tr.dx-column-filter-row` directly below labels.
  - `.dx-column-filter-control` for each input/select.
  - `.dx-column-filter` for controls that submit the table filter.
- Do not place a detached filter toolbar above operational tables when the screen is meant to match DATAFY.
- Do not replace the Excel-like DATAFY filter with cards, pills, toolbar filters, or section-level filters.
- Keep filters column-scoped: drawing/search in the drawing column, discipline in discipline, revision in revision, line in line, table in table, etc.
- Use compact labels and controls like the DATAFY table: `All`, `Filtered`, small selects/inputs, short column names, dense row height, sticky header, visible `<>` sort hints, horizontal scroll for wide grids.
- Filter controls must visually feel embedded in the table, like Excel AutoFilter, not like a form above the table.
- Preserve the left/right structure approved for the dashboard:
  - Left supply card: compact drawing readiness table (`Cobertura Fab x Erection`).
  - Right supply card: DATAFY material rows grid with the full column filter pattern.
- Tables should not feel like plain HTML tables. Keep the Excel-like header filters, but wrap important operational tables with a compact command surface: active dataset label, real counters, reset/action chips, visible row count, denser fixed-height scroll, and row-level status signals.

## Executive Control Towers

- For major dashboard sections, lead with an executive control tower and keep the operational tables directly below.
- Use `references/dashboard-visual-patterns.md` as the dashboard visual pattern memory distilled from the user's approved reference images.
- Use the approved material control tower pattern as the baseline:
  - compact section header with total KPI;
  - conic gauge for the main management percentage;
  - stacked composition bar for status mix;
  - dense status rows with icon, label, detail, count and percentage;
  - right-side risk/exposure summary cards.
- Apply this pattern with section-specific language and colors. The visual should feel like management software, not a generic chart pasted above a table.
- Do not repeat the exact same chart composition across sections. Keep a consistent executive quality bar, but vary the layout by domain:
  - Material can use coverage gauge + composition + exposure aside.
  - Engineering should use separated document board cards: KPI strip, status distribution, revision distribution, and discipline load ranking. Percentages must be visible inside each chart card, not implied.
  - For Engineering documents, the principal completion percentage is AFC / total documents. In this dataset, AFC is represented by revision C.
