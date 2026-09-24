# Section comments and minutes

Each individual chart, table and vessel panel has its own comment history.
The amber **! / History** control sits on a separate row immediately above that
panel, aligned to the right on desktop and mobile. It does not share the chart's
header action row. There are 25 stable panel identifiers, including Piping ISO
rundown, Wooden Box skyline, fabrication charts, supply tables, shipment charts,
3D review, vessel tracking, fleet, details and the vessel map.

**!** opens the form; **History** lists only that panel's records with status filters
and 20 records per page. Initials and counts belong exclusively to that panel.
The top **Export minutes** action exports all visible comments in a single sheet,
identifying both the parent section and the panel for each event.

Existing section-level records are retained with an empty panel. The top
**Previous section comments** button appears only when those records exist and
allows reviewing/updating them. They are never assigned to a chart by inference.
The export includes them as **Previous section comments**. New panel records
use a validated stable panel key, independent of display names or DOM order.

Authenticated colleagues in the same client scope can create comments and change
their status. Internal users without a client share the internal scope. Client
records are isolated in listings, summaries, status updates and the Excel export.
The project identifier is BN-EPC1, matching this dashboard.

Comments begin as **Pending**. A note date and text (up to 4,000 characters) are
required. A forecast completion date is required unless **Information only** is
checked. Informational records are included in the history but not in the pending
action count. Current dashboard date, discipline, campaign and week filters are
captured as context when available.

The original note and author remain unchanged. **Resolved**, **Cancelled** and a
return to **Pending** each append an event containing the previous/new status,
server timestamp, authenticated actor ID and name snapshot. Cancelled notes stay
visible with faded, struck-through text. Changing a cancelled record back to
Pending is also audited. Optimistic versions reject concurrent stale changes;
creation request IDs prevent duplicate records when a request is retried.

The export has one row per event, with the note, author, dates, current status,
previous/event status and actor. It includes cancelled records, preserves names
after user removal, freezes headers and adds table filters. User text is written
as literal text, never Excel formulas or links. Timestamps identify the configured
server timezone; browser timestamps display in the user's local timezone.

Deploy:

```powershell
git pull --ff-only
python manage.py migrate --database default
python manage.py collectstatic --noinput
```

Restart the application. Migrations: **core.0009_section_notes** and **core.0010_section_note_panel**. No external
database or listener service is required.

Validation: `python manage.py test apps.core.tests.test_section_notes
apps.core.tests.test_rundown_live_home --noinput`. Browser checks cover desktop
and mobile creation, status changes, audit history, cancellation, information-only
records, avatar updates, keyboard closing, focus restoration and literal rendering
of HTML-like comment text. Browser fixtures never create operational comments.
