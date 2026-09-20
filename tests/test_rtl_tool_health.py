"""Required RTL tool probes must fail closed without publishing host paths."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.quality_gate.rtl_tool_health import ToolHealthError, _digest, collect_health


class RtlToolHealthTests(unittest.TestCase):
    def test_binary_digest_is_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tool.exe"
            path.write_bytes(b"test binary")
            self.assertEqual(
                _digest(path),
                "sha256:a8b077366207a4f60b23396338f9e2d65007c87d49e7bcc1f8f7d18db947d085",
            )

    @patch("scripts.quality_gate.rtl_tool_health._version")
    @patch("scripts.quality_gate.rtl_tool_health._resolve")
    def test_report_is_path_free_and_iverilog_is_not_claimed(self, resolve, version):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "tool.exe"
            binary.write_bytes(b"tool")
            resolve.return_value = binary
            version.side_effect = [("git version 2.49.0", 2), ("Verilator 5.048", 5)]
            report = collect_health()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["optional_not_run"], ["iverilog"])
        self.assertNotIn(directory, str(report))
        self.assertEqual(set(report["tools"]), {"python", "git", "verilator"})

    @patch("scripts.quality_gate.rtl_tool_health._resolve", side_effect=ToolHealthError("required tool unavailable: git"))
    def test_missing_tool_blocks(self, _resolve):
        with self.assertRaisesRegex(ToolHealthError, "unavailable"):
            collect_health()

    @patch("scripts.quality_gate.rtl_tool_health._version")
    @patch("scripts.quality_gate.rtl_tool_health._resolve")
    def test_unapproved_verilator_blocks(self, resolve, version):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "tool.exe"
            binary.write_bytes(b"tool")
            resolve.return_value = binary
            version.side_effect = [("git version 2.49.0", 2), ("Verilator 6.000", 6)]
            with self.assertRaisesRegex(ToolHealthError, "unapproved Verilator"):
                collect_health()


if __name__ == "__main__":
    unittest.main()
