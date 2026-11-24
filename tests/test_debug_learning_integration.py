"""CLI E2E for portable tooling, not video/board end-to-end acceptance."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts.debug_case_io import read_document
from scripts.debug_cases import load_catalog, query_cases
from scripts.debug_learning_eval import evaluate_scenarios
from scripts.debug_preflight import check_run_plan

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/debug_learning"
CATALOG = ROOT / "knowledge/fpga-video"


def inventory(directory):
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file()}


class DebugLearningIntegrationTests(unittest.TestCase):
    def invoke(self, module, *args):
        completed = subprocess.run(
            [sys.executable, "-m", module, *args], cwd=ROOT,
            capture_output=True, text=True, check=False, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        return json.loads(completed.stdout)

    def test_documented_cli_pipeline_is_read_only_and_never_authorizes(self):
        before = (inventory(CATALOG), inventory(EXAMPLE))
        validated = self.invoke("scripts.debug_cases", "validate")
        queried = self.invoke("scripts.debug_cases", "query", "--context",
                              "examples/debug_learning/context.json")
        replayed = self.invoke("scripts.debug_learning_eval")
        checked = self.invoke("scripts.debug_preflight", "--root", "examples/debug_learning",
                              "--plan", "examples/debug_learning/plan.json")
        self.assertEqual(len(validated["case_ids"]), 7)
        self.assertEqual([row["case_id"] for row in queried["matched"]], ["nv12-rgbx"])
        self.assertEqual(replayed["passed"], 16)
        self.assertEqual(checked["offline_checks"], "PASS")
        for result in (validated, queried, replayed, checked):
            self.assertFalse(result["hardware_validated"])
        self.assertFalse(checked["eligible_for_hardware"])
        self.assertFalse(checked["live_state_verified"])
        self.assertFalse(checked["execution_authorized"])
        self.assertEqual((inventory(CATALOG), inventory(EXAMPLE)), before)

    def test_python_interfaces_do_not_spawn_processes_or_open_sockets(self):
        cases = load_catalog(CATALOG / "cases")
        scenarios = read_document(CATALOG / "evaluation/scenarios.json")
        plan = read_document(EXAMPLE / "plan.json")
        with patch("subprocess.run", side_effect=AssertionError("process forbidden")), \
                patch("socket.socket", side_effect=AssertionError("socket forbidden")):
            self.assertTrue(query_cases(cases, {"target": "fpga"})["needs_context"])
            self.assertEqual(evaluate_scenarios(cases, scenarios)["status"], "PASS")
            self.assertEqual(check_run_plan(EXAMPLE, plan)["offline_checks"], "PASS")

    def test_empty_catalog_cannot_create_vacuous_evaluation_pass(self):
        scenarios = {"schema_version": "1.0", "scenarios": [{
            "id": "empty", "context": {},
            "expected": {"matched": [], "needs_context": [], "excluded": []},
        }]}
        with self.assertRaises(ValueError):
            evaluate_scenarios([], scenarios)


if __name__ == "__main__":
    unittest.main()
