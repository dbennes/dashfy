# Rundown by discipline

In **Cockpit → Fabrication**, the **Discipline** selector sits in the Rundown
header, above its chart. English labels and a 26px control match the existing
fabrication controls. Piping is the initial selection. Switching updates the
chart, summary, units, legend, source date and provenance without reloading the
page. The Skyline and its ROS / AVEON selector remain independent.

## Sources and quantities

| Discipline | Source | Unit | Series |
| --- | --- | --- | --- |
| Piping | Existing reconciled ROS workbook snapshot, `Runddown!T1:X75` | Spools | Baseline and 60-day lookahead daily releases and remaining balances |
| Structural | Active structural fabrication packages and their linked schedule imports in DATAFY | WBS packages | Planned fabrication completions and remaining balance |

`rundown_discipline_source.rundown_disciplines_safe(piping_payload)` preserves
the original Piping arrays and KPIs. Structural counts distinct active package
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
