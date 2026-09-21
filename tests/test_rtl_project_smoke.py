"""Generic G2 smoke never accepts a placeholder or unbound testbench."""

import json
import os
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.quality_gate import rtl_project_smoke
from scripts.quality_gate.rtl_manifest import ManifestError


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("examples/rtl/counter/rtl_project_manifest.json")
CONTRACT = Path("examples/rtl/counter/rtl_simulation_contract.json")


class RtlProjectSmokeTests(unittest.TestCase):
    def test_example_contract_and_template_have_fixed_fields(self):
        schema = json.loads((ROOT / "schemas/rtl_simulation_contract.schema.json").read_text(encoding="utf-8"))
        value = json.loads((ROOT / CONTRACT).read_text(encoding="utf-8"))
        template = json.loads((ROOT / "templates/rtl/simulation_contract.json.template").read_text(encoding="utf-8"))
        self.assertEqual(set(value), set(schema["required"]))
        self.assertEqual(set(template), set(schema["required"]))
        self.assertEqual(value["dut_instance"], "dut")
        self.assertEqual(value["top"], "counter_selfcheck_tb")
        evidence_schema = json.loads((ROOT / "schemas/rtl_project_smoke_evidence.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(evidence_schema["properties"]["gate"]["const"], "G2_PROJECT_RTL_SMOKE")

    def test_pass_is_source_bound_and_requires_one_token(self):
        tool = {"status": "AVAILABLE", "version": "Verilator 5.048", "kind": "DIRECT", "command": ["verilator"]}
        for execution, status in (
            ({"compile": "PASS", "run": "PASS", "pass_token_count": 1}, "PASS"),
            ({"compile": "PASS", "run": "PASS", "pass_token_count": 0}, "FAIL"),
            ({"compile": "PASS", "run": "PASS", "pass_token_count": 2}, "FAIL"),
            ({"compile": "FAIL", "run": "NOT_RUN", "pass_token_count": 0}, "FAIL"),
            ({"compile": "TIMEOUT", "run": "NOT_RUN", "pass_token_count": 0}, "BLOCKED"),
        ):
            with self.subTest(execution=execution):
                with patch.object(rtl_project_smoke, "_tool", return_value=tool):
                    with patch.object(rtl_project_smoke, "_run", return_value=execution):
                        report = rtl_project_smoke.run_project(MANIFEST, CONTRACT, repository_root=ROOT)
                self.assertEqual(report["status"], status)
                self.assertEqual(report["gate"], "G2_PROJECT_RTL_SMOKE")
                self.assertTrue(report["evidence_id"].startswith("sha256:"))
                self.assertEqual(report["evidence_id"], rtl_project_smoke._content_id(report))
                self.assertNotIn(str(ROOT), json.dumps(report))

    def test_missing_tool_and_contract_block(self):
        with patch.object(rtl_project_smoke, "_tool", return_value={
            "status": "MISSING", "version": None, "kind": None, "command": None,
        }):
            report = rtl_project_smoke.run_project(MANIFEST, CONTRACT, repository_root=ROOT)
        self.assertEqual(report["status"], "BLOCKED")
        with self.assertRaisesRegex(ManifestError, "missing simulation contract"):
            rtl_project_smoke.run_project(MANIFEST, Path("examples/rtl/counter/missing.json"), repository_root=ROOT)

    def test_parameterized_project_without_reviewed_adapter_blocks(self):
        manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
        manifest["parameters"] = {"DATA_W": "16"}
        with patch.object(rtl_project_smoke, "validate_manifest", return_value=manifest):
            with self.assertRaisesRegex(ManifestError, "reviewed simulation adapter"):
                rtl_project_smoke.run_project(MANIFEST, CONTRACT, repository_root=ROOT)

    def test_timeout_blocks_instead_of_passing(self):
        tool = {"status": "AVAILABLE", "version": "Verilator 5.048", "kind": "DIRECT", "command": ["verilator"]}
        execution = {"compile": "PASS", "run": "TIMEOUT", "pass_token_count": 0}
        with patch.object(rtl_project_smoke, "_tool", return_value=tool):
            with patch.object(rtl_project_smoke, "_run", return_value=execution):
                report = rtl_project_smoke.run_project(MANIFEST, CONTRACT, repository_root=ROOT)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(rtl_project_smoke.verify_report(report), report)

    def test_evidence_tamper_is_rejected(self):
        tool = {"status": "AVAILABLE", "version": "Verilator 5.048", "kind": "DIRECT", "command": ["verilator"]}
        execution = {"compile": "PASS", "run": "PASS", "pass_token_count": 1}
        with patch.object(rtl_project_smoke, "_tool", return_value=tool):
            with patch.object(rtl_project_smoke, "_run", return_value=execution):
                report = rtl_project_smoke.run_project(MANIFEST, CONTRACT, repository_root=ROOT)
        changed = copy.deepcopy(report)
        changed["execution"]["pass_token_count"] = 0
        with self.assertRaisesRegex(ManifestError, "content ID mismatch"):
            rtl_project_smoke.verify_report(changed)
        changed = copy.deepcopy(report)
        changed["status"] = "FAIL"
        changed["evidence_id"] = rtl_project_smoke._content_id(changed)
        with self.assertRaisesRegex(ManifestError, "status does not match"):
            rtl_project_smoke.verify_report(changed)

    def test_summary_is_bounded_and_summary_write_failure_blocks(self):
        execution = {"compile": "PASS", "run": "PASS", "pass_token_count": 1}
        report = {"status": "PASS", "evidence_id": "sha256:" + "a" * 64, "execution": execution}
        summary = rtl_project_smoke._summary(report)
        self.assertIn(report["evidence_id"], summary)
        self.assertNotIn(str(ROOT), summary)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "summary.md"
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(destination)}):
                with patch.object(rtl_project_smoke, "run_project", return_value=report):
                    self.assertEqual(rtl_project_smoke.main([str(MANIFEST), str(CONTRACT)]), 0)
            self.assertEqual(destination.read_text(encoding="utf-8"), summary)
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(Path(directory) / "missing" / "summary.md")}):
                with patch.object(rtl_project_smoke, "run_project", return_value=report):
                    with patch.object(rtl_project_smoke, "_annotate_failure") as annotate:
                        self.assertEqual(rtl_project_smoke.main([str(MANIFEST), str(CONTRACT)]), 2)
            annotate.assert_called_once_with("BLOCKED")

    def test_testbench_must_instantiate_manifest_top(self):
        manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project" / "demo"
            (project / "rtl").mkdir(parents=True)
            (project / "tests").mkdir()
            (project / "rtl" / "demo.sv").write_text("module demo; endmodule\n", encoding="utf-8")
            bench = project / "tests" / "selfcheck_tb.sv"
            bench.write_text('module selfcheck_tb; initial $display("demo dut ("); endmodule\n', encoding="utf-8")
            manifest.update({
                "project_root": "project/demo", "top": "demo",
                "source_roots": ["project/demo/rtl"], "sources": ["project/demo/rtl/demo.sv"],
                "headers": [], "include_dirs": ["project/demo/rtl"],
                "clocks": [], "resets": [],
            })
            (project / "rtl_project_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            contract = json.loads((ROOT / CONTRACT).read_text(encoding="utf-8"))
            contract.update({"top": "selfcheck_tb", "testbench": "project/demo/tests/selfcheck_tb.sv"})
            (project / "rtl_simulation_contract.json").write_text(json.dumps(contract), encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "does not instantiate"):
                rtl_project_smoke.run_project(
                    Path("project/demo/rtl_project_manifest.json"),
                    Path("project/demo/rtl_simulation_contract.json"), repository_root=root,
                )


if __name__ == "__main__":
    unittest.main()
