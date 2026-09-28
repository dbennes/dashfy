"""Build the offline Niger Delta water mask from OSM/VersaTiles vector polygons.

Uses existing Pillow/requests dependencies; no map service is called at runtime.
Run from the repository root: python tools/build_water_mask.py
Cached source tiles in tmp/water-tiles make rebuilding reproducible/offline.
MVT format: https://github.com/mapbox/vector-tile-spec/tree/master/2.1
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter
import requests

ZOOM, TILE_SIZE = 12, 256
BOUNDS = (4.3, 3.4, 7.5, 5.05)  # west, south, east, north; includes Bonga North
ROOT = Path(__file__).resolve().parents[1]


def varint(data, offset):
    result = shift = 0
    while True:
        byte = data[offset]
        offset += 1
        result |= (byte & 127) << shift
        if byte < 128:
            return result, offset
        shift += 7
        if shift > 70:
            raise ValueError("Invalid protobuf varint")


def fields(data):
    offset = 0
    while offset < len(data):
        key, offset = varint(data, offset)
        wire = key & 7
        if wire == 0:
            value, offset = varint(data, offset)
        elif wire == 2:
            size, offset = varint(data, offset)
            value, offset = data[offset:offset + size], offset + size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value, offset = data[offset:offset + size], offset + size
        else:
            raise ValueError("Unsupported protobuf wire type")
        yield key >> 3, value


def rings(data):
    offset = x = y = 0
    ring = []
    while offset < len(data):
        command, offset = varint(data, offset)
        kind, count = command & 7, command >> 3
        if kind == 7:
            if len(ring) >= 3:
                yield ring
            ring = []
        elif kind in (1, 2):
            for _ in range(count):
                dx, offset = varint(data, offset)
                dy, offset = varint(data, offset)
                x += (dx >> 1) ^ -(dx & 1)
                y += (dy >> 1) ^ -(dy & 1)
                ring.append((x, y))
        else:
            raise ValueError("Unsupported MVT geometry command")


def raster(data):
    tile = Image.new("L", (TILE_SIZE, TILE_SIZE))
    for tag, layer in fields(data):
        if tag != 3:
            continue
        entries = list(fields(layer))
        name = next(value.decode() for key, value in entries if key == 1)
        if name not in ("water_polygons", "ocean"):
            continue
        extent = next((value for key, value in entries if key == 5), 4096)
        for key, feature in entries:
            if key != 2:
                continue
            values = dict(fields(feature))
            if values.get(3) != 3:
                continue
            part = Image.new("L", tile.size)
            draw = ImageDraw.Draw(part)
            for ring in rings(values[4]):
                area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1]))
                # MVT exteriors are clockwise in screen coordinates; holes CCW.
                draw.polygon([(x * TILE_SIZE / extent, y * TILE_SIZE / extent) for x, y in ring], fill=255 if area > 0 else 0)
            tile = ImageChops.lighter(tile, part)
    return tile


def tile_xy(lon, lat):
    return ((lon + 180) / 360 * 2 ** ZOOM,
            (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** ZOOM)


def main():
    west, south, east, north = BOUNDS
    xmin, ymin = map(math.floor, tile_xy(west, north))
    xmax, ymax = map(math.ceil, tile_xy(east, south))
    cache = ROOT / "tmp/water-tiles"
    cache.mkdir(parents=True, exist_ok=True)
    target = ROOT / "apps/vessels/data"
    target.mkdir(parents=True, exist_ok=True)
    image = Image.new("L", ((xmax - xmin) * TILE_SIZE, (ymax - ymin) * TILE_SIZE))
    coords = [(x, y) for y in range(ymin, ymax) for x in range(xmin, xmax)]

    def fetch(coord):
        x, y = coord
        filename = cache / f"{ZOOM}-{x}-{y}.pbf"
        if not filename.exists():
            response = requests.get(f"https://tiles.versatiles.org/tiles/osm/{ZOOM}/{x}/{y}", timeout=30)
            response.raise_for_status()
            filename.write_bytes(response.content)
        return coord, raster(filename.read_bytes())

    with ThreadPoolExecutor(max_workers=4) as executor:
        for index, ((x, y), tile) in enumerate(executor.map(fetch, coords), 1):
            image.paste(tile, ((x - xmin) * TILE_SIZE, (y - ymin) * TILE_SIZE))
            if index % 50 == 0:
                print(f"Water tiles {index}/{len(coords)}", flush=True)
    # Inset shorelines by one pixel (~38m), retaining islands and narrow land
    # strips. Do this after stitching to avoid artificial barriers at tile seams.
    image = image.filter(ImageFilter.MinFilter(3)).convert("1")
    image.save(target / "niger-delta-water.png", optimize=True)
    metadata = {
        "version": 1, "zoom": ZOOM, "tile_size": TILE_SIZE,
        "origin_tile": [xmin, ymin], "size": list(image.size),
        "built_at": datetime.now(timezone.utc).isoformat(), "requested_bounds": BOUNDS,
        "source": "OpenStreetMap water and ocean polygons via VersaTiles",
        "source_url": "https://tiles.versatiles.org/tiles/osm/{z}/{x}/{y}",
        "license": "ODbL-1.0", "attribution": "© OpenStreetMap contributors",
        "shore_inset_pixels": 1,
        "sha256": hashlib.sha256((target / "niger-delta-water.png").read_bytes()).hexdigest(),
    }
    (target / "niger-delta-water.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print("Saved", image.size, (target / "niger-delta-water.png").stat().st_size, "bytes", flush=True)


if __name__ == "__main__":
    main()
