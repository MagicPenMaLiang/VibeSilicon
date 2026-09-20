import json
import unittest

from tests.support import ROOT, load_module


formal = load_module(
    "vibesilicon_formal_verification_policy", "scripts/formal_verification_policy.py"
)
EVIDENCE = "sha256:" + "a" * 64


class FormalVerificationPolicyTests(unittest.TestCase):
    def assessment(self, **overrides):
        value = {
            "schema_version": 1,
            "assessment_id": "FORMAL-DEMO-001",
            "top": "demo",
            "rtl_files": ["rtl/demo.sv"],
            "change_kinds": ["combinational_refactor"],
            "stateful": False,
            "latency_changed": False,
            "latency_contract": None,
            "clock_domains": 1,
            "reset_model": "sync",
            "contains_cdc": False,
            "contains_vendor_ip": False,
            "blackbox_contracts": [],
            "properties": [],
            "assumptions": [],
            "tool": {
                "engine": "symbiyosys",
                "available": True,
                "version": "2.4",
                "probe_evidence_id": EVIDENCE,
            },
            "result": None,
        }
        value.update(overrides)
        return value

    def property_set(self):
        return [
            {"id": "A_RESET", "kind": "assert", "description": "reset reaches idle"},
            {"id": "C_PROGRESS", "kind": "cover", "description": "transaction completes"},
        ]

    def pass_result(self, **overrides):
        value = {
            "status": "PASS",
            "evidence_id": EVIDENCE,
            "modes_completed": ["combinational_equivalence"],
            "properties_proven": [],
            "covers_reached": [],
            "vacuity_checked": True,
            "proof_kind": "unbounded",
            "depth": None,
        }
        value.update(overrides)
        return value

    def test_combinational_refactor_selects_combinational_equivalence(self):
        result = formal.validate_assessment(self.assessment())
        self.assertEqual(result["decision"], "READY_TO_RUN")
        self.assertEqual(result["required_modes"], ["combinational_equivalence"])

    def test_stateful_refactor_escalates_to_sequential_equivalence(self):
        result = formal.validate_assessment(self.assessment(stateful=True))
        self.assertEqual(result["required_modes"], ["sequential_equivalence"])

    def test_latency_change_requires_explicit_alignment_contract(self):
        with self.assertRaisesRegex(formal.FormalPolicyError, "latency_contract"):
            formal.validate_assessment(
                self.assessment(
                    change_kinds=["pipeline"],
                    stateful=True,
                    latency_changed=True,
                )
            )

    def test_cdc_requires_property_proof_and_external_cdc_analysis(self):
        result = formal.validate_assessment(
            self.assessment(
                change_kinds=["cdc"],
                stateful=True,
                clock_domains=2,
                contains_cdc=True,
                properties=self.property_set(),
            )
        )
        self.assertEqual(result["required_modes"], ["cdc_analysis", "property_checking"])

    def test_property_checking_requires_assert_and_cover(self):
        with self.assertRaisesRegex(formal.FormalPolicyError, "assert and cover"):
            formal.validate_assessment(
                self.assessment(
                    change_kinds=["state_machine"],
                    stateful=True,
                    properties=[self.property_set()[0]],
                )
            )

    def test_missing_required_tool_is_blocked_not_skipped(self):
        result = formal.validate_assessment(
            self.assessment(
                tool={
                    "engine": "symbiyosys",
                    "available": False,
                    "version": None,
                    "probe_evidence_id": EVIDENCE,
                }
            )
        )
        self.assertEqual(result["decision"], "BLOCKED")
        self.assertIn("unavailable", result["reason"])

    def test_vacuous_or_broad_assumption_is_rejected(self):
        assumption = {
            "id": "A_BAD",
            "description": "all inputs stable",
            "justification": "make proof easy",
            "evidence_id": EVIDENCE,
        }
        with self.assertRaisesRegex(formal.FormalPolicyError, "broad assumption"):
            formal.validate_assessment(self.assessment(assumptions=[assumption]))

    def test_vendor_ip_requires_evidenced_boundary_contract(self):
        with self.assertRaisesRegex(formal.FormalPolicyError, "blackbox"):
            formal.validate_assessment(
                self.assessment(
                    change_kinds=["vendor_ip_update"],
                    stateful=True,
                    contains_vendor_ip=True,
                    properties=self.property_set(),
                )
            )

    def test_pass_requires_all_obligations_and_vacuity_check(self):
        result = formal.validate_assessment(self.assessment(result=self.pass_result()))
        self.assertEqual(result["decision"], "PASS")
        with self.assertRaisesRegex(formal.FormalPolicyError, "vacuity_checked"):
            formal.validate_assessment(
                self.assessment(result=self.pass_result(vacuity_checked=False))
            )

    def test_property_pass_requires_asserts_and_covers_in_evidence(self):
        with self.assertRaisesRegex(formal.FormalPolicyError, "missing proof obligations"):
            formal.validate_assessment(
                self.assessment(
                    change_kinds=["state_machine"],
                    stateful=True,
                    properties=self.property_set(),
                    result=self.pass_result(
                        modes_completed=["property_checking"],
                        properties_proven=["A_RESET"],
                    ),
                )
            )

    def test_failed_or_inconclusive_result_blocks(self):
        failed = self.pass_result(status="INCONCLUSIVE", evidence_id=None)
        result = formal.validate_assessment(self.assessment(result=failed))
        self.assertEqual(result["decision"], "BLOCKED")

    def test_constraint_only_routes_to_timing_and_cdc(self):
        result = formal.validate_assessment(
            self.assessment(change_kinds=["constraint_only"])
        )
        self.assertEqual(result["applicability"], "NOT_APPLICABLE")
        self.assertEqual(result["decision"], "USE_TIMING_AND_CDC_GATES")

    def test_paths_cannot_escape_project(self):
        with self.assertRaisesRegex(formal.FormalPolicyError, "project root"):
            formal.validate_assessment(self.assessment(rtl_files=["../secret.sv"]))

    def test_schema_is_versioned_json(self):
        schema = json.loads(
            (ROOT / "schemas/formal_assessment.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)


if __name__ == "__main__":
    unittest.main()
