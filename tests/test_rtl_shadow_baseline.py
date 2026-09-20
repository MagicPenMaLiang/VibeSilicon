"""A legacy shadow scan is bounded, deterministic and never a quality PASS."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.quality_gate.rtl_manifest import ManifestError
from scripts.quality_gate.rtl_shadow_baseline import scan_shadow


class RtlShadowBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "project/example/rtl/top.v"
        self.source.parent.mkdir(parents=True)
        self.source.write_text("module top; endmodule\n", encoding="utf-8")

    def scan(self):
        return scan_shadow("project/example", "project/example/rtl", repository_root=self.root)

    def test_report_is_shadow_and_redacts_source_excerpts(self):
        result = self.scan()
        self.assertEqual(result["status"], "SHADOW")
        self.assertEqual(result["source_count"], 1)
        self.assertGreater(result["summary"]["blocking_candidates"], 0)
        self.assertEqual(result["files"][0]["source"], "project/example/rtl/top.v")
        self.assertNotIn(str(self.root), str(result))
        self.assertNotIn("evidence", str(result))
        self.assertEqual(result, self.scan())

    def test_missing_or_outside_project_source_blocks(self):
        (self.root / "project/other").mkdir(parents=True)
        with self.assertRaisesRegex(ManifestError, "inside project_root"):
            scan_shadow("project/other", "project/example/rtl", repository_root=self.root)
        self.source.unlink()
        with self.assertRaisesRegex(ManifestError, "contains no"):
            self.scan()

    def test_source_mutation_during_scan_blocks(self):
        original = scan_shadow.__globals__["analyze"]

        def mutate(path, *, root):
            result = original(path, root=root)
            path.write_text("module changed; endmodule\n", encoding="utf-8")
            return result

        with patch("scripts.quality_gate.rtl_shadow_baseline.analyze", side_effect=mutate):
            with self.assertRaisesRegex(ManifestError, "changed during shadow scan"):
                self.scan()

    def test_headers_are_hashed_but_not_misreported_as_scanned_rtl(self):
        header = self.source.parent / "defs.vh"
        header.write_text("`define WIDTH 8\n", encoding="utf-8")
        result = self.scan()
        self.assertEqual(result["source_count"], 1)
        self.assertEqual(result["header_count"], 1)
        self.assertEqual(result["headers"][0]["source"], "project/example/rtl/defs.vh")
        self.assertTrue(result["headers"][0]["sha256"].startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
