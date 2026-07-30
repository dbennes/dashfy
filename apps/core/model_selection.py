from __future__ import annotations

import json
import struct
from pathlib import Path

from django.conf import settings


MODEL_PATH = Path(settings.BASE_DIR) / "static" / "models" / "bonga-2.glb"
CACHE_DIR = Path(settings.BASE_DIR) / "static" / "models" / "selection-cache"
MAX_SELECTION_MESHES = 500


class SelectionTooLarge(ValueError):
    pass


def _align4(data: bytearray) -> None:
    while len(data) % 4:
        data.append(0)


def _read_gltf_header(path: Path) -> tuple[dict, int]:
    with path.open("rb") as fh:
        magic, version, _length = struct.unpack("<4sII", fh.read(12))
        if magic != b"glTF" or version != 2:
            raise ValueError("Arquivo nao e GLB 2.0")
        json_length, json_type = struct.unpack("<I4s", fh.read(8))
        if json_type != b"JSON":
            raise ValueError("Chunk JSON nao encontrado no GLB")
        gltf = json.loads(fh.read(json_length).decode("utf-8"))
        bin_length, bin_type = struct.unpack("<I4s", fh.read(8))
        if bin_type != b"BIN\x00" or bin_length <= 0:
            raise ValueError("Chunk BIN nao encontrado no GLB")
        return gltf, fh.tell()


def _mat_mul(a: list[float], b: list[float]) -> list[float]:
    result = [0.0] * 16
    for col in range(4):
        for row in range(4):
            result[col * 4 + row] = sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
    return result


def _local_matrix(node: dict) -> list[float]:
    if "matrix" in node:
        return [float(value) for value in node["matrix"]]

    translation = node.get("translation", [0, 0, 0])
    scale = node.get("scale", [1, 1, 1])
    rotation = node.get("rotation", [0, 0, 0, 1])
    x, y, z, w = (float(rotation[0]), float(rotation[1]), float(rotation[2]), float(rotation[3]))
    sx, sy, sz = (float(scale[0]), float(scale[1]), float(scale[2]))
    x2, y2, z2 = x + x, y + y, z + z
    xx, xy, xz = x * x2, x * y2, x * z2
    yy, yz, zz = y * y2, y * z2, z * z2
    wx, wy, wz = w * x2, w * y2, w * z2

    return [
        (1 - (yy + zz)) * sx,
        (xy + wz) * sx,
        (xz - wy) * sx,
        0,
        (xy - wz) * sy,
        (1 - (xx + zz)) * sy,
        (yz + wx) * sy,
        0,
        (xz + wy) * sz,
        (yz - wx) * sz,
        (1 - (xx + yy)) * sz,
        0,
        float(translation[0]),
        float(translation[1]),
        float(translation[2]),
        1,
    ]


def _world_matrices(nodes: list[dict]) -> list[list[float] | None]:
    parents = [-1] * len(nodes)
    for index, node in enumerate(nodes):
        for child in node.get("children", []):
            if 0 <= child < len(nodes):
                parents[child] = index
    roots = [index for index, parent in enumerate(parents) if parent < 0]
    identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    matrices: list[list[float] | None] = [None] * len(nodes)
    stack = [(root, identity) for root in roots]
    while stack:
        index, parent_matrix = stack.pop()
        if index >= len(nodes):
            continue
        matrix = _mat_mul(parent_matrix, _local_matrix(nodes[index]))
        matrices[index] = matrix
        for child in reversed(nodes[index].get("children", [])):
            stack.append((child, matrix))
    return matrices


def _descendants(nodes: list[dict], node_id: int) -> list[int]:
    selected: list[int] = []
    stack = [node_id]
    seen = set()
    while stack:
        index = stack.pop()
        if index in seen or index < 0 or index >= len(nodes):
            continue
        seen.add(index)
        selected.append(index)
        stack.extend(reversed(nodes[index].get("children", [])))
    return selected


def _copy_accessor(
    *,
    source: Path,
    bin_start: int,
    gltf: dict,
    accessor_index: int,
    bin_out: bytearray,
    accessors_out: list[dict],
    buffer_views_out: list[dict],
    target: int,
) -> int:
    accessor = gltf["accessors"][accessor_index]
    buffer_view = gltf["bufferViews"][accessor["bufferView"]]
    offset = int(buffer_view.get("byteOffset", 0))
    length = int(buffer_view["byteLength"])

    _align4(bin_out)
    new_offset = len(bin_out)
    with source.open("rb") as fh:
        fh.seek(bin_start + offset)
        bin_out.extend(fh.read(length))

    new_view = {
        "buffer": 0,
        "byteOffset": new_offset,
        "byteLength": length,
        "target": target,
    }
    if "byteStride" in buffer_view:
        new_view["byteStride"] = buffer_view["byteStride"]
    buffer_views_out.append(new_view)

    new_accessor = {
        "bufferView": len(buffer_views_out) - 1,
        "componentType": accessor["componentType"],
        "count": accessor["count"],
        "type": accessor["type"],
    }
    if "byteOffset" in accessor:
        new_accessor["byteOffset"] = accessor["byteOffset"]
    if "normalized" in accessor:
        new_accessor["normalized"] = accessor["normalized"]
    if "min" in accessor:
        new_accessor["min"] = accessor["min"]
    if "max" in accessor:
        new_accessor["max"] = accessor["max"]
    accessors_out.append(new_accessor)
    return len(accessors_out) - 1


def _write_glb(path: Path, gltf: dict, bin_chunk: bytearray) -> None:
    _align4(bin_chunk)
    json_bytes = json.dumps(gltf, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    while len(json_bytes) % 4:
        json_bytes += b" "
    total_length = 12 + 8 + len(json_bytes) + 8 + len(bin_chunk)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(struct.pack("<4sII", b"glTF", 2, total_length))
        fh.write(struct.pack("<I4s", len(json_bytes), b"JSON"))
        fh.write(json_bytes)
        fh.write(struct.pack("<I4s", len(bin_chunk), b"BIN\x00"))
        fh.write(bin_chunk)


def selection_glb_path(node_id: int) -> Path:
    if node_id < 0:
        raise ValueError("Node invalido")

    source = MODEL_PATH
    if not source.exists():
        raise FileNotFoundError(source)

    cache = CACHE_DIR / f"node-{node_id}.glb"
    if cache.exists() and cache.stat().st_mtime >= source.stat().st_mtime:
        return cache

    gltf, bin_start = _read_gltf_header(source)
    nodes = gltf.get("nodes", [])
    meshes = gltf.get("meshes", [])
    if node_id >= len(nodes):
        raise ValueError("Node nao existe no GLB")

    selected_nodes = [
        index for index in _descendants(nodes, node_id)
        if "mesh" in nodes[index] and nodes[index]["mesh"] < len(meshes)
    ]
    if not selected_nodes:
        raise ValueError("Node sem geometria selecionavel")
    if len(selected_nodes) > MAX_SELECTION_MESHES:
        raise SelectionTooLarge(f"Selecao com {len(selected_nodes)} meshes; limite {MAX_SELECTION_MESHES}")

    world = _world_matrices(nodes)
    bin_out = bytearray()
    accessors_out: list[dict] = []
    buffer_views_out: list[dict] = []
    meshes_out: list[dict] = []
    nodes_out: list[dict] = []

    for index in selected_nodes:
        node = nodes[index]
        mesh = meshes[node["mesh"]]
        primitives_out = []
        for primitive in mesh.get("primitives", []):
            position = primitive.get("attributes", {}).get("POSITION")
            if position is None:
                continue
            new_position = _copy_accessor(
                source=source,
                bin_start=bin_start,
                gltf=gltf,
                accessor_index=position,
                bin_out=bin_out,
                accessors_out=accessors_out,
                buffer_views_out=buffer_views_out,
                target=34962,
            )
            primitive_out = {
                "attributes": {"POSITION": new_position},
                "mode": primitive.get("mode", 4),
                "material": 0,
            }
            if "indices" in primitive:
                primitive_out["indices"] = _copy_accessor(
                    source=source,
                    bin_start=bin_start,
                    gltf=gltf,
                    accessor_index=primitive["indices"],
                    bin_out=bin_out,
                    accessors_out=accessors_out,
                    buffer_views_out=buffer_views_out,
                    target=34963,
                )
            primitives_out.append(primitive_out)
        if not primitives_out:
            continue
        meshes_out.append({"name": mesh.get("name", node.get("name", f"Node {index}")), "primitives": primitives_out})
        nodes_out.append({
            "name": node.get("name", f"Node {index}"),
            "mesh": len(meshes_out) - 1,
            "matrix": [round(float(value), 8) for value in (world[index] or _local_matrix(node))],
        })

    if not nodes_out:
        raise ValueError("Node sem primitivas selecionaveis")

    out_gltf = {
        "asset": {"version": "2.0", "generator": "DASHFY selection extractor"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes_out)))}],
        "nodes": nodes_out,
        "meshes": meshes_out,
        "materials": [{
            "name": "selection-red",
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.86, 0.05, 0.05, 0.72],
                "metallicFactor": 0,
                "roughnessFactor": 0.45,
            },
            "alphaMode": "BLEND",
            "doubleSided": True,
        }],
        "buffers": [{"byteLength": len(bin_out)}],
        "bufferViews": buffer_views_out,
        "accessors": accessors_out,
    }
    _write_glb(cache, out_gltf, bin_out)
    return cache
