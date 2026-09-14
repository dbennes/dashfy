# Updating manual ROS data

The S03 Skyline toolbar provides **Export ROS** and **Import ROS**. Export
downloads the current editable workbook. Import opens a review page: upload the
edited workbook, inspect current and updated values, then select **Apply changes**.
The same accepted revision supplies the ROS Skyline and Piping rundown.

## Source ownership

| Data | Where to update |
| --- | --- |
| ROS baseline dates, lookahead dates, spool quantities and source data date | DASHFY ROS workbook |
| AVEON fabrication dates and Structural rundown | Existing schedule import in DATAFY |
| Weekly fabrication progress | Existing authoritative progress workbook import in DATAFY |
| Supports, bolts/gaskets and valve availability | DATAFY fabrication/material/PO/receipt records |
| Engineering monitor | Existing DASHFY engineering export/import |

The ROS workbook does not overwrite integrated DATAFY fields. ROS spool
quantities also define the physical scope used by the AVEON Skyline view; the
AVEON dates still come from DATAFY.

## Workbook contract

- **ROS Schedule:** Row ID and Line identify existing release rows and remain
  fixed. Baseline Date, Lookahead Date and Spools are editable yellow cells.
- **Settings:** Data date is editable; format, version and revision identify the
  exported workbook. The source date does not replace the application's current
  date used for existing Skyline classification.
- **Rundown:** reference values derived from accepted ROS releases. Editing this
  sheet does not change imported values.
- **Instructions:** explains the update workflow and source ownership.

All current rows must remain, including split releases for a line. Row order
may change. Adding/removing rows or renaming lines is outside this update
workflow. Dates must be Excel dates or ISO YYYY-MM-DD values; quantities must be
positive whole numbers. Split rows for one line must keep the same baseline
date. Formulas in editable sheets, duplicate/missing IDs and malformed workbooks
are rejected. Uploads are limited to 10 MB with bounded expanded workbook size.

## Persistence and display

Migration `core.0007_rosscheduleimport` adds append-only ROS import versions in
the DASHFY database. Each version records the user, timestamp, filename, file
hash, source date, changed fields and both source payloads. The original
versioned JSON files seed the workflow only until the first accepted import.
Database failure makes ROS unavailable instead of silently showing the old seed.

An unchanged export/import creates no version and preserves every original
Skyline row and Rundown point. After an edit, rundown releases are grouped by
the exact ROS dates. Balances retain the existing start-of-day convention: the
zero balance is shown on the day after the final release, followed by blank
points for that scenario. The original date grid is retained and extended with
new release and finish dates.

Previews are signed, bound to the importing user and valid for 30 minutes.
The current revision is checked again when applying; a unique base revision
prevents two competing imports from overwriting each other. Import and preview
require an administrator. Export requires an authenticated session, consistent
with the existing DASHFY export flows.

## Validation

Tests cover untouched roundtrips, actual date/quantity edits, shared baselines,
identity validation, formulas, malformed files, report-date changes, no-op
imports, stale revisions, atomic storage, preview/apply permissions and the
home's use of the accepted revision. Run in an isolated test database with
operational DATAFY connections blocked. No sample update needs to be applied to
the operational ROS schedule to exercise this workflow.
