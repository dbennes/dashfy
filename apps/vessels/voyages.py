"""Observed port arrivals and departures, independent of the map's history filter.

Only a newer, valid position advances a journey. The declared AIS destination
stays untouched: the public journey can suppress an obsolete departure port
without rewriting the provider's original declaration.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
import re

from django.conf import settings


def _number(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and minimum <= value <= maximum else None


def _timestamp(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    try:
        return value.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def configured_geofences(geofences=None):
    """Return safe, JSON-ready geometry; invalid configuration cannot mark arrival."""
    values = getattr(settings, "AIS_PORT_GEOFENCES", ()) if geofences is None else geofences
    result = []
    seen = set()
    for value in values if isinstance(values, (list, tuple)) else ():
        if not isinstance(value, dict):
            continue
        identifier, name = value.get("id"), value.get("name")
        latitude = _number(value.get("latitude"), -90, 90)
        longitude = _number(value.get("longitude"), -180, 180)
        radius = _number(value.get("radius_m"), 0.01, 1_000_000)
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            continue
        if not isinstance(name, str) or not name.strip() or None in (latitude, longitude, radius):
            continue
        seen.add(identifier)
        result.append({"id": identifier, "name": name.strip(), "latitude": latitude,
                       "longitude": longitude, "radius_m": radius})
    return result


def _distance_metres(latitude, longitude, port):
    lat1, lat2 = math.radians(latitude), math.radians(port["latitude"])
    delta = math.radians(port["longitude"] - longitude)
    arc = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(min(1, max(0, arc))))


def _empty_state():
    return {"status": "unknown", "origin": None, "current_port": None,
            "arrived_at": None, "departed_at": None, "position_timestamp": None,
            "suppressed_destination": None}


def _suppressed_destination(state):
    if "suppressed_destination" in state:
        return state["suppressed_destination"]
    # States persisted before this marker existed used the origin as the stale
    # declaration. Retain that interpretation until a changed target is received.
    origin = state.get("origin")
    return origin.get("name") if state.get("status") == "underway" and isinstance(origin, dict) else None


def advance_voyage(state, *, latitude, longitude, timestamp, geofences=None):
    """Pure transition from a received fix; old/equal/invalid fixes are no-ops.

    Arrival/departure times mean the first received fix proving the transition,
    not an interpolated time at which a vessel crossed the radius.
    """
    result = _empty_state()
    if isinstance(state, dict):
        result.update({key: deepcopy(state[key]) for key in result if key in state})
        result["suppressed_destination"] = _suppressed_destination(state)
    latitude, longitude = _number(latitude, -90, 90), _number(longitude, -180, 180)
    moment = _timestamp(timestamp)
    previous_moment = _timestamp(result["position_timestamp"])
    if latitude is None or longitude is None or moment is None:
        return result
    if previous_moment is not None and moment <= previous_moment:
        return result

    ports = configured_geofences(geofences)
    previous = result["current_port"] if isinstance(result["current_port"], dict) else None
    candidates = [(_distance_metres(latitude, longitude, port), port) for port in ports]
    candidates = [(distance, port) for distance, port in candidates if distance <= port["radius_m"]]
    # Keep a port while its circle still contains the vessel if circles overlap.
    candidates.sort(key=lambda item: (not (previous and previous.get("id") == item[1]["id"]),
                                      item[0], item[1]["id"]))
    current = candidates[0][1] if candidates else None
    changed_port = (previous or {}).get("id") != (current or {}).get("id")
    observed_at = moment.isoformat()
    if previous and changed_port:
        result["origin"] = deepcopy(previous)
        result["departed_at"] = observed_at
        result["suppressed_destination"] = previous.get("name")
    if current and changed_port:
        result["arrived_at"] = observed_at
        result["suppressed_destination"] = None
    result.update(status="arrived" if current else "underway", current_port=current,
                  position_timestamp=observed_at)
    return result


def vessel_voyage_state(vessel, *, geofences=None):
    """Bootstrap an existing fleet's current fix without writes or history scans."""
    return advance_voyage(getattr(vessel, "voyage_state", {}),
                          latitude=vessel.last_latitude, longitude=vessel.last_longitude,
                          timestamp=vessel.last_seen, geofences=geofences)


def _port_name(value):
    return re.sub(r"[^A-Z0-9]", "", value.upper()) if isinstance(value, str) else ""


def destination_observation_is_newer(vessel, timestamp):
    """Order declarations independently of unrelated static fields and positions.

    Before this timestamp existed, imports did not record a declaration time.
    Preserve their existing destination against older messages by conservatively
    using the latest known observation until the first newer declaration arrives.
    """
    moment = _timestamp(timestamp)
    latest = _timestamp(getattr(vessel, "destination_seen_at", None))
    if latest is None:
        observed = [_timestamp(getattr(vessel, field, None)) for field in ("last_seen", "last_static_seen")]
        latest = max((value for value in observed if value is not None), default=None)
    return moment is not None and (latest is None or moment > latest)


def accept_destination_change(state, *, previous_destination, destination, timestamp):
    """Record a changed accepted target without moving the vessel.

    Repeating the departure port does not prove a return trip. A change such as
    BONGA -> AVEON after departure does, and remains valid on subsequent repeats.
    Call only after the declaration has passed its independent timestamp guard.
    """
    result = deepcopy(state) if isinstance(state, dict) else {}
    moment = _timestamp(timestamp)
    departed_at = _timestamp(result.get("departed_at"))
    if not _suppressed_destination(result) or moment is None or departed_at is None or moment < departed_at:
        return result
    if _port_name(destination) and _port_name(destination) != _port_name(previous_destination):
        result["suppressed_destination"] = None
    return result


def _shuttle_route(vessel, ports):
    routes = getattr(settings, "AIS_VESSEL_SHUTTLE_ROUTES", {})
    if not isinstance(routes, dict):
        return []
    identifiers = routes.get(str(getattr(vessel, "mmsi", "")))
    if not isinstance(identifiers, (list, tuple)) or len(identifiers) != 2:
        return []
    if not all(isinstance(identifier, str) for identifier in identifiers) or identifiers[0] == identifiers[1]:
        return []
    sites = {port["id"]: port for port in ports}
    if not all(identifier in sites for identifier in identifiers):
        return []
    return [sites[identifier] for identifier in identifiers]


def _opposite_port(port, route):
    identifier = port.get("id") if isinstance(port, dict) else None
    for index, endpoint in enumerate(route):
        if endpoint["id"] == identifier:
            return route[1 - index]
    return None


def voyage_payload(vessel, *, geofences=None):
    """Pure display projection: location and raw destination remain separate facts."""
    ports = configured_geofences(geofences)
    result = vessel_voyage_state(vessel, geofences=ports)
    route = _shuttle_route(vessel, ports)
    destination = result["current_port"]
    destination_source = "arrival" if destination else None
    next_destination = _opposite_port(destination, route) if destination and route else None
    declared = vessel.destination.strip() if isinstance(vessel.destination, str) else ""
    if destination is None and route:
        # A configured shuttle reverses only through its observed port calls.
        # The fallback supplies its planned target, never an invented origin.
        destination = _opposite_port(result["origin"], route) or route[1]
        destination_source = "scheduled_route"
    elif destination is None and declared:
        # After leaving a port, its unchanged AIS declaration is not a new trip.
        suppressed = result["suppressed_destination"]
        if not suppressed or _port_name(declared) != _port_name(suppressed):
            destination = next((port for port in ports if _port_name(port["name"]) == _port_name(declared)),
                               {"name": declared})
            destination_source = "ais_declared"
    result.pop("suppressed_destination", None)
    result["destination"] = deepcopy(destination)
    result["destination_source"] = destination_source
    result["next_destination"] = deepcopy(next_destination)
    result["route_ports"] = route
    result["geofences"] = ports
    return result
