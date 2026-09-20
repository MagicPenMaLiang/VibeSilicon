"""Unified RTL evidence is deterministic, bounded and safe for annotations."""

import copy
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts.quality_gate import rtl_gate_evidence


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "project/demo/rtl/demo.sv"
SHA = "sha256:" + "a" * 64


def fixture(*, warning_count=0):
    manifest = {
        "target": "fpga", "top": "demo", "sources": [SOURCE], "headers": [],
    }
    lint = {
        "source_sha256": {SOURCE: "b" * 64},
        "tool": {"name": "verilator", "version": "Verilator 5.048"},
        "returncode": 0,
        "warning_headers": [
            {"code": "WIDTH", "source": SOURCE, "line": number + 1, "column": 2}
            for number in range(warning_count)
        ],
    }
    smoke = {
        "evidence_id": "sha256:" + "c" * 64,
        "execution": {"compile": "PASS", "run": "PASS", "pass_token_count": 1},
    }
    return rtl_gate_evidence.build_bundle(
        manifest_path="project/demo/rtl_project_manifest.json", manifest=manifest,
        manifest_sha256=SHA, waiver_sha256="sha256:" + "d" * 64,
        waiver_result={"sources_checked": 1, "waivers_checked": 0},
        lint_report=lint, smoke_report=smoke,
        checks={"g0": "PASS", "g1": "PASS", "g2": "PASS"}, status="PASS",
    )


class RtlGateEvidenceTests(unittest.TestCase):
    def test_pass_bundle_is_ordered_content_addressed_and_schema_backed(self):
        first = fixture()
        second = fixture()
        self.assertEqual(first, second)
        self.assertEqual([stage["gate"] for stage in first["stages"]], ["G0", "G1", "G2"])
        self.assertTrue(all(stage["evidence_id"].startswith("sha256:") for stage in first["stages"]))
        self.assertEqual(rtl_gate_evidence.verify_bundle(first, allowed_sources={SOURCE}), first)
        schema = json.loads((ROOT / "schemas/rtl_gate_evidence.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(first), set(schema["required"]))
        self.assertEqual(schema["properties"]["evidence_kind"]["const"], "RTL_GATE_BUNDLE")

    def test_annotations_are_bounded_relative_and_do_not_expose_rtl(self):
        bundle = fixture(warning_count=25)
        self.assertEqual(bundle["annotation_count"], 20)
        self.assertEqual(bundle["annotations_truncated"], 5)
        self.assertEqual(bundle["stages"][1]["finding_count"], 25)
        output = io.StringIO()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            with redirect_stdout(output):
                rtl_gate_evidence.emit_github_annotations(bundle)
        rendered = output.getvalue()
        self.assertEqual(rendered.count("::warning file="), 20)
        self.assertIn(f"file={SOURCE},line=1,col=2", rendered)
        self.assertIn("VERILATOR_WARNING; review unified RTL evidence", rendered)
        self.assertNotIn("module demo", rendered)
        self.assertNotIn(str(ROOT), rendered)

    def test_stage_bundle_and_status_tamper_are_rejected(self):
        original = fixture()
        changed = copy.deepcopy(original)
        changed["stages"][1]["metrics"]["tool"]["version"] = "Verilator 5.999"
        with self.assertRaisesRegex(rtl_gate_evidence.GateEvidenceError, "stage content ID mismatch"):
            rtl_gate_evidence.verify_bundle(changed, allowed_sources={SOURCE})
        changed = copy.deepcopy(original)
        changed["status"] = "FAIL"
        changed["evidence_id"] = rtl_gate_evidence._content_id(changed)
        with self.assertRaisesRegex(rtl_gate_evidence.GateEvidenceError, "status mismatch"):
            rtl_gate_evidence.verify_bundle(changed, allowed_sources={SOURCE})

    def test_unsafe_or_nonmanifest_annotation_is_rejected(self):
        changed = fixture(warning_count=1)
        annotation = changed["stages"][1]["annotations"][0]
        annotation["file"] = "project/other/secret.sv"
        changed["stages"][1]["evidence_id"] = rtl_gate_evidence._content_id(changed["stages"][1])
        changed["evidence_id"] = rtl_gate_evidence._content_id(changed)
        with self.assertRaisesRegex(rtl_gate_evidence.GateEvidenceError, "unsafe"):
            rtl_gate_evidence.verify_bundle(changed, allowed_sources={SOURCE})

    def test_cross_stage_identity_and_annotation_semantics_are_rejected(self):
        changed = fixture(warning_count=1)
        changed["project"]["manifest_sha256"] = "sha256:" + "e" * 64
        changed["evidence_id"] = rtl_gate_evidence._content_id(changed)
        with self.assertRaisesRegex(rtl_gate_evidence.GateEvidenceError, "manifest hashes differ"):
            rtl_gate_evidence.verify_bundle(changed, allowed_sources={SOURCE})

        changed = fixture(warning_count=1)
        annotation = changed["stages"][1]["annotations"][0]
        annotation["message_code"] = "GENERIC_WARNING"
        changed["stages"][1]["evidence_id"] = rtl_gate_evidence._content_id(changed["stages"][1])
        changed["evidence_id"] = rtl_gate_evidence._content_id(changed)
        with self.assertRaisesRegex(rtl_gate_evidence.GateEvidenceError, "unsafe"):
            rtl_gate_evidence.verify_bundle(changed, allowed_sources={SOURCE})


if __name__ == "__main__":
    unittest.main()
