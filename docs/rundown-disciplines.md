# Rundown by discipline

In **Cockpit → Fabrication**, the Rundown toolbar contains **Fabrication** and
**Installation** buttons, followed by a **Discipline** selector with **Piping**,
**Electrical** and **Structural**. All controls are 26px high. Fabrication /
Piping is the initial selection. Changing mode preserves the selected
discipline. Both controls update the chart, summary, units, legend, source date
and provenance without reloading. The Skyline and its schedule selector remain
independent.

## Sources and quantities

| Discipline | Source | Unit | Series |
| --- | --- | --- | --- |
| Piping | Last accepted ROS workbook; original reconciled snapshot until the first import | Spools | Baseline and 60-day lookahead daily releases and remaining balances |
| Electrical | No electrical fabrication schedule is provided by the current DATAFY importer | Not established | Explicit unavailable state; no inferred or simulated fabrication curve |
| Structural | Active structural fabrication packages and their linked schedule imports in DATAFY | WBS packages | Planned fabrication completions and remaining balance |

These are **Fabrication** sources. **Installation** uses separate deterministic
sample schedules for all three disciplines. The toolbar displays **Sample
data**, and the source footer, explanatory note and accessible chart summary
identify the simulation. Sample quantities and dates do not enter DATAFY,
fabrication progress, ROS schedules, Skyline or stored imports. Repeated
selections reproduce the same curves. Each sample reconciles daily completions
with a nonnegative start-of-day remaining balance and its own finish dates.
The sample curves distribute completions across the schedule with a gradual
startup, a busier middle period and a taper near completion. Installation axes
fit the selected sample scope and daily quantities; they do not inherit the
700-spool / 100-release display limits of the real Piping ROS chart.

`rundown_modes_safe(piping_payload)` provides both modes with the same chart
contract. Real-source failures remain isolated from the sample installation
view. At verification on 15 September 2026, DATAFY contained no identifiable
electrical fabrication schedule, so that real-data selection correctly showed
an unavailable state.

`rundown_discipline_source.rundown_disciplines_safe(piping_payload)` preserves
the supplied Piping arrays and KPIs. The Skyline toolbar provides the
[ROS workbook update workflow](ros-workbook-updates.md) for both Piping views.
Structural counts distinct active package
identities, including packages without a linked drawing. It uses the imported
planned fabrication finish, including the final fabrication stage. A schedule
is labeled AVEON only when its linked source workbooks establish that origin.

At verification on 14 September 2026, Piping retained its 607-spool scope.
Structural contained 29 packages from `AVEON Schedule 1.xlsx`, all dated. Its
last planned completion is 24 December 2026. Balances use the existing
start-of-day convention, so the zero balance occurs on 25 December.

Structural tonnage is incomplete and includes overlapping drawing references;
package counts avoid treating that weight as a complete, additive scope. The
scope tooltip explains the unit. Packages without attributable plan dates
remain in the remaining balance, with coverage stated beside the source. No
zero date is reported while unscheduled packages remain.

No complete structural lookahead or dated actual-progress series is currently
integrated. Its lookahead arrays and date variance are null, its comparison
KPIs display a dash, and an on-screen note explains the available plan. Current
progress percentages and partially matched external weekly reports are not
converted into invented completion dates.

Source failure affects Structural independently; Piping stays available. The
home embeds discipline data with Django `json_script`; operational source text
is displayed with `textContent`. Source reads do not modify operational data.

## Verification

```powershell
.\.venv\Scripts\python.exe manage.py test apps.core.tests.test_fabrication_rundown apps.core.tests.test_rundown_disciplines apps.core.tests.test_rundown_live_home apps.core.tests.test_skyline_live_home apps.core.tests.test_skyline_aveon apps.core.tests.test_home_sections.FabricationRundownStyleTests
```

Checks cover original Piping preservation, structural date aggregation,
deduplication, missing dates and weights, unavailable forecasts, source
attribution, safe JSON, independent failure and integration into the real home.
Browser verification covers both selections, returning to Piping, and the
selector and chart at desktop and phone widths.
