"""Multi-file lint must fail closed when tool or elaboration fails."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.quality_gate.rtl_manifest import ManifestError, validate_manifest
from scripts.quality_gate.rtl_project_lint import run_lint


class RtlProjectLintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        rtl = self.root / "project/demo/rtl"
        rtl.mkdir(parents=True)
        (rtl / "top.sv").write_text(
            "module top #(parameter WIDTH=8); child u_child(); endmodule\n", encoding="utf-8"
        )
        (rtl / "child.sv").write_text("module child; endmodule\n", encoding="utf-8")
        self.manifest = self.root / "project/demo/rtl_project_manifest.json"
        self.manifest.write_text(json.dumps({
            "schema_version": 1, "project_root": "project/demo", "target": "asic",
            "source_kinds": ["handwritten"], "top": "top",
            "source_roots": ["project/demo/rtl"],
            "sources": ["project/demo/rtl/top.sv", "project/demo/rtl/child.sv"],
            "headers": [], "include_dirs": ["project/demo/rtl"],
            "defines": {"MODE": "1"}, "parameters": {"WIDTH": "8"},
            "clocks": [], "resets": [],
        }), encoding="utf-8")

    @patch("scripts.quality_gate.rtl_project_lint.subprocess.run")
    def test_pass_uses_complete_manifest_and_hashes(self, execute):
        execute.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="Verilator 5.048", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ]
        with patch("scripts.quality_gate.rtl_project_lint.validate_manifest", wraps=validate_manifest) as check:
            report = run_lint(self.manifest, repository_root=self.root, verilator=sys.executable)
        self.assertEqual(check.call_args.kwargs["repository_root"], self.root)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(set(report["source_sha256"]), {
            "project/demo/rtl/top.sv", "project/demo/rtl/child.sv",
        })
        args = execute.call_args_list[1].args[0]
        self.assertIn("--top-module", args)
        self.assertIn("+define+MODE=1", args)
        self.assertIn("-GWIDTH=8", args)
        self.assertIn("project/demo/rtl/child.sv", args)
        self.assertFalse(execute.call_args_list[1].kwargs.get("shell", False))

    @patch("scripts.quality_gate.rtl_project_lint.subprocess.run")
    def test_cross_file_error_is_not_pass(self, execute):
        execute.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="Verilator 5.048", stderr=""),
            subprocess.CompletedProcess([], 1, stdout="", stderr="missing child"),
        ]
        report = run_lint(self.manifest, repository_root=self.root, verilator=sys.executable)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("missing child", report["stderr"])

    @patch("scripts.quality_gate.rtl_project_lint.subprocess.run")
    def test_timeout_and_unapproved_version_block(self, execute):
        execute.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="Verilator 5.048", stderr=""),
            subprocess.TimeoutExpired([], 1),
        ]
        with self.assertRaisesRegex(ManifestError, "timeout"):
            run_lint(self.manifest, repository_root=self.root, verilator=sys.executable)
        execute.reset_mock()
        execute.side_effect = None
        execute.return_value = subprocess.CompletedProcess([], 0, stdout="Verilator 6.000", stderr="")
        with self.assertRaisesRegex(ManifestError, "unapproved"):
            run_lint(self.manifest, repository_root=self.root, verilator=sys.executable)

    def test_required_tool_missing_blocks(self):
        with self.assertRaisesRegex(ManifestError, "unavailable"):
            run_lint(self.manifest, repository_root=self.root, verilator=str(self.root / "missing.exe"))

    @patch("scripts.quality_gate.rtl_project_lint.subprocess.run")
    def test_v2_excluded_source_is_hashed_but_not_compiled(self, execute):
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["schema_version"] = 2
        excluded = "project/demo/rtl/child.sv"
        data["sources"].remove(excluded)
        data["excluded_sources"] = {excluded: "mutually_exclusive_variant"}
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        execute.side_effect = [
            subprocess.CompletedProcess([], 0, stdout="Verilator 5.048", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ]
        report = run_lint(self.manifest, repository_root=self.root, verilator=sys.executable)
        self.assertEqual(report["status"], "PASS")
        self.assertIn(excluded, report["source_sha256"])
        self.assertNotIn(excluded, execute.call_args_list[1].args[0])

    @patch("scripts.quality_gate.rtl_project_lint.subprocess.run")
    def test_v2_excluded_source_mutation_during_lint_blocks(self, execute):
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data["schema_version"] = 2
        excluded = "project/demo/rtl/child.sv"
        data["sources"].remove(excluded)
        data["excluded_sources"] = {excluded: "mutually_exclusive_variant"}
        self.manifest.write_text(json.dumps(data), encoding="utf-8")

        def result(*args, **kwargs):
            if "--version" in args[0]:
                return subprocess.CompletedProcess([], 0, stdout="Verilator 5.048", stderr="")
            (self.root / excluded).write_text("module changed; endmodule\n", encoding="utf-8")
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

        execute.side_effect = result
        with self.assertRaisesRegex(ManifestError, "changed during"):
            run_lint(self.manifest, repository_root=self.root, verilator=sys.executable)

    @patch("scripts.quality_gate.rtl_project_lint.subprocess.run")
    def test_source_mutated_during_lint_blocks(self, execute):
        source = self.root / "project/demo/rtl/child.sv"

        def result(*args, **kwargs):
            if "--version" in args[0]:
                return subprocess.CompletedProcess([], 0, stdout="Verilator 5.048", stderr="")
            source.write_text("module changed; endmodule\n", encoding="utf-8")
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")

        execute.side_effect = result
        with self.assertRaisesRegex(ManifestError, "changed during"):
            run_lint(self.manifest, repository_root=self.root, verilator=sys.executable)

    def test_real_cross_file_elaboration_when_tool_available(self):
        binary = shutil.which("verilator_bin") or shutil.which("verilator")
        if not binary:
            self.skipTest("Verilator is not installed on this host")
        good = run_lint(self.manifest, repository_root=self.root, verilator=binary)
        self.assertEqual(good["status"], "PASS", good["stderr"])
        (self.root / "project/demo/rtl/child.sv").write_text("module renamed_child; endmodule\n", encoding="utf-8")
        report = run_lint(self.manifest, repository_root=self.root, verilator=binary)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("child", report["stderr"])


if __name__ == "__main__":
    unittest.main()
