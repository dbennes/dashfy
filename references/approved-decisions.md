# Approved Decisions

## DATAFY Filter Pattern

- Approved table filtering pattern: the Excel-like filter system from the DATAFY table at `http://127.0.0.1:8000/`.
- This DATAFY table is the visual/interaction reference for dashboard operational tables.
- Avoid external filter bars for detailed operational tables.
- The user explicitly prefers this pattern for dashboard tables:
  - Header row with column names and sort hint (`<>`).
  - Filter row directly below the header.
  - One small select/input per column, inside the header cell.
  - `All`/`Filtered` style values like the DATAFY material rows grid.
  - Compact column-width controls, dense row height, horizontal scroll.
  - Behavior and look should resemble Excel table filters.
- Apply this pattern to engineering/eClic and supply/DATAFY tables unless the user asks for a different behavior.
- The accepted table direction is richer than a simple grid: keep filters inside the table, but use an operational command bar with real counters/actions and row status indicators so the screen reads like a management system, not a basic report.

## Executive Control Tower Pattern

- Approved dashboard inspiration memory is documented in `references/dashboard-visual-patterns.md` and the `dashboard-visual-design` skill.
- Approved dashboard pattern: place a management-grade "control tower" panel before detailed tables in each major area.
- The accepted material panel is the reference: total KPI, conic coverage indicator, stacked composition bar, status rows with icons/counts/percentages, and an executive aside focused on risk/exposure.
- Reuse this pattern for Engenharia, Suprimentos and other cockpit areas when the user asks for modern management charts.
- Keep the detail tables below the executive panel; charts summarize the operating view but do not replace the Excel-like operational tables.
- Important refinement approved after review: each major area must keep the same management-grade consistency but use a distinct layout language. Do not clone the material control tower structure for every section.
- Engineering document completion percentage must be based on AFC divided by total documents. In the current eClic interpretation, AFC corresponds to revision C.
