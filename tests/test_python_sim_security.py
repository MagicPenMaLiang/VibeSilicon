import tempfile
import unittest
from pathlib import Path

import numpy as np

from tests.support import load_module


python_sim = load_module("vibesilicon_python_sim", "mcp/python-sim-mcp/server.py")


class PythonSimSecurityTests(unittest.TestCase):
    def test_strict_json_array_is_accepted(self):
        array = python_sim._load_array("[[1, 2], [3, 4]]")
        np.testing.assert_array_equal(array, np.array([[1, 2], [3, 4]]))

    def test_python_expression_is_rejected(self):
        with self.assertRaises(ValueError):
            python_sim._load_array("__import__('os').getcwd()")

    def test_non_numeric_json_is_rejected(self):
        with self.assertRaises(ValueError):
            python_sim._load_array('["not", "numeric"]')

    def test_npy_pickle_payload_is_not_allowed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            old_root = python_sim.PROJECT_ROOT
            python_sim.PROJECT_ROOT = root
            try:
                path = root / "object.npy"
                np.save(path, np.array([{"payload": 1}], dtype=object), allow_pickle=True)
                with self.assertRaises(ValueError):
                    python_sim._load_array(str(path))
            finally:
                python_sim.PROJECT_ROOT = old_root

    def test_path_outside_project_is_rejected(self):
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            old_root = python_sim.PROJECT_ROOT
            python_sim.PROJECT_ROOT = Path(root_dir).resolve()
            try:
                outside = Path(outside_dir) / "data.npy"
                np.save(outside, np.array([1, 2, 3]))
                with self.assertRaises(ValueError):
                    python_sim._load_array(str(outside))
            finally:
                python_sim.PROJECT_ROOT = old_root


if __name__ == "__main__":
    unittest.main()
