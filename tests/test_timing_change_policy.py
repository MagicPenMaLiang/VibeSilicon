import json
import unittest

from tests.support import ROOT, load_module


policy = load_module("vibesilicon_timing_change_policy", "scripts/timing_change_policy.py")
EVIDENCE = "sha256:" + "a" * 64


class TimingChangePolicyTests(unittest.TestCase):
    def proposal(self, **overrides):
        value = {
            "schema_version": 1,
            "proposal_id": "TIMING-DEMO-001",
            "analysis_evidence_id": EVIDENCE,
            "hypothesis": "route delay dominates the worst path",
            "changes": [
                {"path": "rtl/top.sv", "kind": "rtl", "description": "register fanout source"}
            ],
            "constraints": [],
            "invariants": ["bit_exact", "latency_unchanged"],
            "required_gates": ["G1", "G2", "G3", "G4"],
            "max_iterations": 3,
            "approval_status": "PENDING",
        }
        value.update(overrides)
        return value

    def test_pending_valid_proposal_is_ready_for_approval(self):
        result = policy.validate_proposal(self.proposal())
        self.assertEqual(result["decision"], "READY_FOR_APPROVAL")
        self.assertEqual(result["risk_class"], "R2")

    def test_approved_valid_proposal_is_not_executed_by_validator(self):
        result = policy.validate_proposal(self.proposal(approval_status="APPROVED"))
        self.assertEqual(result["decision"], "APPROVED_FOR_EXECUTION")

    def test_broad_false_path_is_blocked_even_with_proof(self):
        constraint = {
            "type": "false_path",
            "command": "set_false_path -from [all_registers] -to [get_pins sink/D]",
            "from": "all registers",
            "to": "sink/D",
            "proof_evidence_id": EVIDENCE,
        }
        with self.assertRaisesRegex(policy.TimingPolicyError, "broad"):
            policy.validate_proposal(self.proposal(constraints=[constraint]))

    def test_sensitive_constraint_without_proof_is_blocked(self):
        constraint = {
            "type": "false_path",
            "command": "set_false_path -from [get_ports rst_n] -to [get_pins sync_ff1/D]",
            "from": "rst_n",
            "to": "sync_ff1/D",
            "proof_evidence_id": "missing",
        }
        with self.assertRaisesRegex(policy.TimingPolicyError, "content-addressed"):
            policy.validate_proposal(self.proposal(constraints=[constraint]))

    def test_multicycle_requires_paired_hold(self):
        constraint = {
            "type": "multicycle",
            "command": "set_multicycle_path -setup 4 -from A -to B",
            "from": "A",
            "to": "B",
            "proof_evidence_id": EVIDENCE,
            "setup_cycles": 4,
            "hold_cycles": 2,
        }
        with self.assertRaisesRegex(policy.TimingPolicyError, "N-1"):
            policy.validate_proposal(self.proposal(constraints=[constraint]))

    def test_fourth_blind_iteration_is_blocked(self):
        with self.assertRaisesRegex(policy.TimingPolicyError, "between 1 and 3"):
            policy.validate_proposal(self.proposal(max_iterations=4))

    def test_change_path_cannot_escape_project(self):
        changes = [{"path": "../outside.sv", "kind": "rtl", "description": "escape"}]
        with self.assertRaisesRegex(policy.TimingPolicyError, "project root"):
            policy.validate_proposal(self.proposal(changes=changes))

    def test_schema_is_versioned(self):
        schema = json.loads(
            (ROOT / "schemas/timing_change_proposal.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)


if __name__ == "__main__":
    unittest.main()
