"""New project G0/G1/G2 aggregation must fail closed and stay target-neutral."""

import hashlib
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from scripts.quality_gate import rtl_project_gate


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("examples/rtl/counter/rtl_project_manifest.json")
SOURCE = "examples/rtl/counter/rtl/counter.sv"


class RtlProjectGateTests(unittest.TestCase):
    @staticmethod
    def lint(status="PASS", root=ROOT):
        return {
            "status": status,
            "source_sha256": {SOURCE: hashlib.sha256((root / SOURCE).read_bytes()).hexdigest()},
            "tool": {"name": "verilator", "version": "Verilator 5.048"},
            "returncode": 0 if status == "PASS" else 1,
            "warning_headers": [],
        }

    @contextmanager
    def project_with_source(self, text):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for relative in (MANIFEST, MANIFEST.parent / "rtl_quality_waivers.json", Path(SOURCE)):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            (root / SOURCE).write_text(text, encoding="utf-8")
            yield root

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
        self.assertEqual(result["g1_static_evidence"]["status"], "PASS")
        metrics = result["evidence_bundle"]["stages"][1]["metrics"]
        self.assertEqual(metrics["static_evidence_id"], result["g1_static_evidence"]["evidence_id"])

    def test_readability_failure_blocks_g1_even_when_verilator_passes(self):
        text = (ROOT / SOURCE).read_text(encoding="utf-8")
        text = text[text.index("`default_nettype none"):]
        with self.project_with_source(text) as root:
            with patch.object(rtl_project_gate, "run_lint", return_value=self.lint(root=root)):
                with patch.object(rtl_project_gate, "run_project") as smoke:
                    result = rtl_project_gate.run_gates(MANIFEST, repository_root=root)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["checks"], {"g0": "PASS", "g1": "FAIL", "g2": "NOT_RUN"})
        stage = result["evidence_bundle"]["stages"][1]
        self.assertEqual(stage["metrics"]["returncode"], 0)
        self.assertEqual(stage["metrics"]["static_status"], "FAIL")
        self.assertIn("RTL-R007", {item["rule_id"] for item in stage["annotations"]})
        smoke.assert_not_called()

    def test_async_reg_failures_are_included_in_g1(self):
        text = '''`default_nettype none
module counter(input wire clk_i, input wire clk_b, input wire rst_ni, input wire enable_i, output reg count_o);
always @(posedge clk_i) begin
    count_o <= enable_i;
end
always @(posedge clk_b) begin
    count_o <= enable_i;
end
endmodule
`default_nettype wire
'''
        with self.project_with_source(text) as root:
            with patch.object(rtl_project_gate, "run_lint", return_value=self.lint(root=root)):
                with patch.object(rtl_project_gate, "run_project") as smoke:
                    result = rtl_project_gate.run_gates(MANIFEST, repository_root=root)
        self.assertEqual(result["checks"]["g1"], "FAIL")
        self.assertEqual(result["g1_static_evidence"]["async_reg"]["missing"], 1)
        self.assertIn("ASYNC-REG", {item["rule_id"] for item in result["evidence_bundle"]["stages"][1]["annotations"]})
        smoke.assert_not_called()

    def test_incomplete_static_check_blocks_instead_of_passing(self):
        with patch.object(rtl_project_gate, "run_lint", return_value=self.lint()):
            with patch.object(rtl_project_gate, "run_static_checks", side_effect=OSError("unreadable source")):
                with patch.object(rtl_project_gate, "run_project") as smoke:
                    result = rtl_project_gate.run_gates(MANIFEST, repository_root=ROOT)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blocked_gate"], "g1")
        self.assertIsNone(result["evidence_bundle"]["stages"][1]["metrics"]["static_status"])
        smoke.assert_not_called()

    def test_source_changes_between_g0_and_lint_block_g1(self):
        lint = self.lint()
        lint["source_sha256"][SOURCE] = "a" * 64
        with patch.object(rtl_project_gate, "run_lint", return_value=lint):
            with patch.object(rtl_project_gate, "run_project") as smoke:
                result = rtl_project_gate.run_gates(MANIFEST, repository_root=ROOT)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blocked_gate"], "g1")
        smoke.assert_not_called()

    def test_waiver_registry_changes_during_g0_block_the_gate(self):
        validate = rtl_project_gate.validate_waivers
        with self.project_with_source((ROOT / SOURCE).read_text(encoding="utf-8")) as root:
            def mutate(*args, **kwargs):
                report = validate(*args, **kwargs)
                registry = root / MANIFEST.parent / "rtl_quality_waivers.json"
                registry.write_bytes(registry.read_bytes() + b"\n")
                return report

            with patch.object(rtl_project_gate, "validate_waivers", side_effect=mutate):
                with patch.object(rtl_project_gate, "run_lint") as lint:
                    result = rtl_project_gate.run_gates(MANIFEST, repository_root=root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blocked_gate"], "g0")
        lint.assert_not_called()

    def test_manifest_changes_during_g1_block_the_gate(self):
        with self.project_with_source((ROOT / SOURCE).read_text(encoding="utf-8")) as root:
            def mutate(*args, **kwargs):
                manifest = root / MANIFEST
                manifest.write_bytes(manifest.read_bytes() + b"\n")
                return self.lint(root=root)

            with patch.object(rtl_project_gate, "run_lint", side_effect=mutate):
                with patch.object(rtl_project_gate, "run_project") as smoke:
                    result = rtl_project_gate.run_gates(MANIFEST, repository_root=root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blocked_gate"], "g1")
        smoke.assert_not_called()

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
