# Rundown workbook updates

Use **Export** in the rundown toolbar to download `DASHFY_Rundown.xlsx`.
It contains six data sheets: Piping, Electrical and Structural, each with
Fabrication and Installation. Instructions and signed workbook metadata are
included. Each row is a daily quantity feeding the chart, not an individual ISO.

1. Set **Include on import** to YES for each sheet to update. NO leaves that view unchanged.
2. Enter Scope and Data date. Keep the sheet names, units and column headers.
3. Edit Date, Baseline daily, Lookahead daily and Actual daily from row 10.
   Actual means completed **that day**, not cumulative. Blank means unreported;
   zero is a reported zero. Rows can be added, deleted or reordered.
4. Balances and cumulative progress percentages are calculated from the quantities.
   Grey Excel formula columns are for reference and are recalculated by the importer.
   Formulas in editable fields use the calculated results saved by Excel. Recalculate
   and save before uploading; the server does not execute formulas. Missing cached
   results and Excel errors are rejected. Auxiliary columns after H are ignored.
5. An administrator opens **Import** in the rundown toolbar. The modal lets them
   upload, review changed sheets/fields and select **Apply changes** without
   leaving the dashboard. The chart refreshes while keeping the selected mode and
   discipline. History is available in the same modal.

Dates must be unique and valid. Quantities must be non-negative whole units and
each series total must not exceed Scope. Actual reports cannot be later than the
Data date; Data date cannot be in the future. An incomplete plan leaves an
unscheduled balance. Blank forecast or actual series remain unavailable.
Baseline/forecast balances are start-of-day; actual balances are end-of-day.

Installation demo curves are exported as **empty, disabled templates**. They are
replaced only when the user enables a sheet and supplies real quantities/dates.
Electrical fabrication is also an empty template until a schedule is supplied.

Accepted updates are append-only `core.RundownImport` records in the default
database, with author, filename, file hash, revision and changed-sheet summaries.
Each import retains previous overrides for unchanged sheets. Only the latest
export/source state can be imported. Previews expire after 30 minutes and are
bound to the administrator who uploaded the workbook. Concurrent/stale updates
are rejected rather than overwriting newer work.

These updates feed the rundown card. The existing ROS/Skyline workflow, DATAFY
package records, stage percentages and 3D progress colours keep their existing
sources. Imported rundown curves take precedence for their specific mode and
discipline; the chart identifies the imported workbook.

Deployment requires:

```powershell
python manage.py migrate --database default
python manage.py collectstatic --noinput
```

Migration: `core.0008_rundownimport`. Restart the application after deployment.
Regression tests: `test_rundown_workbook`, `test_rundown_modes_ui`,
`test_rundown_live_home`, `test_rundown_modes`, `test_rundown_disciplines`.

The upload limit is 10 MiB compressed, 256 MiB raw expanded XML and 200 internal
ZIP entries. Worksheets are processed one row at a time, discarding empty formatted
cells and auxiliary columns after H. Dimensions are rebuilt from retained cells,
so formatting through Excel's final row does not count as imported daily rows.
The retained workbook data still has a 50 MiB limit. No change is made to the
user's original file. Dates, quantities, scope, identity and revision are validated
after compaction, including values obtained from saved formula results.
The preview log records uploaded byte count and SHA-256 to identify the exact file
without logging its data. A valid unchanged workbook reports no changes and is not saved.
The modal/diagnostic update adds no migration beyond the existing core.0008.

The vertical chart marker is **Today**, based on the browser calendar day. It
advances at midnight and checks again when the window regains focus. The axis
includes today even outside the source schedule range. The separate **Data date**
badge retains the workbook snapshot date; curves and quantities are unchanged.
