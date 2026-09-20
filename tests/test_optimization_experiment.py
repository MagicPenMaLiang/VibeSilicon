import json
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT, load_module


experiment = load_module(
    "vibesilicon_optimization_experiment", "scripts/optimization_experiment.py"
)


class OptimizationExperimentTests(unittest.TestCase):
    def make_spec(self, **overrides):
        value = {
            "schema_version": 1,
            "experiment_id": "OPT-TEST-001",
            "hypothesis": "One pipeline stage improves routed WNS without excess LUT growth.",
            "baseline": {
                "evidence_id": "sha256:" + "a" * 64,
                "metrics": {"wns_ns": 0.1, "lut": 100.0},
            },
            "objectives": [{"metric": "wns_ns", "operator": ">=", "value": 0.2}],
            "guardrails": [{"metric": "lut", "max_delta_pct": 5.0}],
            "non_regression": [{"metric": "wns_ns", "direction": "higher"}],
            "invariants": ["bit_exact", "latency_4"],
            "files": ["rtl/design.sv"],
            "required_gates": ["G1", "G2", "G3", "G4"],
            "max_iterations": 2,
            "auto_rollback": True,
        }
        value.update(overrides)
        return value

    def make_result(self, **overrides):
        value = {
            "schema_version": 1,
            "evidence_id": "sha256:" + "b" * 64,
            "metrics": {"wns_ns": 0.25, "lut": 103.0},
            "invariants": {"bit_exact": True, "latency_4": True},
            "gates": {"G1": "PASS", "G2": "PASS", "G3": "PASS", "G4": "PASS"},
        }
        value.update(overrides)
        return value

    def prepare(self, root):
        root_path = Path(root)
        source = root_path / "rtl" / "design.sv"
        source.parent.mkdir()
        source.write_text("baseline\n", encoding="utf-8")
        return root_path, source

    def test_start_captures_content_addressed_baseline(self):
        with tempfile.TemporaryDirectory() as root:
            root_path, source = self.prepare(root)
            state = experiment.start_experiment(root_path, self.make_spec())
            snapshot = root_path / ".vibesilicon/optimization/OPT-TEST-001/baseline/rtl/design.sv"
            snapshot_content = snapshot.read_text(encoding="utf-8")
            source_content = source.read_text(encoding="utf-8")
        self.assertEqual(state["status"], "ACTIVE")
        self.assertEqual(state["iteration"], 0)
        self.assertEqual(snapshot_content, source_content)

    def test_target_and_guardrails_pass_accepts_change(self):
        with tempfile.TemporaryDirectory() as root:
            root_path, source = self.prepare(root)
            experiment.start_experiment(root_path, self.make_spec())
            source.write_text("optimized\n", encoding="utf-8")
            state = experiment.evaluate_experiment(root_path, "OPT-TEST-001", self.make_result())
            content = source.read_text(encoding="utf-8")
        self.assertEqual(state["status"], "ACCEPTED")
        self.assertEqual(state["history"][-1]["decision"], "ACCEPT")
        self.assertEqual(content, "optimized\n")

    def test_invariant_failure_automatically_restores_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            root_path, source = self.prepare(root)
            experiment.start_experiment(root_path, self.make_spec())
            source.write_text("broken\n", encoding="utf-8")
            result = self.make_result(invariants={"bit_exact": False, "latency_4": True})
            state = experiment.evaluate_experiment(root_path, "OPT-TEST-001", result)
            content = source.read_text(encoding="utf-8")
        self.assertEqual(state["status"], "ROLLED_BACK")
        self.assertIn("invariant_failed:bit_exact", state["history"][-1]["reasons"])
        self.assertEqual(content, "baseline\n")

    def test_guardrail_regression_automatically_restores_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            root_path, source = self.prepare(root)
            experiment.start_experiment(root_path, self.make_spec())
            source.write_text("too-large\n", encoding="utf-8")
            state = experiment.evaluate_experiment(
                root_path,
                "OPT-TEST-001",
                self.make_result(metrics={"wns_ns": 0.3, "lut": 110.0}),
            )
            content = source.read_text(encoding="utf-8")
        self.assertEqual(state["status"], "ROLLED_BACK")
        self.assertIn("guardrail_exceeded:lut", state["history"][-1]["reasons"])
        self.assertEqual(content, "baseline\n")

    def test_max_iterations_without_target_stops_and_restores(self):
        with tempfile.TemporaryDirectory() as root:
            root_path, source = self.prepare(root)
            experiment.start_experiment(root_path, self.make_spec())
            source.write_text("iteration-one\n", encoding="utf-8")
            first = experiment.evaluate_experiment(
                root_path,
                "OPT-TEST-001",
                self.make_result(evidence_id="sha256:" + "c" * 64, metrics={"wns_ns": 0.15, "lut": 101.0}),
            )
            source.write_text("iteration-two\n", encoding="utf-8")
            second = experiment.evaluate_experiment(
                root_path,
                "OPT-TEST-001",
                self.make_result(evidence_id="sha256:" + "d" * 64, metrics={"wns_ns": 0.18, "lut": 102.0}),
            )
            content = source.read_text(encoding="utf-8")
        self.assertEqual(first["status"], "ACTIVE")
        self.assertEqual(second["status"], "ROLLED_BACK")
        self.assertIn("max_iterations_without_target", second["history"][-1]["reasons"])
        self.assertEqual(content, "baseline\n")

    def test_missing_gate_is_fail_closed_and_restored(self):
        with tempfile.TemporaryDirectory() as root:
            root_path, source = self.prepare(root)
            experiment.start_experiment(root_path, self.make_spec())
            source.write_text("unchecked\n", encoding="utf-8")
            result = self.make_result(gates={"G1": "PASS", "G2": "PASS", "G3": "PASS"})
            state = experiment.evaluate_experiment(root_path, "OPT-TEST-001", result)
            content = source.read_text(encoding="utf-8")
        self.assertIn("gate_not_pass:G4", state["history"][-1]["reasons"])
        self.assertEqual(content, "baseline\n")

    def test_invalid_metric_is_fail_closed_and_restored(self):
        with tempfile.TemporaryDirectory() as root:
            root_path, source = self.prepare(root)
            experiment.start_experiment(root_path, self.make_spec())
            source.write_text("invalid-evidence\n", encoding="utf-8")
            result = self.make_result(metrics={"wns_ns": "unknown", "lut": 103.0})
            state = experiment.evaluate_experiment(root_path, "OPT-TEST-001", result)
            content = source.read_text(encoding="utf-8")
        self.assertIn("invalid_metric:wns_ns", state["history"][-1]["reasons"])
        self.assertEqual(state["status"], "ROLLED_BACK")
        self.assertEqual(content, "baseline\n")

    def test_deleted_file_is_restored_when_parent_remains(self):
        with tempfile.TemporaryDirectory() as root:
            root_path, source = self.prepare(root)
            experiment.start_experiment(root_path, self.make_spec())
            source.unlink()
            result = self.make_result(invariants={"bit_exact": False, "latency_4": True})
            state = experiment.evaluate_experiment(root_path, "OPT-TEST-001", result)
            content = source.read_text(encoding="utf-8")
        self.assertEqual(state["status"], "ROLLED_BACK")
        self.assertEqual(content, "baseline\n")

    def test_missing_parent_refuses_unsafe_restore(self):
        with tempfile.TemporaryDirectory() as root:
            root_path, source = self.prepare(root)
            experiment.start_experiment(root_path, self.make_spec())
            source.unlink()
            source.parent.rmdir()
            result = self.make_result(invariants={"bit_exact": False, "latency_4": True})
            with self.assertRaisesRegex(experiment.ExperimentError, "parent directory is missing"):
                experiment.evaluate_experiment(root_path, "OPT-TEST-001", result)
        self.assertFalse(source.exists())

    def test_outside_file_and_duplicate_start_are_rejected(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            root_path, _ = self.prepare(root)
            outside_file = Path(outside) / "outside.sv"
            outside_file.write_text("outside\n", encoding="utf-8")
            bad = self.make_spec(files=[str(outside_file)])
            with self.assertRaisesRegex(experiment.ExperimentError, "outside"):
                experiment.start_experiment(root_path, bad)
            experiment.start_experiment(root_path, self.make_spec())
            with self.assertRaisesRegex(experiment.ExperimentError, "already exists"):
                experiment.start_experiment(root_path, self.make_spec())

    def test_tampered_baseline_refuses_unsafe_restore(self):
        with tempfile.TemporaryDirectory() as root:
            root_path, source = self.prepare(root)
            experiment.start_experiment(root_path, self.make_spec())
            snapshot = root_path / ".vibesilicon/optimization/OPT-TEST-001/baseline/rtl/design.sv"
            snapshot.write_text("tampered\n", encoding="utf-8")
            source.write_text("broken\n", encoding="utf-8")
            result = self.make_result(invariants={"bit_exact": False, "latency_4": True})
            with self.assertRaisesRegex(experiment.ExperimentError, "hash mismatch"):
                experiment.evaluate_experiment(root_path, "OPT-TEST-001", result)
            content = source.read_text(encoding="utf-8")
        self.assertEqual(content, "broken\n")

    def test_schema_is_versioned_json(self):
        schema = json.loads(
            (ROOT / "schemas/optimization_experiment.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        experiment.validate_spec(self.make_spec())


if __name__ == "__main__":
    unittest.main()
