import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.evidence_contract import content_id
from tests.support import ROOT, load_module


reports = load_module("vibesilicon_vivado_reports", "scripts/quality_gate/vivado_reports.py")
gate = load_module("vibesilicon_gate_with_reports", "scripts/quality_gate/post_run_check.py")
report_evidence = load_module(
    "vibesilicon_vivado_evidence", "scripts/quality_gate/vivado_evidence.py"
)
FIXTURE_REPORTS = ROOT / "tests/fixtures/vivado"


class VivadoReportParserTests(unittest.TestCase):
    def test_synthetic_timing_is_parsed(self):
        result = reports.parse_timing(FIXTURE_REPORTS / "impl_timing_summary.rpt")
        self.assertEqual(result["schema_version"], 1)
        self.assertAlmostEqual(result["metrics"]["wns_ns"], 13.220)
        self.assertAlmostEqual(result["metrics"]["whs_ns"], 0.028)
        self.assertTrue(result["metrics"]["constraints_met"])
        self.assertEqual(len(result["sha256"]), 64)

    def test_empty_cdc_report_means_zero_paths(self):
        result = reports.parse_cdc(FIXTURE_REPORTS / "impl_cdc.rpt")
        self.assertEqual(result["metrics"]["critical"], 0)
        self.assertEqual(result["metrics"]["violations"], 0)

    def test_synthetic_utilization_is_parsed(self):
        result = reports.parse_utilization(FIXTURE_REPORTS / "impl_util.rpt")
        self.assertEqual(result["metrics"]["lut_used"], 1634)
        self.assertEqual(result["metrics"]["bram_used"], 2)
        self.assertAlmostEqual(result["metrics"]["bram_pct"], 1.39)

    def test_sub_one_hundredth_utilization_is_parsed_conservatively(self):
        content = """Utilization Design Information
| CLB LUTs      | 6 | 0 | 0 | 117120 | <0.01 |
| CLB Registers | 8 | 0 | 0 | 234240 | <0.01 |
| Block RAM Tile| 0 | 0 | 0 | 144    | 0.00  |
| DSPs          | 0 | 0 | 0 | 1248   | 0.00  |
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "utilization.rpt"
            path.write_text(content, encoding="utf-8")
            result = reports.parse_utilization(path)
        self.assertEqual(6, result["metrics"]["lut_used"])
        self.assertEqual(8, result["metrics"]["ff_used"])
        self.assertEqual(0.01, result["metrics"]["lut_pct"])

    def test_seven_series_slice_utilization_aliases_are_parsed(self):
        content = """Utilization Design Information
| Slice LUTs*     | 7 | 0 | 0 | 20800 | 0.03 |
| Slice Registers | 8 | 0 | 0 | 41600 | 0.02 |
| Block RAM Tile  | 0 | 0 | 0 | 50    | 0.00 |
| DSPs            | 0 | 0 | 0 | 90    | 0.00 |
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "utilization.rpt"
            path.write_text(content, encoding="utf-8")
            result = reports.parse_utilization(path)
        self.assertEqual(7, result["metrics"]["lut_used"])
        self.assertEqual(8, result["metrics"]["ff_used"])

    def test_synthetic_drc_preserves_critical_warning(self):
        result = reports.parse_drc(FIXTURE_REPORTS / "impl_drc.rpt")
        self.assertEqual(result["metrics"]["checks_found"], 5)
        self.assertEqual(result["metrics"]["critical"], 1)
        self.assertEqual(result["metrics"]["warning"], 4)

    def test_truncated_report_is_an_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "timing.rpt"
            path.write_text("Design Timing Summary\nWNS(ns) TNS(ns)\n", encoding="utf-8")
            with self.assertRaises(reports.ReportParseError):
                reports.parse_timing(path)

    def test_negative_timing_is_not_constraints_met(self):
        content = """Design Timing Summary
WNS(ns) TNS(ns) TNS Failing Endpoints Total WHS(ns) THS(ns) Hold Failing Endpoints Total
------- ------- --------------------- ----- ------- ------- ---------------------- -----
-0.125 -3.500 4 10 0.010 0.000 0 10
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "timing.rpt"
            path.write_text(content, encoding="utf-8")
            result = reports.parse_timing(path)
            self.assertFalse(result["metrics"]["constraints_met"])

    def test_gate_uses_canonical_reports_and_blocks_critical_drc(self):
        timing = gate.check_timing(FIXTURE_REPORTS)
        cdc = gate.check_cdc(FIXTURE_REPORTS)
        implementation = gate.check_impl(FIXTURE_REPORTS)
        self.assertEqual(timing["status"], gate.PASS)
        self.assertEqual(cdc["status"], gate.PASS)
        self.assertEqual(implementation["status"], gate.FAIL)
        self.assertIn("critical_drc", implementation["blockers"])
        self.assertEqual(timing["evidence"]["receipt_source"], "legacy-import")
        self.assertEqual(timing["evidence"]["parser"]["name"], "timing-summary")

    def test_legacy_import_receipt_is_deterministic_and_verified(self):
        report = FIXTURE_REPORTS / "impl_timing_summary.rpt"
        first = report_evidence.create_legacy_import_evidence(
            report, root=ROOT, kind="timing_report"
        )["receipt"]
        second = report_evidence.create_legacy_import_evidence(
            report, root=ROOT, kind="timing_report"
        )["receipt"]
        self.assertEqual(first["evidence_id"], second["evidence_id"])
        verified = report_evidence.verify_report_evidence(
            first, report, root=ROOT, kind="timing_report"
        )
        self.assertEqual(verified["backend"], "legacy-import")

    def test_tampered_report_is_rejected_by_receipt_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "timing.rpt"
            shutil.copyfile(FIXTURE_REPORTS / "impl_timing_summary.rpt", report)
            receipt = report_evidence.create_legacy_import_evidence(
                report, root=root, kind="timing_report"
            )["receipt"]
            report.write_text(report.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash does not match"):
                report_evidence.verify_report_evidence(
                    receipt, report, root=root, kind="timing_report"
                )

    def test_tampered_sidecar_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "cdc.rpt"
            shutil.copyfile(FIXTURE_REPORTS / "impl_cdc.rpt", report)
            receipt = report_evidence.create_legacy_import_evidence(
                report, root=root, kind="cdc_report"
            )["receipt"]
            receipt["metrics"]["critical"] = 99
            sidecar = report.with_suffix(report.suffix + ".receipt.json")
            sidecar.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "evidence_id"):
                report_evidence.load_verified_report(report, root=root, kind="cdc_report")

    def test_wrong_parser_version_is_rejected(self):
        report = FIXTURE_REPORTS / "impl_cdc.rpt"
        receipt = report_evidence.create_legacy_import_evidence(
            report, root=ROOT, kind="cdc_report"
        )["receipt"]
        receipt["parser"]["schema_version"] = 2
        receipt["evidence_id"] = content_id(receipt, "evidence_id")
        with self.assertRaisesRegex(ValueError, "parser must be"):
            report_evidence.verify_report_evidence(receipt, report, root=ROOT, kind="cdc_report")

    def test_gate_applies_timing_threshold_after_receipt_verification(self):
        content = """Design Timing Summary
WNS(ns) TNS(ns) TNS Failing Endpoints Total WHS(ns) THS(ns) Hold Failing Endpoints Total
------- ------- --------------------- ----- ------- ------- ---------------------- -----
-0.125 -3.500 4 10 0.010 0.000 0 10
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = root / "timing_summary.rpt"
            report.write_text(content, encoding="utf-8")
            old_root = gate.PROJECT_ROOT
            gate.PROJECT_ROOT = root
            try:
                outcome = gate.check_timing(root)
            finally:
                gate.PROJECT_ROOT = old_root
        self.assertEqual(outcome["status"], gate.FAIL)
        self.assertEqual(outcome["evidence"]["receipt_source"], "legacy-import")

    def test_gate_missing_reports_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(gate.check_timing(Path(temp_dir))["status"], gate.ERROR)
            self.assertEqual(gate.check_cdc(Path(temp_dir))["status"], gate.ERROR)
            self.assertEqual(gate.check_impl(Path(temp_dir))["status"], gate.ERROR)


if __name__ == "__main__":
    unittest.main()
