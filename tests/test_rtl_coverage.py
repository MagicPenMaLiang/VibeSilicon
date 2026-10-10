import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts.evidence_contract import content_id
from scripts.quality_gate import rtl_coverage as coverage
from tests.support import ROOT


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "design.sv").write_text("module design; endmodule\n")
        self.contract = {"schema_version": 1, "backend": "verilator", "metric": "line",
                         "scope": ["design.sv"], "minimum_percent": 100, "simulation_contract": "simulation.json"}
        (self.root / "simulation.json").write_text("{}")
        self.manifest = {"sources": ["design.sv"], "headers": []}

    def test_supported_scope_counts_instrumented_lines(self):
        text = "SF:design.sv\nDA:1,2\nDA:2,0\nend_of_record\n"
        result = coverage.parse_lcov(text, self.root, ["design.sv"])
        self.assertEqual((result["hit"], result["total"], result["percent"]), (1, 2, 50))
        self.assertEqual(result["sources"]["design.sv"]["uncovered_lines"], [2])

    def test_truncated_duplicate_negative_or_absent_points_block(self):
        for text in ("SF:design.sv\nDA:1,1", "SF:design.sv\nDA:1,-1\nend_of_record\n",
                     "SF:design.sv\nDA:1,1\nDA:1,0\nend_of_record\n", "SF:design.sv\nend_of_record\n",
                     "SF:../design.sv\nDA:1,1\nend_of_record\n"):
            with self.subTest(text=text), self.assertRaises((ValueError, OSError)):
                coverage.parse_lcov(text, self.root, ["design.sv"])

    def test_unsupported_metric_bad_scope_and_threshold_rejected(self):
        for field, value in (("metric", "toggle"), ("scope", []), ("scope", ["other.sv"]),
                             ("minimum_percent", True), ("minimum_percent", float("nan")),
                             ("minimum_percent", 0), ("scope", ["design.sv", "design.sv"])):
            contract = self.contract | {field: value}
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                coverage.validate_contract(self.root, self.manifest, contract)

    def copy_example(self):
        destination = self.root / "examples/rtl/counter"
        destination.parent.mkdir(parents=True)
        shutil.copytree(ROOT / "examples/rtl/counter", destination)
        return "examples/rtl/counter/rtl_project_manifest.json", "examples/rtl/counter/rtl_coverage_contract.json"

    def test_missing_tool_has_no_pass_or_metrics(self):
        manifest, contract = self.copy_example()
        with patch.object(coverage, "_tool", return_value={"status": "MISSING", "version": None}):
            result = coverage.run_coverage(manifest, contract, self.root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIsNone(result["metrics"])
        coverage.verify_report(self.root, result)
        forged = copy.deepcopy(result)
        forged["status"] = "PASS"
        forged["evidence_id"] = content_id(forged, "evidence_id")
        with self.assertRaises(ValueError):
            coverage.verify_report(self.root, forged)

    def test_test_failure_cannot_be_covered_by_pass_token(self):
        manifest, contract = self.copy_example()
        tool = {"status": "AVAILABLE", "version": "Verilator 5.048"}
        with patch.object(coverage, "_tool", return_value=tool), patch.object(coverage, "_run", return_value={
            "compile": "PASS", "run": "FAIL", "pass_token_count": 1
        }):
            result = coverage.run_coverage(manifest, contract, self.root)
        self.assertEqual(result["status"], "FAIL")
        self.assertIsNone(result["metrics"])

    def test_input_change_during_execution_blocks_result(self):
        manifest, contract = self.copy_example()
        def changed(*args, **kwargs):
            path = self.root / "examples/rtl/counter/rtl/counter.sv"
            path.write_text(path.read_text() + "\n// changed\n")
            return {"compile": "FAIL", "run": "NOT_RUN", "pass_token_count": 0}
        with patch.object(coverage, "_tool", return_value={"status": "AVAILABLE", "version": "Verilator 5.048"}), patch.object(coverage, "_run", side_effect=changed):
            result = coverage.run_coverage(manifest, contract, self.root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("inputs changed during coverage run", result["errors"])

    def test_example_matches_declared_json_schema(self):
        import jsonschema
        jsonschema.validate(json.loads((ROOT / "examples/rtl/counter/rtl_coverage_contract.json").read_text()),
                            json.loads((ROOT / "schemas/rtl_coverage_contract.schema.json").read_text()))


if __name__ == "__main__":
    unittest.main()
