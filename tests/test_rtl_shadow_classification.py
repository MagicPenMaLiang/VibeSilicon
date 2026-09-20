"""Legacy source roles are complete, content-bound, and never a PASS."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.quality_gate.rtl_manifest import ManifestError
from scripts.quality_gate.rtl_shadow_baseline import scan_shadow
from scripts.quality_gate.rtl_shadow_classification import classify_shadow


class RtlShadowClassificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "project/example/rtl"
        self.directory.mkdir(parents=True)
        self.source = "project/example/rtl/top.v"
        (self.root / self.source).write_text("module top; endmodule\n", encoding="utf-8")
        self.inventory_path = "project/example/classification.json"
        self.inventory = {
            "schema_version": 1,
            "project_root": "project/example",
            "source_root": "project/example/rtl",
            "source_set_sha256": scan_shadow("project/example", "project/example/rtl", repository_root=self.root)["source_set_sha256"],
            "groups": {"design_candidate": [self.source], "testbench": [], "archive": []},
        }

    def classify(self):
        (self.root / self.inventory_path).write_text(json.dumps(self.inventory), encoding="utf-8")
        return classify_shadow(self.inventory_path, repository_root=self.root)

    def test_valid_inventory_is_shadow_not_pass(self):
        result = self.classify()
        self.assertEqual(result["status"], "CLASSIFIED_SHADOW")
        self.assertEqual(result["role_counts"], {"archive": 0, "design_candidate": 1, "testbench": 0})
        self.assertNotIn(str(self.root), str(result))

    def test_missing_duplicate_and_unexpected_sources_block(self):
        self.inventory["groups"]["design_candidate"] = []
        with self.assertRaisesRegex(ManifestError, "missing or unexpected"):
            self.classify()
        self.inventory["groups"]["design_candidate"] = [self.source]
        self.inventory["groups"]["testbench"] = [self.source]
        with self.assertRaisesRegex(ManifestError, "duplicate"):
            self.classify()
        self.inventory["groups"]["testbench"] = []
        (self.directory / "new.v").write_text("module new; endmodule\n", encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "missing or unexpected"):
            self.classify()

    def test_source_change_and_bad_role_block(self):
        (self.root / self.source).write_text("module changed; endmodule\n", encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "hash drift"):
            self.classify()
        self.inventory["groups"]["unreviewed"] = []
        with self.assertRaisesRegex(ManifestError, "reviewed roles"):
            self.classify()


if __name__ == "__main__":
    unittest.main()
