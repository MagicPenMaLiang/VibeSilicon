"""Portable scenario replay tests; no board, model or private run is used."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from scripts import debug_learning_eval as evaluation
from scripts.debug_case_io import DebugDataError, read_document
from scripts.debug_cases import load_catalog

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "knowledge/fpga-video/evaluation/scenarios.json"


class DebugLearningEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_catalog(ROOT / "knowledge/fpga-video/cases")
        cls.scenarios = read_document(SCENARIOS)

    def test_frozen_positive_and_counterfactual_scenarios(self):
        result = evaluation.evaluate_scenarios(self.cases, self.scenarios)
        self.assertEqual(result["status"], "PASS")
        self.assertGreaterEqual(result["total"], 12)
        self.assertEqual(result["passed"], result["total"])
        self.assertFalse(result["model_evaluation_performed"])
        self.assertFalse(result["hardware_validated"])
        self.assertFalse(result["execution_authorized"])
        self.assertTrue(result["synthetic"])
        self.assertEqual(result["evaluation_kind"], "deterministic_offline_contract")

    def test_wrong_expectation_fails_not_silently_relabelled(self):
        changed = copy.deepcopy(self.scenarios)
        first = changed["scenarios"][0]["expected"]
        matched = first["matched"].pop()
        first["excluded"].append(matched)
        result = evaluation.evaluate_scenarios(self.cases, changed)
        self.assertEqual(result["status"], "FAIL")
        self.assertLess(result["passed"], result["total"])
        self.assertFalse(result["results"][0]["passed"])

    def test_report_and_inputs_are_deterministic_and_immutable(self):
        cases, scenarios = copy.deepcopy(self.cases), copy.deepcopy(self.scenarios)
        before = copy.deepcopy((cases, scenarios))
        first = evaluation.evaluate_scenarios(cases, scenarios)
        second = evaluation.evaluate_scenarios(cases, scenarios)
        self.assertEqual(first, second)
        self.assertEqual((cases, scenarios), before)
        self.assertTrue(first["catalog_id"].startswith("sha256:"))
        self.assertTrue(first["scenario_set_id"].startswith("sha256:"))

    def test_scenario_change_changes_content_binding(self):
        changed = copy.deepcopy(self.scenarios)
        changed["scenarios"][0]["id"] += "-variant"
        left = evaluation.evaluate_scenarios(self.cases, self.scenarios)
        right = evaluation.evaluate_scenarios(self.cases, changed)
        self.assertNotEqual(left["scenario_set_id"], right["scenario_set_id"])

    def test_invalid_scenario_structure_is_rejected(self):
        for change in ([], {}, {"schema_version": "other", "scenarios": []}):
            with self.subTest(change=change), self.assertRaises(DebugDataError):
                evaluation.evaluate_scenarios(self.cases, change)

    def test_duplicate_scenario_ids_are_rejected(self):
        changed = copy.deepcopy(self.scenarios)
        changed["scenarios"][1]["id"] = changed["scenarios"][0]["id"]
        with self.assertRaises(DebugDataError):
            evaluation.evaluate_scenarios(self.cases, changed)

    def test_unknown_case_labels_are_rejected(self):
        changed = copy.deepcopy(self.scenarios)
        changed["scenarios"][0]["expected"]["matched"] = ["unknown-case"]
        with self.assertRaises(DebugDataError):
            evaluation.evaluate_scenarios(self.cases, changed)

    def test_overlapping_and_incomplete_labels_are_rejected(self):
        for overlap in (False, True):
            changed = copy.deepcopy(self.scenarios)
            expected = changed["scenarios"][0]["expected"]
            if overlap:
                expected["excluded"].extend(expected["matched"])
            else:
                expected["matched"] = []
            with self.subTest(overlap=overlap), self.assertRaises(DebugDataError):
                evaluation.evaluate_scenarios(self.cases, changed)

    def test_extra_fields_cannot_claim_model_evaluation(self):
        changed = copy.deepcopy(self.scenarios)
        changed["model_evaluation_performed"] = True
        with self.assertRaises(DebugDataError):
            evaluation.evaluate_scenarios(self.cases, changed)

    def test_direct_cli_exit_codes_and_structured_output(self):
        import contextlib
        import io
        import tempfile

        wrong = copy.deepcopy(self.scenarios)
        expected = wrong["scenarios"][0]["expected"]
        expected["excluded"].append(expected["matched"].pop())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenarios.json"
            for document, code, status in ((self.scenarios, 0, "PASS"),
                                           (wrong, 1, "FAIL"), ({}, 2, "INVALID")):
                with self.subTest(status=status):
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with contextlib.redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(evaluation.main(["--scenarios", str(path)]), code)
                    report = json.loads(output.getvalue())
                    self.assertEqual(report["status"], status)
                    self.assertFalse(report["execution_authorized"])
                    self.assertFalse(report["model_evaluation_performed"])

    def test_cli_software_integration(self):
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.debug_learning_eval"], cwd=ROOT,
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["model_evaluation_performed"])

    def test_cli_invalid_input_has_json_error_no_traceback(self):
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.debug_learning_eval", "--scenarios",
             "missing-debug-learning-scenarios.json"], cwd=ROOT,
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(json.loads(completed.stdout)["status"], "INVALID")
        self.assertNotIn("Traceback", completed.stderr)


if __name__ == "__main__":
    unittest.main()
