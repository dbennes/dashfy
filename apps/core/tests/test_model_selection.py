import os
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.core import model_selection as selection


class ModelSelectionTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "source.glb"
        self.cache = Path(self.directory.name) / "selections"
        self.nodes = [
            {"translation": [10, 2, 3], "children": [1, 2]},
            {"name": "First", "scale": [2, 3, 4], "mesh": 0},
            {"name": "Second", "translation": [0, 7, 0], "mesh": 0},
            {"name": "Unrelated", "translation": [100, 0, 0], "mesh": 0},
        ]
        self.gltf = {
            "asset": {"version": "2.0"},
            "nodes": self.nodes,
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
            "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}],
            "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}],
            "buffers": [{"byteLength": 36}],
        }
        self.binary = bytearray(struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0))
        selection._write_glb(self.source, self.gltf, self.binary)
        for name, value in (("MODEL_PATH", self.source), ("CACHE_DIR", self.cache), ("_SOURCE_INDEX", None)):
            patcher = patch.object(selection, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_cold_lines_share_header_and_keep_exact_transforms_and_vertices(self):
        expected = selection._world_matrices(self.nodes)
        with patch.object(selection, "_read_gltf_header", wraps=selection._read_gltf_header) as read:
            first = selection.selection_glb_path(1)
            second = selection.selection_glb_path(2)
            self.assertEqual(read.call_count, 1)
        for node_id, path in ((1, first), (2, second)):
            gltf, start = selection._read_gltf_header(path)
            self.assertEqual(gltf["nodes"][0]["matrix"], expected[node_id])
            with path.open("rb") as stream:
                stream.seek(start)
                self.assertEqual(stream.read(), self.binary)
        self.assertNotIn(3, selection._SOURCE_INDEX.matrices)

    def test_warm_selection_reads_no_source_header(self):
        path = selection.selection_glb_path(1)
        with patch.object(selection, "_read_gltf_header") as read:
            self.assertEqual(selection.selection_glb_path(1), path)
        read.assert_not_called()

    def test_replaced_source_invalidates_header_transforms_and_selection(self):
        selection.selection_glb_path(1)
        old_index = selection._SOURCE_INDEX
        self.nodes[0]["translation"] = [20, 2, 3]
        selection._write_glb(self.source, self.gltf, self.binary)
        # Ensure the changed model is newer even on coarse filesystem clocks.
        newer = max(self.source.stat().st_mtime_ns, (self.cache / "node-1.glb").stat().st_mtime_ns) + 1_000_000_000
        os.utime(self.source, ns=(newer, newer))
        path = selection.selection_glb_path(1)
        gltf, _ = selection._read_gltf_header(path)
        self.assertIsNot(selection._SOURCE_INDEX, old_index)
        self.assertEqual(gltf["nodes"][0]["matrix"][12:15], [20, 2, 3])

    def test_concurrent_requests_generate_the_same_selection_once(self):
        with patch.object(selection, "_write_glb", wraps=selection._write_glb) as write:
            with ThreadPoolExecutor(max_workers=4) as workers:
                paths = list(workers.map(selection.selection_glb_path, [1] * 8))
        self.assertEqual(len(set(paths)), 1)
        self.assertEqual(write.call_count, 1)
        gltf, _ = selection._read_gltf_header(paths[0])
        self.assertEqual(gltf["nodes"][0]["name"], "First")

    def test_failed_atomic_replace_preserves_previous_file_and_cleans_temporary(self):
        previous = self.source.read_bytes()
        with patch.object(selection.os, "replace", side_effect=OSError("Cannot replace")):
            with self.assertRaises(OSError):
                selection._write_glb(self.source, self.gltf, self.binary)
        self.assertEqual(self.source.read_bytes(), previous)
        self.assertEqual(list(self.source.parent.glob("*.tmp")), [])

    def test_selection_limits_and_invalid_nodes_are_unchanged(self):
        for node_id in (-1, 50):
            with self.assertRaises(ValueError):
                selection.selection_glb_path(node_id)
        with patch.object(selection, "MAX_SELECTION_MESHES", 1):
            with self.assertRaises(selection.SelectionTooLarge):
                selection.selection_glb_path(0)
