"""Build compact, independently hideable disciplines from the source GLB.

Run with the project's Python and --gltfpack PATH (gltfpack 1.1).
Only authored level-3 groups classify geometry; unrecognised nodes stay in Other.
Original geometry, materials and world transforms are retained before packing.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from apps.core.model_selection import _read_gltf_header, _world_matrices, _write_glb, _align4

CODES = {"ELEC": "electrical", "INST": "instrumentation", "STRU": "structural",
         "WIT": "structural", "FRMW": "structural", "PIPE": "piping",
         "PSUP": "supports", "PUSP": "supports", "EQUI": "equipment",
         "TELE": "telecom", "PAUX": "auxiliary"}


def combine(parts, output):
    """Join already optimised GLBs without undoing material/mesh batching."""
    out = {"asset": {"version": "2.0", "generator": "Dashfy discipline pack"},
           "buffers": [{"byteLength": 0}], "bufferViews": [], "accessors": [],
           "materials": [], "meshes": [], "nodes": [], "scenes": [{"nodes": []}], "scene": 0}
    binary = bytearray()
    for name, path in parts:
        doc, offset = _read_gltf_header(path)
        assert not doc.get("textures") and not doc.get("animations") and not doc.get("skins")
        _align4(binary)
        start = len(binary)
        with path.open("rb") as stream:
            stream.seek(offset)
            binary.extend(stream.read())
        buffers = {0: 0}
        for index, buffer in enumerate(doc["buffers"][1:], 1):
            assert "uri" not in buffer
            buffers[index] = len(out["buffers"])
            out["buffers"].append(buffer)
        view_base, accessor_base = len(out["bufferViews"]), len(out["accessors"])
        material_base, mesh_base, node_base = len(out["materials"]), len(out["meshes"]), len(out["nodes"])
        for view in doc.get("bufferViews", []):
            if view["buffer"] == 0:
                view["byteOffset"] = view.get("byteOffset", 0) + start
            view["buffer"] = buffers[view["buffer"]]
            compressed = view.get("extensions", {}).get("EXT_meshopt_compression")
            if compressed:
                if compressed["buffer"] == 0:
                    compressed["byteOffset"] = compressed.get("byteOffset", 0) + start
                compressed["buffer"] = buffers[compressed["buffer"]]
            out["bufferViews"].append(view)
        for accessor in doc.get("accessors", []):
            assert "sparse" not in accessor
            if "bufferView" in accessor:
                accessor["bufferView"] += view_base
            out["accessors"].append(accessor)
        out["materials"].extend(doc.get("materials", []))
        for mesh in doc["meshes"]:
            for primitive in mesh["primitives"]:
                assert "targets" not in primitive
                primitive["attributes"] = {key: value + accessor_base for key, value in primitive["attributes"].items()}
                if "indices" in primitive:
                    primitive["indices"] += accessor_base
                if "material" in primitive:
                    primitive["material"] += material_base
            out["meshes"].append(mesh)
        for node in doc["nodes"]:
            if "mesh" in node:
                node["mesh"] += mesh_base
            if "children" in node:
                node["children"] = [index + node_base for index in node["children"]]
            out["nodes"].append(node)
        out["scenes"][0]["nodes"].append(len(out["nodes"]))
        out["nodes"].append({"name": f"discipline_{name}",
                             "children": [index + node_base for index in doc["scenes"][doc.get("scene", 0)]["nodes"]]})
        for key in ("extensionsUsed", "extensionsRequired"):
            out[key] = sorted(set(out.get(key, [])) | set(doc.get(key, [])))
    out["buffers"][0]["byteLength"] = len(binary)
    _write_glb(output, out, binary)
    return len(out["nodes"]), sum(len(mesh["primitives"]) for mesh in out["meshes"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gltfpack", required=True)
    args = parser.parse_args()
    folder = ROOT / "static/models"
    source = folder / "bonga-2.glb"
    gltf, offset = _read_gltf_header(source)
    hierarchy = json.loads((folder / "bonga-2-hierarchy.json").read_text())
    rows = {row[0]: row for row in hierarchy["nodes"]}
    membership = {}

    def discipline(index):
        if index not in membership:
            row = rows[index]
            membership[index] = (("piping" if row[3].upper().endswith("-TIE-IN-POINTS") else
                                  CODES.get(row[3].rsplit("-", 1)[-1].upper(), "other"))
                                 if row[2] == 3 else
                                 discipline(row[1]) if row[1] in rows else "other")
        return membership[index]

    matrices = _world_matrices(gltf["nodes"])
    groups = {name: [] for name in dict.fromkeys([*CODES.values(), "other"])}
    new_nodes = []
    for index, node in enumerate(gltf["nodes"]):
        if "mesh" not in node:
            continue
        groups[discipline(index)].append(len(new_nodes))
        new_nodes.append({"mesh": node["mesh"], "matrix": matrices[index]})
    for mesh in gltf["meshes"]:
        mesh.pop("name", None)
    for material in gltf.get("materials", []):
        material.pop("name", None)
    gltf.update(nodes=new_nodes, scene=0)
    intermediate = ROOT / "tmp/discipline-source.glb"
    with source.open("rb") as stream:
        stream.seek(offset)
        binary = bytearray(stream.read())
    print("Source mesh coverage:", {name: len(nodes) for name, nodes in groups.items()}, flush=True)
    parts = {"fast": [], "hq": []}
    for name, children in groups.items():
        if not children:
            continue
        mesh_ids = list(dict.fromkeys(new_nodes[index]["mesh"] for index in children))
        mesh_map = {index: target for target, index in enumerate(mesh_ids)}
        part_doc = dict(gltf, nodes=[dict(new_nodes[index], mesh=mesh_map[new_nodes[index]["mesh"]]) for index in children],
                        meshes=[gltf["meshes"][index] for index in mesh_ids], scenes=[{"nodes": list(range(len(children)))}])
        _write_glb(intermediate, part_doc, binary)
        for quality, ratio in [("fast", "0.25"), ("hq", "1")]:
            part = ROOT / f"tmp/discipline-{name}-{quality}.glb"
            subprocess.run([args.gltfpack, "-i", str(intermediate), "-o", str(part),
                            "-mm", "-cc", "-si", ratio, "-vp", "16"], check=True)
            parts[quality].append((name, part))
        print("Packed", name, flush=True)
    for quality in parts:
        output = folder / f"bonga-2-disciplines-{quality}.glb"
        nodes, draws = combine(parts[quality], output)
        packed, _ = _read_gltf_header(output)
        actual = {node.get("name") for node in packed["nodes"] if node.get("name", "").startswith("discipline_")}
        assert actual == {f"discipline_{name}" for name, nodes in groups.items() if nodes}, actual
        report = {"nodes": nodes, "draws": draws, "bytes": output.stat().st_size,
                  "source_meshes": {name: len(nodes) for name, nodes in groups.items()}}
        (folder / f"bonga-2-disciplines-{quality}-report.json").write_text(json.dumps(report, indent=2))
        print(quality, round(output.stat().st_size / 1048576, 2), "MiB", nodes, "nodes", draws, "draws", flush=True)


if __name__ == "__main__":
    main()
