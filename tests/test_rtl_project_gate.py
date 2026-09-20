"""New project G0/G1/G2 aggregation must fail closed and stay target-neutral."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.quality_gate import rtl_project_gate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("examples/rtl/counter/rtl_project_manifest.json")


class RtlProjectGateTests(unittest.TestCase):
    @staticmethod
    def lint(status="PASS"):
        return {
            "status": status,
            "source_sha256": {"examples/rtl/counter/src/rtl/counter.v": "a" * 64},
            "tool": {"name": "verilator", "version": "Verilator 5.048"},
            "returncode": 0 if status == "PASS" else 1,
            "warning_headers": [],
        }

    @staticmethod
    def smoke():
        return {
            "status": "PASS", "evidence_id": "sha256:" + "a" * 64,
            "execution": {"compile": "PASS", "run": "PASS", "pass_token_count": 1},
        }

    def test_gates_are_ordered_and_content_addressed(self):
        with patch.object(rtl_project_gate, "run_lint", return_value=self.lint()):
            with patch.object(rtl_project_gate, "run_project", return_value=self.smoke()) as smoke:
                result = rtl_project_gate.run_gates(MANIFEST, repository_root=ROOT)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["target"], "fpga")
        self.assertEqual(result["checks"], {"g0": "PASS", "g1": "PASS", "g2": "PASS"})
        self.assertTrue(result["evidence_id"].startswith("sha256:"))
        self.assertEqual(result["unified_evidence_id"], result["evidence_bundle"]["evidence_id"])
        self.assertEqual([stage["gate"] for stage in result["evidence_bundle"]["stages"]], ["G0", "G1", "G2"])
        self.assertTrue(result["supplemental"]["maintenance_evidence_id"].startswith("sha256:"))
        self.assertEqual(result["supplemental"]["generated_provenance"], "NOT_APPLICABLE")
        self.assertEqual(result["supplemental"]["domain_evidence"], "NOT_APPLICABLE")
        self.assertEqual(smoke.call_count, 1)

    def test_lint_failure_does_not_run_simulation(self):
        with patch.object(rtl_project_gate, "run_lint", return_value=self.lint("FAIL")):
            with patch.object(rtl_project_gate, "run_project") as smoke:
                result = rtl_project_gate.run_gates(MANIFEST, repository_root=ROOT)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["checks"]["g2"], "NOT_RUN")
        smoke.assert_not_called()

    def test_missing_project_contract_blocks_g2(self):
        with patch.object(rtl_project_gate, "run_lint", return_value=self.lint()):
            with patch.object(rtl_project_gate, "run_project", side_effect=FileNotFoundError()):
                result = rtl_project_gate.run_gates(MANIFEST, repository_root=ROOT)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blocked_gate"], "g2")
        self.assertEqual(result["reason_code"], "FileNotFoundError")
        self.assertEqual(result["checks"]["g2"], "NOT_RUN")

    def test_missing_multidomain_evidence_blocks_before_simulation(self):
        with patch.object(rtl_project_gate, "run_lint", return_value=self.lint()):
            with patch.object(rtl_project_gate, "validate_domain_evidence", side_effect=ValueError("missing")):
                with patch.object(rtl_project_gate, "run_project") as smoke:
                    result = rtl_project_gate.run_gates(MANIFEST, repository_root=ROOT)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blocked_gate"], "g2")
        smoke.assert_not_called()

    def test_template_testbench_cannot_claim_pass(self):
        source = (ROOT / "templates/rtl/selfcheck_tb.sv.template").read_text(encoding="utf-8")
        self.assertIn('$fatal(1, "PLACEHOLDER_TESTBENCH_NOT_REVIEWED")', source)
        self.assertNotIn('$display("MY_IP_SELF_CHECK_PASS")', source)


if __name__ == "__main__":
    unittest.main()
