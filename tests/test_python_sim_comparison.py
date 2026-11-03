"""Exercise exact comparisons through the public MCP tool and real .npy files."""

import ast
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from tests.support import load_module


python_sim = load_module("vibesilicon_python_sim_comparison", "mcp/python-sim-mcp/server.py")


class PythonSimComparisonTests(unittest.TestCase):
    def compare(self, left, right, **tolerances):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            np.save(root / "left.npy", left)
            np.save(root / "right.npy", right)
            with patch.object(python_sim, "PROJECT_ROOT", root):
                output = asyncio.run(python_sim.call_tool("numpy_diff", {
                    "array_a": "left.npy", "array_b": "right.npy", **tolerances,
                }))[0].text
            return output if output.startswith(("ERROR:", "FAIL:")) else ast.literal_eval(output)

    def test_adjacent_uint64_values_above_float_precision_fail(self):
        report = self.compare(np.array([2**53], dtype=np.uint64), np.array([2**53 + 1], dtype=np.uint64))
        self.assertFalse(report["pass"])
        self.assertEqual(report["max_abs_diff"], 1)
        self.assertEqual(report["mean_abs_diff"], 1)
        self.assertEqual(report["mismatch_count"], 1)

    def test_integer_differences_do_not_overflow_or_wrap(self):
        cases = [
            (np.array([0], dtype=np.uint64), np.array([2**64 - 1], dtype=np.uint64), 2**64 - 1),
            (np.array([-2**63], dtype=np.int64), np.array([2**63 - 1], dtype=np.int64), 2**64 - 1),
            (np.array([-1], dtype=np.int64), np.array([2**64 - 1], dtype=np.uint64), 2**64),
        ]
        for left, right, expected in cases:
            with self.subTest(expected=expected):
                report = self.compare(left, right)
                self.assertFalse(report["pass"])
                self.assertEqual(report["max_abs_diff"], expected)

    def test_explicit_tolerances_use_exact_integer_differences(self):
        left, right = np.array([2**53 + 1], dtype=np.uint64), np.array([2**53], dtype=np.uint64)
        self.assertFalse(self.compare(left, right, atol=0.5)["pass"])
        self.assertTrue(self.compare(left, right, atol=1)["pass"])
        self.assertTrue(self.compare(np.array([101]), np.array([100]), rtol=0.02)["pass"])

    def test_mixed_integer_float_zero_tolerance_retains_exact_values(self):
        report = self.compare(np.array([2**53 + 1], dtype=np.uint64), np.array([float(2**53)]))
        self.assertFalse(report["pass"])
        self.assertEqual(report["max_abs_diff"], 1)
        self.assertTrue(self.compare(np.array([2**54], dtype=np.uint64), np.array([float(2**54)]))["pass"])
        error = self.compare(np.array([2**53 + 1], dtype=np.uint64), np.array([float(2**53)]), atol=0.5)
        self.assertTrue(error.startswith("ERROR:"))

    def test_floating_point_diagnostics_preserve_fractional_differences(self):
        report = self.compare(np.array([0.25, 0.5]), np.array([0.5, 0.5]))
        self.assertFalse(report["pass"])
        self.assertEqual(report["max_abs_diff"], 0.25)
        self.assertEqual(report["mean_abs_diff"], 0.125)
        self.assertEqual(report["mismatch_count"], 1)
        self.assertTrue(self.compare(np.array([0.25]), np.array([0.5]), atol=0.3)["pass"])

    def test_nonfinite_negative_and_nonnumeric_tolerances_are_errors(self):
        for tolerance in (-1, float("nan"), float("inf"), True, "0"):
            for name in ("rtol", "atol"):
                with self.subTest(tolerance=tolerance, name=name):
                    error = self.compare(np.array([1]), np.array([1]), **{name: tolerance})
                    self.assertTrue(error.startswith("ERROR:"))

    def test_equal_empty_boolean_and_complex_arrays_pass(self):
        for array in (np.array([], dtype=np.uint64), np.array([True, False]), np.array([1 + 2j])):
            with self.subTest(dtype=array.dtype):
                self.assertTrue(self.compare(array, array)["pass"])

    def test_shape_mismatch_and_nan_never_pass(self):
        self.assertTrue(self.compare(np.array([1]), np.array([[1]])).startswith("FAIL:"))
        with np.errstate(invalid="ignore"):
            report = python_sim._compare_arrays(np.array([np.nan]), np.array([np.nan]), 0, 0)
        self.assertFalse(report["pass"])


if __name__ == "__main__":
    unittest.main()
