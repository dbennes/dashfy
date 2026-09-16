# Skyline views

The existing Shellbi dashboard has three Piping Skyline buttons above the chart:

- **Fabrication** (`aveon`): planned fabrication finishes and completed lines from the existing fabrication integration. Recorded and estimated completion dates retain their current rules and evidence.
- **Wooden Box** (`ros`, the initial selection): the existing ROS baseline and 60-day lookahead. ROS workbook export/import remain available in this view.
- **Installation** (`installation`): the same real line identifiers and per-line spool quantities as Wooden Box, with deterministic **Sample data** for dates and progress from `skyline_installation_source.installation_skyline_sample(ros_payload)`. No Structural or Electrical selection is provided for Skyline.

Installation takes its exact line-to-spool map from the supplied ROS payload, using the same scope extraction as Fabrication: forecast quantities are summed by line; lookahead quantities are used only when forecast is absent. The current ROS snapshot contains 166 lines and 607 spools. Quantities can differ between lines and are never replaced with fixed-size batches or synthetic identifiers. No additional source files or database queries are required, and the input is not changed.

Only dates and progress are simulated. The fixed daily distribution of the Piping Installation Rundown is scaled to the real total spool scope without changing the Rundown itself. A line completes when its entire spool quantity has been covered. The simulated execution sequence differs from the planned sequence, and both stay deterministic when input rows are reordered. Only whole lines completed by the fixed sample date, 15 September 2026, appear below the axis; work within an unfinished line does not count as a completed box.

Installation sample version 4 spreads these dates over a longer Skyline horizon: each date's distance from 15 September 2026 is multiplied by four. This gives the current scope 21 weekly columns, from 24 July through 11 December 2026, so boxes are distributed across narrower periods. The transformation preserves completion order, the reporting cutoff and the comparison against plan: the same 45 lines / 158 spools remain complete, with five lines on plan and 40 delayed. Wooden Box, Fabrication and Rundown dates are unchanged.

Planned finishes appear above; simulated completion dates appear below, grouped by the week ending Friday. Green means completion on or before plan; blue means after plan. Incomplete lines remain in the planned band. Completion dates use `completion_date_kind="sample"`, leave `actual_finish` empty and keep `actual_date_confirmed=false`. They never become operational installation records. Material lights, PO evidence and ROS workbook actions are omitted from Installation, and its boxes and period details identify the simulation.

Source metadata separates the real scope from the simulation: `scope_kind="real"`, `scope_source="ROS"`, `scope_workbook`, `scope_snapshot_date` and `scope_snapshot_label` describe the supplied scope; `is_sample=true`, `data_kind="sample"`, `source_label="Sample data"` and the fixed sample date describe installation dates and progress. ROS planned dates, completion flags and material readiness do not drive the simulation.

Switching views updates the title, scope, legend, date marker, sources and details. It preserves Show all / Collapse and does not change the Rundown selection. If the supplied ROS payload has no valid line scope, Installation is unavailable and does not substitute invented lines or quantities.

Tests: `test_skyline_installation`, `test_skyline_live_home`, `test_skyline_modes_ui`, and the existing `test_skyline_aveon` regressions.

## Box status colors

All three skyline views use green for completed on or before plan, blue for completed after plan, orange for work in progress or partial delivery, and gray for not started. Partial progress is always orange, without a red/yellow/green gradient. Planned-band boxes reflect the same line execution evidence, while their positions remain at planned dates. The completion band continues to show only completed lines at completion dates. A passed planned date alone never makes an unstarted box blue. Completed lines without a comparable date remain neutral and are labeled Timing unknown. Material-readiness lights retain their separate category rules. Legend quantities describe the visible classification and do not add unfinished lines to completed totals. ROS evidence remains the documented schedule proxy; Installation remains sample data.
