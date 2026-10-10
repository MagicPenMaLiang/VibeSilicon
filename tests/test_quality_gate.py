import unittest
from unittest import mock

from tests.support import ROOT, load_module


qg = load_module("vibesilicon_quality_gate", "scripts/quality_gate/post_run_check.py")


class QualityGateStatusTests(unittest.TestCase):
    def summarize(self, check, required=True):
        check["required"] = required
        return qg.summarize({"checks": {"example": check}})["summary"]

    def test_required_skip_fails_closed(self):
        summary = self.summarize(qg._result(qg.SKIP, reason="tool missing"))
        self.assertEqual(summary["overall"], "FAIL")
        self.assertEqual(summary["required_failures"], ["example"])

    def test_required_error_fails_closed(self):
        summary = self.summarize(qg._result(qg.ERROR, reason="timeout"))
        self.assertEqual(summary["overall"], "FAIL")

    def test_optional_skip_is_not_a_failure(self):
        summary = self.summarize(qg._result(qg.SKIP, reason="not applicable"), required=False)
        self.assertEqual(summary["overall"], "PASS")

    def test_optional_error_is_advisory(self):
        summary = self.summarize(qg._result(qg.ERROR, reason="optional unavailable"), required=False)
        self.assertEqual(summary["overall"], "WARN")

    def test_fast_gate_returns_nonzero_for_required_error(self):
        with mock.patch.object(qg, "check_lint", return_value=qg._result(qg.ERROR)), mock.patch.object(
            qg, "check_async_reg", return_value=qg._result(qg.PASS)
        ), mock.patch.object(
            qg, "check_readability", return_value=qg._result(qg.PASS)
        ):
            result = qg.summarize(qg.run_fast(None))
        self.assertEqual(qg.exit_code_for(result), 1)

    def test_readability_is_a_required_fast_gate(self):
        with mock.patch.object(qg, "check_lint", return_value=qg._result(qg.PASS)), mock.patch.object(
            qg, "check_async_reg", return_value=qg._result(qg.PASS)
        ), mock.patch.object(
            qg, "check_readability", return_value=qg._result(qg.FAIL)
        ):
            result = qg.summarize(qg.run_fast(None))
        self.assertIn("readability", result["summary"]["required_failures"])

    def test_readable_fixture_passes_integrated_check(self):
        source = ROOT / "tests/fixtures/rtl_readability/readable_counter.sv"
        result = qg.check_readability(source)
        self.assertEqual(result["status"], qg.PASS, result)

    @unittest.skipUnless(qg.VERILATOR, "Verilator is not installed on this host")
    def test_fast_lint_can_find_installed_standard_library(self):
        source = ROOT / "tests/fixtures/rtl_readability/readable_counter.sv"
        result = qg.check_lint(source)
        self.assertEqual(result["status"], qg.PASS, result)

    def test_warning_does_not_block(self):
        result = qg.summarize(
            {"checks": {"lint": qg._required(qg._result(qg.PASS, level="WARN"), True)}}
        )
        self.assertEqual(result["summary"]["overall"], "WARN")
        self.assertEqual(qg.exit_code_for(result), 0)


if __name__ == "__main__":
    unittest.main()
