"""Offline, water-constrained connections between AIS fixes for display only.

Original observations are never moved or written. These paths are estimates,
not measured tracks or nautical navigation instructions (no depth/tide model).
"""
from functools import lru_cache
import heapq
import json
import math
from pathlib import Path
import time

from PIL import Image
import numpy as np

DATA = Path(__file__).with_name("data")
MAX_VISITS = 250_000
STEP = 1  # ~38m lattice, retaining the narrow approach to Aveon


class WaterMask:
    def __init__(self, metadata, image):
        self.meta = metadata
        self.width, self.height = image.size
        self.bits = image.convert("1").tobytes()
        self.row_bytes = (self.width + 7) // 8
        self.scale = (2 ** metadata["zoom"]) * metadata["tile_size"]
        self.origin = tuple(v * metadata["tile_size"] for v in metadata["origin_tile"])
        # Merge only entirely-water squares. Open sea becomes a small graph,
        # while riverbanks/islands retain the original pixel resolution.
        pixels = np.asarray(image.convert("1"), dtype=bool)
        height = math.ceil(self.height / 64) * 64
        width = math.ceil(self.width / 64) * 64
        pixels = np.pad(pixels, ((0, height - self.height), (0, width - self.width)))
        self.levels = []
        for _ in range(6):
            pixels = pixels.reshape(pixels.shape[0] // 2, 2, pixels.shape[1] // 2, 2).all(axis=(1, 3))
            self.levels.append(pixels)

    def pixel(self, lat, lon):
        x = (lon + 180) / 360 * self.scale - self.origin[0]
        y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * self.scale - self.origin[1]
        return round(x), round(y)

    def coordinate(self, pixel):
        x, y = pixel
        lon = (x + self.origin[0]) / self.scale * 360 - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + self.origin[1]) / self.scale))))
        return [round(lat, 7), round(lon, 7)]

    def water(self, x, y):
        return (0 <= x < self.width and 0 <= y < self.height
                and bool(self.bits[y * self.row_bytes + (x >> 3)] & (128 >> (x & 7))))

    def clear(self, a, b):
        """Supercover raster line: check both sides of diagonal corner crossings."""
        x, y = a
        dx, dy = b[0] - x, b[1] - y
        nx, ny = abs(dx), abs(dy)
        sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
        ix = iy = 0
        if not self.water(x, y):
            return False
        while ix < nx or iy < ny:
            decision = (1 + 2 * ix) * ny - (1 + 2 * iy) * nx
            if decision == 0:
                if not self.water(x + sx, y) or not self.water(x, y + sy):
                    return False
                x += sx; y += sy; ix += 1; iy += 1
            elif decision < 0:
                x += sx; ix += 1
            else:
                y += sy; iy += 1
            if not self.water(x, y):
                return False
        return True

    def anchor(self, point):
        """Connect to a nearby water lattice cell, never through a bank/island."""
        x, y = point
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        on_water = self.water(x, y)
        options = []
        # At most ~300m from an imprecise quay observation. The AIS marker stays
        # at its received coordinates; only the estimated path starts on water.
        for cy in range((y // STEP) * STEP - 6, (y // STEP) * STEP + 8, STEP):
            for cx in range((x // STEP) * STEP - 6, (x // STEP) * STEP + 8, STEP):
                distance = math.hypot(cx - x, cy - y)
                if distance <= 7 and self.water(cx, cy):
                    options.append((distance, (cx, cy)))
        for _, candidate in sorted(options):
            if not on_water or self.clear(point, candidate):
                return candidate
        return None

    def path(self, start, end):
        if self.clear(start, end):
            return [start, end]
        first_anchor, last_anchor = self.anchor(start), self.anchor(end)
        if first_anchor is None or last_anchor is None:
            return None
        first, last = self.cell(*first_anchor), self.cell(*last_anchor)
        queue = [(math.dist(first[:2], last[:2]), 0, first)]
        costs, parents = {first: 0}, {}
        visits = 0
        while queue and visits < MAX_VISITS:
            _, cost, point = heapq.heappop(queue)
            if cost != costs.get(point):
                continue
            if point == last:
                result, current = [last[:2]], last
                while current != first:
                    previous, via = parents[current]
                    result.extend(reversed(via))
                    result.append(previous[:2])
                    current = previous
                result.reverse()
                if result[0] != first_anchor:
                    result.insert(0, first_anchor)
                if result[-1] != last_anchor:
                    result.append(last_anchor)
                if self.clear(start, first_anchor):
                    result.insert(0, start)
                if self.clear(last_anchor, end):
                    result.append(end)
                return self.simplify(result)
            visits += 1
            for neighbour, via in self.neighbours(point):
                steps = (point[:2], *via, neighbour[:2])
                candidate = cost + sum(math.dist(a, b) for a, b in zip(steps, steps[1:]))
                if candidate >= costs.get(neighbour, math.inf):
                    continue
                costs[neighbour], parents[neighbour] = candidate, (point, via)
                # Weighted A* bounds work for display routes; shortest/nautical
                # optimality is deliberately not claimed.
                heapq.heappush(queue, (candidate + 1.15 * math.dist(neighbour[:2], last[:2]), candidate, neighbour))
        return None

    def cell(self, x, y):
        if not self.water(x, y):
            return None
        for level in range(6, 0, -1):
            if self.levels[level - 1][y >> level, x >> level]:
                size = 1 << level
                return (x // size * size + size // 2, y // size * size + size // 2, size)
        return (x, y, 1)

    @lru_cache(maxsize=32768)
    def neighbours(self, node):
        x, y, size = node
        left, top = x - size // 2, y - size // 2
        result = {}
        for axis in (0, 1):
            for side in (-1, size):
                offset = 0
                while offset < size:
                    px, py = (left + side, top + offset) if axis == 0 else (left + offset, top + side)
                    cell = self.cell(px, py)
                    if cell:
                        via = ()
                        if not self.clear(node[:2], cell[:2]):
                            inside = (px + (1 if side == -1 else -1), py) if axis == 0 else (px, py + (1 if side == -1 else -1))
                            via = (inside, (px, py))
                        result.setdefault(cell, via)
                        boundary = cell[1 - axis] - cell[2] // 2 + cell[2]
                        offset = max(offset + 1, boundary - (top if axis == 0 else left))
                    else:
                        offset += 1
        return tuple(sorted(result.items()))

    def simplify(self, points):
        result = [points[0]]
        # Local string pulling keeps every retained edge entirely in water.
        index = 0
        while index < len(points) - 1:
            next_index = index + 1
            for candidate in range(index + 2, min(len(points), index + 128)):
                if not self.clear(points[index], points[candidate]):
                    break
                next_index = candidate
            if points[next_index] != result[-1]:
                result.append(points[next_index])
            index = next_index
        return result


@lru_cache(maxsize=1)
def water_mask():
    metadata = json.loads((DATA / "niger-delta-water.json").read_text(encoding="utf-8"))
    with Image.open(DATA / "niger-delta-water.png") as image:
        return WaterMask(metadata, image)


@lru_cache(maxsize=2048)
def route_pair(a, b):
    mask = water_mask()
    start, end = mask.pixel(*a), mask.pixel(*b)
    # Search outward from the confined river end. Starting in open sea expands
    # vast equivalent cells before discovering a narrow port entrance.
    def openness(point):
        return sum(mask.water(point[0] + dx * 32, point[1] + dy * 32)
                   for dx in range(-2, 3) for dy in range(-2, 3))
    reverse = openness(start) > openness(end)
    path = mask.path(end, start) if reverse else mask.path(start, end)
    if path is None:
        return None
    if reverse:
        path.reverse()
    return tuple(tuple(mask.coordinate(point)) for point in path)


def estimated_water_routes(positions):
    """The API keeps `positions` untouched and attaches a separate route layer."""
    segments, unresolved, pending = [], 0, 0
    started = time.monotonic()
    for index, (first, last) in enumerate(zip(positions, positions[1:])):
        # A long/corrupt history cannot occupy a web worker indefinitely. The
        # next refresh reuses cached geometry and continues remaining pairs.
        if time.monotonic() - started > 2:
            pending = len(positions) - 1 - index
            break
        a = (float(first["latitude"]), float(first["longitude"]))
        b = (float(last["latitude"]), float(last["longitude"]))
        if a == b:
            continue
        coordinates = route_pair(a, b)
        if coordinates is None:
            unresolved += 1
            continue
        segments.append({"from_id": first.get("id"), "to_id": last.get("id"),
                         "timestamp": last["timestamp"], "coordinates": coordinates})
    return {"kind": "estimated_water_route", "segments": segments,
            "unresolved": unresolved, "pending": pending, "coverage": "Niger Delta · Bonga / Port Harcourt",
            "source": "OpenStreetMap contributors / VersaTiles", "version": 1}
