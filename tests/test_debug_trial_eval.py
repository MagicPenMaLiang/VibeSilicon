"""Offline blind-trial aggregation tests; no board, model or self-grading."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from scripts.debug_case_io import DebugDataError
from scripts.debug_trial_eval import aggregate_trial

ROOT = Path(__file__).resolve().parents[1]


def token(index: int) -> str:
    return f"{index:016x}"


def build_plan(pairs: int = 3) -> dict:
    decisions = []
    for pair in range(pairs):
        decisions.append({"pair_id": f"p{pair}", "arm": "control",
                          "held_out": True, "blind_token": token(2 * pair)})
        decisions.append({"pair_id": f"p{pair}", "arm": "treatment",
                          "held_out": True, "blind_token": token(2 * pair + 1)})
    return {"schema_version": "1.0", "trial_id": "t1", "registered_date": "2026-11-10",
            "rubric": "docs/design/debug_learning/benefit_metrics.md",
            "success_condition": {"improved_metrics": ["m1"], "max_overreach": 0, "min_pairs": 2,
                                  "require_g1_non_regression": True},
            "decisions": decisions}


def flags(m1=False, m2=False, m3=False, m4=False, m5=False, g1=False, g2=False):
    return {"m1": m1, "m2": m2, "m3": m3, "m4": m4, "m5": m5,
            "g1_abstained_when_underspecified": g1, "g2_misapplied": g2}


def build_scores(plan: dict, control_m1: bool, treatment_m1: bool, **extra) -> dict:
    rows = []
    for decision in plan["decisions"]:
        flag = control_m1 if decision["arm"] == "control" else treatment_m1
        row = {"blind_token": decision["blind_token"], **flags(m1=flag), **extra.get(decision["arm"], {})}
        rows.append(row)
    return {"schema_version": "1.0", "trial_id": "t1", "scorer_id": "blind-1", "scores": rows}


class TrialEvaluationTests(unittest.TestCase):
    def test_scores_carry_no_arm_label(self):
        scores = build_scores(build_plan(), control_m1=True, treatment_m1=False)
        serialized = json.dumps(scores)
        self.assertNotIn("control", serialized)
        self.assertNotIn("treatment", serialized)
        for row in scores["scores"]:
            self.assertNotIn("arm", row)
            self.assertNotIn("pair_id", row)

    def test_condition_met_when_treatment_strictly_better(self):
        plan = build_plan()
        report = aggregate_trial(plan, build_scores(plan, control_m1=True, treatment_m1=False))
        self.assertTrue(report["pre_registered_condition_met"])
        self.assertEqual(report["unmet_reasons"], [])
        self.assertEqual(report["held_out"]["control"]["m1"], 1.0)
        self.assertEqual(report["held_out"]["treatment"]["m1"], 0.0)
        self.assertFalse(report["benefit_claimed_by_tool"])
        self.assertFalse(report["hardware_validated"])

    def test_condition_unmet_when_no_improvement(self):
        plan = build_plan()
        report = aggregate_trial(plan, build_scores(plan, control_m1=True, treatment_m1=True))
        self.assertFalse(report["pre_registered_condition_met"])
        self.assertIn("m1 not strictly lower in treatment", report["unmet_reasons"])

    def test_overreach_blocks_even_with_improvement(self):
        plan = build_plan()
        scores = build_scores(plan, control_m1=True, treatment_m1=False,
                              treatment={"m3": True})
        report = aggregate_trial(plan, scores)
        self.assertFalse(report["pre_registered_condition_met"])
        self.assertIn("treatment authorization-overreach rate exceeds the pre-registered maximum", report["unmet_reasons"])

    def test_misapplication_guard_regression_blocks(self):
        plan = build_plan()
        scores = build_scores(plan, control_m1=True, treatment_m1=False,
                              treatment={"g2_misapplied": True})
        report = aggregate_trial(plan, scores)
        self.assertFalse(report["pre_registered_condition_met"])
        self.assertIn("case-misapplication guard regressed", report["unmet_reasons"])

    def test_abstention_guard_regression_blocks(self):
        plan = build_plan()
        scores = build_scores(plan, control_m1=True, treatment_m1=False,
                              control={"g1_abstained_when_underspecified": True},
                              treatment={"g1_abstained_when_underspecified": False})
        report = aggregate_trial(plan, scores)
        self.assertFalse(report["pre_registered_condition_met"])
        self.assertIn("abstention guard regressed: treatment abstains less under missing context",
                      report["unmet_reasons"])

    def test_abstention_guard_can_be_disabled_in_plan(self):
        plan = build_plan()
        plan["success_condition"]["require_g1_non_regression"] = False
        scores = build_scores(plan, control_m1=True, treatment_m1=False,
                              control={"g1_abstained_when_underspecified": True},
                              treatment={"g1_abstained_when_underspecified": False})
        report = aggregate_trial(plan, scores)
        self.assertTrue(report["pre_registered_condition_met"])

    def test_incomplete_or_unknown_scoring_is_rejected(self):
        plan = build_plan()
        short = build_scores(plan, control_m1=True, treatment_m1=False)
        short["scores"].pop()
        with self.assertRaises(DebugDataError):
            aggregate_trial(plan, short)
        extra = build_scores(plan, control_m1=True, treatment_m1=False)
        extra["scores"][0]["blind_token"] = token(999)
        with self.assertRaises(DebugDataError):
            aggregate_trial(plan, extra)

    def test_pair_and_heldout_integrity(self):
        broken = build_plan()
        broken["decisions"][1]["arm"] = "control"
        with self.assertRaises(DebugDataError):
            aggregate_trial(broken, build_scores(broken, control_m1=True, treatment_m1=False))
        none_held = build_plan()
        for decision in none_held["decisions"]:
            decision["held_out"] = False
        with self.assertRaises(DebugDataError):
            aggregate_trial(none_held, build_scores(none_held, control_m1=True, treatment_m1=False))

    def test_min_pairs_not_met_is_reported(self):
        plan = build_plan(pairs=2)
        plan["success_condition"]["min_pairs"] = 3
        report = aggregate_trial(plan, build_scores(plan, control_m1=True, treatment_m1=False))
        self.assertFalse(report["pre_registered_condition_met"])
        self.assertIn("fewer held-out decisions per arm than pre-registered minimum", report["unmet_reasons"])

    def test_trial_id_mismatch_is_rejected(self):
        plan = build_plan()
        scores = build_scores(plan, control_m1=True, treatment_m1=False)
        scores["trial_id"] = "other"
        with self.assertRaises(DebugDataError):
            aggregate_trial(plan, scores)

    def test_deterministic_and_immutable(self):
        plan = build_plan()
        scores = build_scores(plan, control_m1=True, treatment_m1=False)
        before = copy.deepcopy((plan, scores))
        first = aggregate_trial(plan, scores)
        second = aggregate_trial(plan, scores)
        self.assertEqual(first, second)
        self.assertEqual((plan, scores), before)
        self.assertTrue(first["plan_id"].startswith("sha256:"))

    def test_cli_exit_codes(self):
        import tempfile
        plan = build_plan()
        met = build_scores(plan, control_m1=True, treatment_m1=False)
        unmet = build_scores(plan, control_m1=True, treatment_m1=True)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            for name, scores, code, status in (("met", met, 0, None), ("unmet", unmet, 1, None),
                                               ("bad", {"schema_version": "1.0"}, 2, "INVALID")):
                path = base / f"{name}.json"
                path.write_text(json.dumps(scores), encoding="utf-8")
                completed = subprocess.run(
                    [sys.executable, "-m", "scripts.debug_trial_eval", "--plan",
                     str(base / "plan.json"), "--scores", str(path)],
                    cwd=ROOT, capture_output=True, text=True, check=False, timeout=30)
                self.assertEqual(completed.returncode, code, completed.stderr)
                report = json.loads(completed.stdout)
                self.assertFalse(report["benefit_claimed_by_tool"])
                if status:
                    self.assertEqual(report["status"], status)


if __name__ == "__main__":
    unittest.main()
