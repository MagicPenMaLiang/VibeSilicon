"""Warning census is content-bound, sanitized and non-blocking on drift."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.quality_gate.rtl_manifest import ManifestError
from scripts.quality_gate.rtl_project_lint import _warning_headers
from scripts.quality_gate.rtl_warning_shadow import compare_snapshot, snapshot


class RtlWarningShadowTests(unittest.TestCase):
    def test_parses_only_bounded_warning_headers(self):
        stderr = (
            "%Warning-IMPLICIT: project/demo/rtl\\top.v:3:2: source excerpt\n"
            "   3 | assign x = y;\n"
            "%Warning-UNDRIVEN: project/demo/rtl/top.v:5:1: more text\n"
        )
        result = _warning_headers(stderr, {"project/demo/rtl/top.v"})
        self.assertEqual([item["code"] for item in result], ["IMPLICIT", "UNDRIVEN"])
        self.assertNotIn("source excerpt", str(result))
        with self.assertRaisesRegex(ManifestError, "outside manifest"):
            _warning_headers("%Warning-IMPLICIT: project/other.v:2:1: text", {"project/demo/rtl/top.v"})
        with self.assertRaisesRegex(ManifestError, "unrecognized"):
            _warning_headers("%Warning-IMPLICIT: unexpected format", {"project/demo/rtl/top.v"})

    def test_snapshot_and_drift_stay_shadow(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rtl = root / "project/demo/rtl"
            rtl.mkdir(parents=True)
            source = "project/demo/rtl/top.v"
            (root / source).write_text("module top; endmodule\n", encoding="utf-8")
            manifest = root / "project/demo/manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 1, "project_root": "project/demo", "target": "fpga",
                "source_kinds": ["handwritten"], "top": "top", "source_roots": ["project/demo/rtl"],
                "sources": [source], "headers": [], "include_dirs": ["project/demo/rtl"],
                "defines": {}, "parameters": {}, "clocks": [], "resets": [],
            }), encoding="utf-8")
            mock_report = {
                "status": "PASS", "manifest_sha256": "a" * 64,
                "source_sha256": {source: "b" * 64},
                "tool": {"version": "Verilator 5.048"},
                "warning_headers": [{"code": "IMPLICIT", "source": source, "line": 2, "column": 1}],
            }
            baseline_path = root / "project/demo/warnings.json"
            with patch("scripts.quality_gate.rtl_warning_shadow.run_lint", return_value=mock_report):
                expected = snapshot(manifest, repository_root=root)
                baseline_path.write_text(json.dumps(expected), encoding="utf-8")
                match = compare_snapshot(manifest, "project/demo/warnings.json", repository_root=root)
                self.assertEqual(match["status"], "SHADOW_MATCH")
                expected["warning_count"] = 2
                baseline_path.write_text(json.dumps(expected), encoding="utf-8")
                drift = compare_snapshot(manifest, "project/demo/warnings.json", repository_root=root)
                self.assertEqual(drift["status"], "SHADOW_DRIFT")
                self.assertEqual(drift["warning_count"], 1)

                (root / source).write_bytes(b"module top; endmodule\r\n")
                normalized = snapshot(manifest, repository_root=root)
                self.assertEqual(normalized["source_set_sha256"], expected["source_set_sha256"])


if __name__ == "__main__":
    unittest.main()
