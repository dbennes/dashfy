# Niger Delta water mask

`niger-delta-water.png` is a derived OpenStreetMap water/ocean polygon extract
covering Bonga North, the Niger Delta and Port Harcourt. White pixels are mapped
water; black pixels are land or unavailable coverage. Resolution is approximately
38 metres, with a one-pixel inset from mapped banks. Islands remain excluded.

Source: [OpenStreetMap contributors](https://www.openstreetmap.org/copyright),
distributed by [VersaTiles](https://docs.versatiles.org/guides/use_tiles_versatiles_org).
Derived database licence: [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
Metadata and file checksum are in `niger-delta-water.json`. No ESA landcover layer
is used. The public tile provider is contacted only by the build tool, never by
the production route calculation.

Rebuild with `python tools/build_water_mask.py`, using existing requirements.
The builder caches source tiles under `tmp/water-tiles/`. Preserve that directory
for byte-reproducible rebuilds; a new download may use updated OSM geometry.

This is a display aid for estimating connections between recorded AIS fixes.
It does not establish the vessel's actual path and does not model depths, tides,
bridges, traffic restrictions or vessel clearance. It is not a navigation chart.
Outside the extract, or where there is no connected mapped water, keep the
observations visible without drawing an unsupported connection.
