"""G0 RTL manifest completeness and path-safety controls."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from unittest.mock import patch

from scripts.quality_gate.rtl_manifest import ManifestError, _bounded_path, validate_manifest


class RtlManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rtl = self.root / "project" / "demo" / "rtl"
        self.rtl.mkdir(parents=True)
        (self.rtl / "top.sv").write_text("module top; child u_child(); endmodule\n", encoding="utf-8")
        (self.rtl / "child.sv").write_text("module child; endmodule\n", encoding="utf-8")
        (self.rtl / "defs.svh").write_text("`define WIDTH 8\n", encoding="utf-8")
        self.manifest = self.root / "project" / "demo" / "rtl_project_manifest.json"
        self.data = {
            "schema_version": 1,
            "project_root": "project/demo",
            "target": "fpga",
            "source_kinds": ["handwritten"],
            "top": "top",
            "source_roots": ["project/demo/rtl"],
            "sources": ["project/demo/rtl/top.sv", "project/demo/rtl/child.sv"],
            "headers": ["project/demo/rtl/defs.svh"],
            "include_dirs": ["project/demo/rtl"],
            "defines": {"DEMO": "1"},
            "parameters": {"WIDTH": "8"},
            "clocks": [],
            "resets": [],
        }

    def check(self):
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")
        return validate_manifest(self.manifest, repository_root=self.root)

    def test_complete_multifile_inventory_passes(self):
        self.assertEqual(self.check()["top"], "top")

    def test_repository_alias_keeps_manifest_containment(self):
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")
        alias = self.root.parent / (self.root.name + "-alias")
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory aliases are unavailable on this host")
        self.addCleanup(alias.unlink)
        result = validate_manifest(
            alias / "project/demo/rtl_project_manifest.json", repository_root=alias
        )
        self.assertEqual(result["top"], "top")

    def test_omitted_dependency_and_header_block(self):
        self.data["sources"].remove("project/demo/rtl/child.sv")
        with self.assertRaisesRegex(ManifestError, "omitted"):
            self.check()
        self.data["sources"].append("project/demo/rtl/child.sv")
        self.data["headers"] = []
        with self.assertRaisesRegex(ManifestError, "omitted"):
            self.check()

    def test_source_outside_roots_blocks(self):
        self.data["source_roots"] = ["project/demo/rtl/top.sv"]
        with self.assertRaises(ManifestError):
            self.check()
        self.data["source_roots"] = ["project/demo"]
        (self.root / "project" / "demo" / "unlisted.v").write_text("module stray; endmodule\n", encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "omitted"):
            self.check()

    def test_traversal_and_absolute_paths_block(self):
        for bad in ("../outside.sv", "C:" + "/outside.sv", "project/demo/../other.sv"):
            with self.subTest(bad=bad):
                self.data["sources"][0] = bad
                with self.assertRaises(ManifestError):
                    self.check()

    def test_bad_shape_and_duplicate_source_block(self):
        self.data["schema_version"] = True
        with self.assertRaises(ManifestError):
            self.check()
        self.data["schema_version"] = 1
        self.data["sources"].append(self.data["sources"][0])
        with self.assertRaisesRegex(ManifestError, "duplicate"):
            self.check()

    def test_symlinked_file_blocks(self):
        link = self.rtl / "linked.sv"
        try:
            link.symlink_to(self.rtl / "child.sv")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable on this host")
        with self.assertRaisesRegex(ManifestError, "linked"):
            self.check()

    def test_injected_link_metadata_blocks_without_link_privilege(self):
        calls = 0

        def is_link(_metadata):
            nonlocal calls
            calls += 1
            return calls == 4  # project/demo/rtl/child.sv

        with patch("scripts.quality_gate.rtl_manifest._is_link", side_effect=is_link):
            with self.assertRaisesRegex(ManifestError, "linked sources"):
                _bounded_path(self.root, "project/demo/rtl/child.sv", kind="sources")
        self.assertEqual(calls, 4)

    def test_external_manifest_blocks(self):
        outside = self.root.parent / "outside-rtl-manifest.json"
        with self.assertRaisesRegex(ManifestError, "inside repository"):
            validate_manifest(outside, repository_root=self.root)

    def test_schema_is_available_and_explicit(self):
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "schemas/rtl_project_manifest.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(self.data))

    def test_v2_explicit_variant_exclusions_preserve_complete_inventory(self):
        self.data["schema_version"] = 2
        self.data["sources"].remove("project/demo/rtl/child.sv")
        self.data["excluded_sources"] = {"project/demo/rtl/child.sv": "mutually_exclusive_variant"}
        self.assertEqual(self.check()["excluded_sources"], self.data["excluded_sources"])
        (self.rtl / "new.sv").write_text("module new; endmodule\n", encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "omitted"):
            self.check()
        (self.rtl / "new.sv").unlink()
        self.data["sources"].append("project/demo/rtl/child.sv")
        with self.assertRaisesRegex(ManifestError, "compiled and excluded"):
            self.check()

    def test_v2_bad_exclusion_reason_or_shape_blocks(self):
        self.data["schema_version"] = 2
        self.data["excluded_sources"] = {"project/demo/rtl/child.sv": "unreviewed"}
        with self.assertRaisesRegex(ManifestError, "invalid excluded"):
            self.check()
        self.data["excluded_sources"] = {"project/demo/rtl/child.sv": []}
        with self.assertRaisesRegex(ManifestError, "invalid excluded"):
            self.check()
        self.data.pop("excluded_sources")
        with self.assertRaisesRegex(ManifestError, "shape or version"):
            self.check()

    def test_v2_schema_requires_explicit_exclusions(self):
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "schemas/rtl_project_manifest_v2.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], 2)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(self.data) | {"excluded_sources"})


if __name__ == "__main__":
    unittest.main()
