# Vessel tracking in Shellbi

The cockpit includes **Vessels** immediately before **3D Model**. It uses real
AISStream observations, an authenticated Django API and Leaflet 1.9.4 with
OpenStreetMap tiles. There are no seeded vessels, simulated positions or
predicted routes. Existing fabrication, skyline and rundown sources are independent.

## Activate collection

Use the existing DASHFY PostgreSQL database, not the DATAFY database. After
updating the application on each server:

```bash
pip install -r requirements.txt
python manage.py migrate --database default
python manage.py collectstatic --noinput
```

Set `AISSTREAM_API_KEY` in the server's private `.env` using a key from
[AISStream](https://aisstream.io/). Restart Django after changing configuration.
The key is used only by the backend collector; the browser receives a configured
flag and sanitized connection status, never the key or subscription payload.

In **Vessels → Add vessel**, an administrator registers a name and nine-digit
MMSI. IMO and vessel type are optional. MMSI is fixed after registration to avoid
merging unrelated histories. **Stop tracking** retains the vessel and its history;
it can be reactivated. Authenticated cockpit users can view the fleet and tracks.

Start the independent collector:

```bash
python manage.py listen_ais
```

It continues receiving AIS with all browsers closed. A separate process must
remain running; Gunicorn/ASGI alone does not start collection. With no active
vessels the collector waits without subscribing to worldwide vessel traffic.
Registering or stopping tracking refreshes the subscription within 30 seconds.
The fleet supports up to 200 active MMSIs, matching the provider's subscription
limit. Run one collector per database; a PostgreSQL advisory lock prevents a
second collector from processing the same fleet.

For Linux, adjust the user and paths in [the service template](../deploy/dashfy-ais.service),
then install it as `/etc/systemd/system/dashfy-ais.service`:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dashfy-ais
sudo systemctl status dashfy-ais
sudo journalctl -u dashfy-ais -f
```

After code or `.env` changes restart both the web application and `dashfy-ais`.
On Windows the foreground command works from the project's virtual environment;
use the existing process supervisor or Task Scheduler for unattended operation.
The collector needs outbound HTTPS/WSS access to AISStream. Map tiles are fetched
normally by the browser; no tile prefetching or offline harvesting is implemented.

## Data rules

* The latest received valid position updates the vessel. Older or duplicate
  reports cannot move its current position backwards in time. Static/voyage
  messages update metadata without moving the vessel.
* The first valid observation is stored. Further history is stored every 180
  seconds, after movement of at least 250 metres, or a course change of at least
  15 degrees; a 10-second minimum spacing bounds bursts. These are configurable.
* History consists of received AIS observations, indexed by vessel and timestamp.
  It persists across restarts and deactivation and belongs to DASHFY. It starts
  when collection starts; there is no historical backfill from the free stream.
* AIS unavailable-value sentinels become missing fields, not zero coordinates,
  speed or heading. Vessels use a blue pulsing dot; freshness remains explicit in status badges.
  Reduced-motion preferences disable the pulse.
* The dashed **REAL TRACK** connects stored observations chronologically. Large
  query results are sampled from actual rows, preserving the first and last
  observations. Sampling does not create estimated positions. A line between
  observations is not a verified navigable route.
* **RECENT** means the last actual AIS position is at most 10 minutes old;
  **STALE** is 10–60 minutes; **NO RECENT AIS** means older than 60 minutes or no
  received position. The marker stays at the last actual position when signal is
  lost. Collector connection status is shown separately from vessel freshness.
* Destination and ETA are declarations from the vessel and may be outdated.
  AIS ETA supplies month/day/time without a year; the application does not infer
  a year or construct a route to that destination.
* Every stored observation records the `provider` that delivered it, so stream
  and imported rows stay distinguishable in the admin and in exports.
* All displayed history times and custom range inputs use UTC. The browser polls
  every 20 seconds while the section is visible, without reloading the cockpit.

Connection loss triggers capped exponential backoff with jitter. Logs record
connection/reconnection and sanitized error categories. The dashboard detects an
expired collector heartbeat after 120 seconds. PostgreSQL backups must include
the new `vessels_*` tables. No automatic history deletion is enabled.

## Importing a provider report

Terrestrial AIS networks only reach roughly 40-60 nautical miles offshore, so a
vessel working far from the coast produces no stream observations at all. When a
commercial provider has positions the free stream does not, its exported report
can be imported instead of waiting for the collector.

```bash
python manage.py import_vessel_report report.csv --dry-run
python manage.py import_vessel_report report.csv
```

Always inspect with `--dry-run` first: it parses the file, resolves each row
against the fleet and prints exactly what a real import would store, without
writing anything. Both runs print every observation with its **real age**, so a
stale export is visible rather than silently becoming the current position.

| Option | Purpose |
| --- | --- |
| `--dry-run` | Parse and report without writing |
| `--provider <label>` | Channel recorded for auditing (default `marinetraffic_report`) |
| `--max-age-hours <n>` | Refuse the import when the newest fix is older than this |

Export the report as CSV (or TSV) from the provider. Headers are matched by
alias and are case-insensitive, so most exports work unchanged; provider
preamble lines above the header row are skipped. A row needs an **MMSI** (or
**IMO**) plus **latitude**, **longitude** and a **timestamp**. Recognised
alternatives include `Ship MMSI`, `Position Received`, `Last Pos`, `LAT`/`LON`,
`Speed`, `Course`, `Heading` and `Destination`. Comma, semicolon, tab and pipe
delimiters are detected automatically, as are UTF-8 BOM and Latin-1 encodings.

Import rules follow the collection rules above:

* Only vessels already registered are updated. A report never creates a
  registration, so an unknown MMSI is reported and skipped.
* Timestamps without an offset are read as UTC; epoch seconds and milliseconds
  are also accepted. A timestamp more than five minutes in the future is rejected.
* `0, 0`, out-of-range coordinates and AIS sentinel values for speed, course and
  heading become missing fields; the row is skipped only if the position itself
  is unusable. Unparseable rows are listed, never guessed at.
* Re-importing the same report is safe: `(vessel, timestamp)` is unique, so
  duplicates are counted and ignored. Scheduling repeated imports of an
  overlapping export cannot corrupt the track.
* An observation older than the vessel's current position is still stored as
  history but never moves the vessel backwards.
* Imported rows keep `source="AIS"` because they are real AIS observations;
  `provider` records which channel delivered them. Nothing here estimates or
  interpolates a position.

Importing a report does not make an old position current. If the provider's
newest fix is weeks old, the vessel legitimately has no recent AIS, and the
dashboard continues to show **NO RECENT AIS** with the observation's real time.

## Configuration

Defaults are documented in [`.env.example`](../.env.example):

| Setting | Default / purpose |
| --- | --- |
| `AISSTREAM_API_KEY` | Required server-only provider key |
| `AISSTREAM_BOUNDING_BOXES` | `[[[-90,-180],[90,180]]]`; exact registered MMSIs are always filtered |
| `AIS_POSITION_INTERVAL_SECONDS` | `180` |
| `AIS_POSITION_MIN_SECONDS` | `10` |
| `AIS_POSITION_DISTANCE_METERS` | `250` |
| `AIS_POSITION_COURSE_DEGREES` | `15` |
| `AIS_SUBSCRIPTION_REFRESH_SECONDS` | `30` |
| `AIS_RECENT_SECONDS` / `AIS_STALE_SECONDS` | `600` / `3600` |
| `AIS_HEARTBEAT_TIMEOUT_SECONDS` | `120` |
| `AIS_MAX_ACTIVE_VESSELS` | `200` maximum |
| `AIS_MAX_TRACK_POINTS` | `5000` maximum; API default `2000` |
| `AIS_POLL_SECONDS` | `20`; browser bounds to 10–30 seconds |
| `AIS_MAP_TILE_URL` | `https://tile.openstreetmap.org/{z}/{x}/{y}.png` |
| `AIS_MAP_ATTRIBUTION` | OpenStreetMap contributors link; update with a different tile provider |

The stream URL is fixed to the official AISStream WSS endpoint. Leaflet code and
styles are vendored with their license. Tile provider configuration allows a
different provider if usage outgrows public OSM tile service capacity.

## API

All endpoints require the existing authenticated session and return JSON.
Create/update also require an administrator and a valid CSRF token. Responses
use `Cache-Control: private, no-store`.

| Method and path | Purpose |
| --- | --- |
| `GET /vessels/api/vessels/` | Fleet, latest observations, freshness, collector status |
| `POST /vessels/api/vessels/` | Register `name`, `mmsi`, optional `imo`, `vessel_type`, `is_active` |
| `GET /vessels/api/vessels/<id>/` | Vessel details |
| `PATCH /vessels/api/vessels/<id>/` | Edit registration or set `is_active: false`; preserves history |
| `GET /vessels/api/vessels/<id>/latest/` | Latest received position and metadata |
| `GET /vessels/api/vessels/<id>/positions/?range=24h&limit=2000` | Chronological stored positions |
| `GET /vessels/api/status/` | Collector configuration and heartbeat status |

Ranges: `24h`, `7d`, `30d`, or `custom` with timezone-aware `start` and `end`, e.g.
`start=2026-09-01T00:00:00Z&end=2026-09-15T23:59:59Z`. A history response reports
`total_count`, `returned_count` and `simplified`; limits must be between 2 and the
configured maximum. The source of every track observation is `AIS`.

## Verification

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test apps.vessels --keepdb --noinput
node --test apps/core/tests/test_vessel_tracking_frontend.cjs
node --test apps/core/tests/test_vessel_dossier_boot.mjs
```

Tests use AIS message fixtures and mocked transport; they do not require a key
or create records in the operational fleet. After setting a real key, verify
the collector connects, a registered MMSI receives a timestamped position, and
its stored track grows over time. Free AIS coverage is not continuous worldwide.

Provider references: [AISStream WebSocket protocol](https://aisstream.io/documentation),
[Leaflet](https://leafletjs.com/reference.html),
[OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/).

## Map and journey summary

The workspace uses the model viewer height: `clamp(520px, calc(100vh - 190px), 760px)`.
The detail column scrolls independently, and mobile stacks the panels.
`All history` is the default map period (`range=all` is also supported by CSV export).
The API still bounds and samples large histories while retaining the first and last
observations. Period filters only change the view; they never delete saved positions.
The journey summary uses observed port arrivals and departures independently of the
selected history period. The latest received position remains the current location.
Only saved AIS observations form the blue dashed route. Collection and imports
continue to persist positions in the existing database, independently of the browser.

## Operational arrival areas

`AIS_PORT_GEOFENCES` defines fixed circular areas in metres. The initial
**AVEON JETTY PH** area has a **3,000 m** radius around **4.7942467, 6.9417582**.
This is an operational area anchored to the position recorded on 16 September
2026 and identified by the user as AVEON, not a surveyed jetty boundary. Its centre remains
fixed when the vessel moves.

A valid position inside the area marks **Arrived**; the first newer position
outside marks **Underway** and makes the departed port the journey origin.
If the declared AIS destination still names that port, the next destination is
left empty until a different destination is reported. A new declaration becomes
the next destination; entering a known destination's circle marks arrival there.
An accepted change of destination after departure clears the stale declaration
marker. For example, **BONGA -> AVEON JETTY PH** then shows AVEON as the return
destination while the vessel is still outside its circle. Repeated unchanged
AVEON declarations alone do not imply a new return trip. Each new departure
starts this rule afresh; entering the circle always takes precedence as arrival.
The original AIS `destination` is retained unchanged for source traceability.
Arrival and departure times are observation times, not interpolated crossing times.
Signal freshness is separate: an old position may still show the last observed
arrival while keeping its stale/no-recent-AIS indicator.

Migration `vessels.0003_vessel_voyage_state` adds journey state without changing
positions. Existing vessels derive their initial arrival from their latest stored
position when read, without database writes or history scans. Each subsequent
newer AIS or imported position advances the state atomically with that position.
Older and duplicate reports retain their history but cannot rewind a journey.
Changing the map history period never changes journey origin or destination.

Migration `vessels.0004_vessel_destination_seen_at` gives destination declarations
their own observation timestamp. An older AIS static message cannot overwrite a
newer imported destination, and an older destination in a position report cannot
overwrite a newer AIS declaration. Other static metadata retains its independent
ordering; equal-time conflicting declarations keep the value already accepted.
Existing declarations without this timestamp use the latest known observation as
a conservative initial boundary until a newer declaration is received.

## AVEON / BONGA NORTH regular shuttle

**BONGA NORTH** is a second permanent map area centred on the coordinates
provided by the user: **latitude 4.5575266, longitude 4.6164432**, with a **3,000 m**
radius. Both AVEON and BONGA areas stay fixed on the map.

`AIS_VESSEL_SHUTTLE_ROUTES` assigns only **EASTERN URSINIA / MMSI 636023616**
the regular route **AVEON JETTY PH <-> BONGA NORTH**. While the vessel is inside
one area, the API keeps that port as the observed arrival and supplies the
opposite port as `next_destination`. After departure, the destination is the
opposite end of the last observed origin, with `destination_source=scheduled_route`.
This scheduled target does not inherit the AIS declaration's ETA. A vessel outside
both areas without an observed origin has BONGA as its configured outbound target;
its origin remains unknown. Missing GPS still means unknown location, not arrival.

The API includes `route_ports` for the configured shuttle. Other vessels retain
their AIS-declared destination behavior (`destination_source=ais_declared`), and
observed arrivals use `destination_source=arrival`. Raw AIS declarations and all
stored positions remain unchanged. Direction changes follow newer observed port
arrivals/departures; loading an older export or changing the map period cannot
reverse the journey.
