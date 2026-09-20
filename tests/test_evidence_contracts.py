import copy
import json
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT, load_module


evidence = load_module("vibesilicon_evidence_contract", "scripts/evidence_contract.py")


class EvidenceContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)
        self.artifacts = [
            ("specs/counter.md", "spec"),
            ("rtl/counter.sv", "source"),
            ("constraints/counter.sdc", "constraints"),
            ("reports/timing.rpt", "timing_report"),
            ("reports/cdc.rpt", "cdc_report"),
            ("reports/utilization.rpt", "utilization_report"),
        ]
        for relative, kind in self.artifacts:
            path = self.project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"synthetic {kind} evidence\n", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def build_example_manifest(self):
        return evidence.build_manifest(
            project="counter-example",
            task_id="example-signoff",
            root=self.project,
            artifacts=self.artifacts,
            created_at="2026-08-27T06:00:00Z",
            source_commit="58e134a",
            reproduce_commands=[
                "python scripts/quality_gate/rtl_project_gate.py examples/rtl/counter/rtl_project_manifest.json"
            ],
            environment={"vivado": "2024.2", "python": "3.10-3.12"},
        )

    def test_synthetic_artifacts_build_a_valid_manifest(self):
        manifest = self.build_example_manifest()
        evidence.validate_manifest(manifest)
        self.assertEqual(len(manifest["artifacts"]), len(self.artifacts))
        self.assertTrue(manifest["manifest_id"].startswith("sha256:"))

    def test_manifest_id_is_deterministic(self):
        self.assertEqual(
            self.build_example_manifest()["manifest_id"],
            self.build_example_manifest()["manifest_id"],
        )

    def test_timing_receipt_references_manifest_artifact(self):
        manifest = self.build_example_manifest()
        timing = next(item for item in manifest["artifacts"] if item["kind"] == "timing_report")
        receipt = evidence.build_receipt(
            task_id="example-signoff-timing",
            tool={"name": "vivado", "version": "2024.2", "backend": "native"},
            inputs={
                "rtl_tree_hash": next(
                    item["sha256"] for item in manifest["artifacts"] if item["kind"] == "source"
                ),
                "spec_hash": next(
                    item["sha256"] for item in manifest["artifacts"] if item["kind"] == "spec"
                ),
            },
            command_argv=["vivado", "-mode", "batch", "-source", "vivado_full_impl.tcl"],
            command_cwd="examples/rtl/counter",
            started_at="2026-08-27T06:00:00Z",
            duration_s=12.5,
            status="PASS",
            metrics={"wns_ns": 13.22, "constraints_met": True},
            artifacts=[timing],
            parser={"name": "timing-summary", "schema_version": 1},
            provenance={"agent": "reviewer-fpga", "prompt_version": "p1-v1"},
        )
        evidence.validate_receipt(receipt)
        self.assertEqual(receipt["artifacts"][0]["artifact_id"], timing["artifact_id"])

    def test_tampered_receipt_is_rejected(self):
        manifest = self.build_example_manifest()
        timing = next(item for item in manifest["artifacts"] if item["kind"] == "timing_report")
        receipt = evidence.build_receipt(
            task_id="timing",
            tool={"name": "vivado", "version": "2024.2", "backend": "native"},
            inputs={"rtl_hash": manifest["artifacts"][1]["sha256"]},
            command_argv=["vivado", "-mode", "batch"],
            command_cwd="examples/rtl/counter",
            started_at="2026-08-27T06:00:00Z",
            duration_s=1,
            status="PASS",
            metrics={"wns_ns": 13.22},
            artifacts=[timing],
            parser={"name": "timing-summary", "schema_version": 1},
            provenance={"agent": "reviewer-fpga"},
        )
        tampered = copy.deepcopy(receipt)
        tampered["metrics"]["wns_ns"] = -1
        with self.assertRaises(evidence.EvidenceContractError):
            evidence.validate_receipt(tampered)

    def test_artifact_outside_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir) / "report.rpt"
            outside.write_text("report", encoding="utf-8")
            with self.assertRaises(evidence.EvidenceContractError):
                evidence.artifact_record(outside, Path(root_dir), "timing_report")

    def test_manifest_tamper_is_rejected(self):
        manifest = self.build_example_manifest()
        manifest["artifacts"][0]["path"] = "../outside"
        with self.assertRaises(evidence.EvidenceContractError):
            evidence.validate_manifest(manifest)

    def test_unknown_fields_are_rejected(self):
        manifest = self.build_example_manifest()
        manifest["unreviewed"] = True
        manifest["manifest_id"] = evidence.content_id(manifest, "manifest_id")
        with self.assertRaises(evidence.EvidenceContractError):
            evidence.validate_manifest(manifest)

    def test_json_schemas_are_versioned_and_parseable(self):
        for name in ("artifact_manifest.schema.json", "evidence_receipt.schema.json"):
            schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertIn("schema_version", schema["properties"])


if __name__ == "__main__":
    unittest.main()
