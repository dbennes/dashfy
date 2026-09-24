# Section comments and minutes

Each dashboard section (S00–S05) has a small comment control grouped with its
existing header actions, rather than a full-width bar. The **!** button opens
the form; **History** lists its records, filters status and paginates 20 at a
time. Initials represent distinct comment authors, not live online presence.
The dashboard header exports **DASHFY_Minutes.xlsx**, containing one worksheet with
all visible comments and status events in chronological order.

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

Restart the application. Migration: **core.0009_section_notes**. No external
database or listener service is required.

Validation: `python manage.py test apps.core.tests.test_section_notes
apps.core.tests.test_rundown_live_home --noinput`. Browser checks cover desktop
and mobile creation, status changes, audit history, cancellation, information-only
records, avatar updates, keyboard closing, focus restoration and literal rendering
of HTML-like comment text. Browser fixtures never create operational comments.
