# Skyline material readiness

The three lights belong to the existing **Cockpit → S03 Fabrication → Fabrication
skyline**. The normal home view loads the schedule, then calls
`skyline_source.attach_live_material_readiness()` to obtain the full line scope
from `skyline_material_source.skyline_material_readiness()`.

## Project rule

Use the existing DATAFY integration, fabrication records, material allocations,
procurement/yard status and drawing support readings before asking for another
spreadsheet or leaving indicators unconnected. The user explicitly confirmed
that these operational sources are available. Implement and verify changes in
the existing project and home view.

Keep interface labels in English. View-toggle buttons retain the same dimensions
in both states and reuse the existing button size for their section.

## Sources and matching

- Read the existing DATAFY PostgreSQL connection through `real_sources._datafy_conn`.
- Match the physical line identity: size, service and six-digit line number;
  normalize equivalent half-inch spellings and DATAFY specification suffixes.
- Include all current drawings belonging to that line. Drawing revisions and
  documents from different projects must not be mixed silently.
- Read the whole material scope, independent of the current dashboard filters.
- Reuse the Fabrication/Supply quantity and receipt logic for bolts, gaskets and
  valves. A material item is fully available only when its required quantity is
  covered by actual receipt, or its drawing is dated field-complete.
- Receipt proof belongs to the exact PO item. Its tracker overrides the parent
  PO, including a blank actual date. Daily-plan mappings must still match the
  current PO/item identity; a PO-wide date alone does not complete sibling items.
- Include physical valve tags linked to MTO items. This includes PSV/relief
  valves whose material family is Instrument. Description-only references do
  not classify an unrelated component as a required valve.
- Check support material rows and individual PS/SPS drawing occurrences together.
  The geometry extraction version determines whether absent support scope is
  known or unprocessed. Repeated references remain separate occurrences.
- The synthetic `PIPE_SUPPORT_TRACKING` allocation establishes PO coverage only;
  without physical evidence it leaves the support light pending. General piping
  fabrication progress cannot establish support completion: the current P6
  importer excludes support activities.

## States

| State | Meaning |
| --- | --- |
| `ready` | All required category items are available in DATAFY. |
| `partial` | Some items or quantities are available; required scope remains outstanding. |
| `pending` | Required scope exists and availability is outstanding. |
| `not_applicable` | Complete current drawing scope does not require the category. |
| `unknown` | Source, line identity, required quantities or scope cannot be established. |

`supports`, `erection` (bolts and gaskets), and `valves` are independent. A received
bolt does not complete the erection light while a required gasket remains pending.

The result is `charts.material_readiness[segment.line][category]`, containing
`status`, `source`, `as_of_date`, `note`, and supporting `counts`. All schedule
segments for one line use the same current operational state. The date buckets,
spool totals and existing fabrication box-fill rules remain schedule concerns.
Live status is not reconstructed historically from today's database.

## Skyline compact view

The header separates the title, schedule controls and scope totals from the
material category and color legends. Keep these groups spaced apart; do not
append long source/instruction text to the legend row. Source filenames belong
in the footer and operational evidence in the box details.

The chart header has its own **Show all / Collapse** control. The skyline
starts compact, showing up to six boxes per period and scenario; a **+N lines**
button identifies the remaining boxes and expands the whole chart. Period totals
and the underlying data always include every line. Expanding restores every box,
the original ordering and full tower heights; date columns remain unchanged.
The existing period modal continues to list the complete scope in either view.

## ROS / AVEON dates

**Export ROS / Import ROS** updates the manual ROS dates and spool quantities
through a reviewed workbook. Both ROS Skyline and Piping rundown use the same
accepted revision; live material evidence remains sourced from DATAFY. See
[Updating manual ROS data](ros-workbook-updates.md).

The schedule buttons switch locally between the current ROS snapshot and the
imported AVEON fabrication schedule. They retain the compact/full choice, line
scope, spool quantities and shared live material lights. Source-specific dates,
labels, totals, coverage and details are refreshed together. Neither the ROS
schedule nor its completion proxy can fill missing AVEON dates.

AVEON planned finish is the latest planned finish across the complete applicable
fabrication stages, including painting. The second band accepts only explicit,
nonfuture actual finish dates for all linked packages. Weekly/P6 progress remains
reported separately in details; a past planned date or 100% report cannot create
an actual finish date.

Match exact document line identity, with the explicit physical line in an
unlinked AVEON package name as a bounded fallback. If WBS and drawing line labels
disagree, a full exact and unique drawing-number link can resolve identity;
show the source discrepancy in box details. Other conflicts remain undated.

The current imported `AVEON Schedule 1.xlsx` provides dates for 163 lines / 602
spools. Three lines / 5 spools remain listed without dates; the comparison scope
stays 166 lines / 607 spools. Its AVEON WBS spool counts differ from this scope,
so quantities are never distributed among unmatched activity/spool names.
Source failure shows the AVEON error and leaves ROS available.

## Box details

Hover or focus an individual box to open its line detail panel. Click/tap to keep
it open; Escape, the close button, or an outside click dismisses it. The panel
starts compact for each newly opened box, keeping category states, available /
required items and PO allocation counts visible. The top **Show all** button
pins and expands the complete evidence; **Collapse** restores the summary.
The same open box keeps its selected view; another box or closing and reopening
starts compact again. Expanding does not reload or recalculate the data.
The expanded panel
keeps the three material categories together and explains each color with
required MTO items, items with/without an allocated PO, confirmed availability,
source and observation date. PO allocation is separate from receipt; the scope
includes items without an allocated PO. Counts refer to distinct MTO rows, not
spools or physical PS/SPS occurrences. Support occurrences remain explicit in
the evidence. A missing count displays a dash, not a fabricated zero.

`items_with_po` / `items_without_po` report allocation presence;
`fully_po_allocated_items` / `partly_po_allocated_items` compare allocated and
required quantities. They do not alter readiness colors. The box-fill schedule
status appears separately in the panel. Selecting a period spool total or the
panel's Period details action retains the existing schedule-period modal.

The normal cockpit always replaces optional snapshot material metadata with
live DATAFY results. No manual snapshot editing is needed. A connection failure
keeps the schedule visible and explains why the lights could not be refreshed;
it must not display unverified positive statuses from a static fallback.

## Verification

Run the snapshot, live material and existing-home integration tests:

```powershell
.\.venv\Scripts\python.exe manage.py test apps.core.tests.test_fabrication_skyline apps.core.tests.test_skyline_material_readiness apps.core.tests.test_skyline_live_materials apps.core.tests.test_skyline_aveon apps.core.tests.test_skyline_live_home
```

The home tests render the real view and template without creating users or writing
to operational databases. Live validation should report category totals and
inspect examples against the actual DATAFY quantities.
