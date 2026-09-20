import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import load_module


vivado = load_module("vibesilicon_vivado_mcp", "mcp/vivado-mcp/server.py")


class VivadoMcpSecurityTests(unittest.TestCase):
    def test_project_path_must_stay_inside_root(self):
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            old_root = vivado.PROJECT_ROOT
            vivado.PROJECT_ROOT = Path(root_dir).resolve()
            try:
                outside = Path(outside_dir) / "outside.xpr"
                outside.write_text("", encoding="utf-8")
                with self.assertRaises(ValueError):
                    vivado._resolve_project_path(str(outside))
            finally:
                vivado.PROJECT_ROOT = old_root

    def test_tcl_identifier_injection_is_rejected(self):
        for value in ["top; exec calc", "top\nexit", "[exec whoami]"]:
            with self.assertRaises(ValueError):
                vivado._validate_identifier(value, "top")

    def test_output_path_must_stay_inside_root(self):
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            old_root = vivado.PROJECT_ROOT
            vivado.PROJECT_ROOT = Path(root_dir).resolve()
            try:
                outside = Path(outside_dir) / "timing.json"
                with self.assertRaises(ValueError):
                    vivado._resolve_output_path(str(outside), Path(root_dir) / "default.json", ".json")
            finally:
                vivado.PROJECT_ROOT = old_root

    def test_bitstream_name_cannot_escape_directory(self):
        for value in ["../design.bit", "subdir/design.bit", "design.txt", "x;exit.bit"]:
            with self.assertRaises(ValueError):
                vivado._validate_bitstream_name(value)

    def test_arbitrary_script_tool_is_hidden_by_default(self):
        tools = asyncio.run(vivado.list_tools())
        self.assertNotIn("run_script", {tool.name for tool in tools})

    def test_vivado_process_uses_shell_false(self):
        source = (Path(__file__).resolve().parents[1] / "scripts" / "vivado_backend.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("shell=False", source)
        self.assertNotIn("shell=True", source)

    def test_backend_capabilities_are_published(self):
        tools = asyncio.run(vivado.list_tools())
        self.assertIn("backend_capabilities", {tool.name for tool in tools})

    def test_backend_capabilities_keep_remote_features_disabled(self):
        content = asyncio.run(vivado.call_tool("backend_capabilities", {"probe": False}))
        capabilities = json.loads(content[0].text)
        self.assertFalse(capabilities["telemetry"])
        self.assertFalse(capabilities["remote_connection"])
        self.assertFalse(capabilities["remote_ssh"])

    def test_checkpoint_analysis_is_read_only_r0(self):
        with tempfile.TemporaryDirectory() as root_dir:
            old_root = vivado.PROJECT_ROOT
            root = Path(root_dir).resolve()
            vivado.PROJECT_ROOT = root
            checkpoint = root / "post_route.dcp"
            checkpoint.write_bytes(b"checkpoint")
            captured = {}

            def fake_run(tcl_path, cwd, timeout=3600, risk_class="R1", reports=None):
                captured.update(
                    tcl=tcl_path.read_text(encoding="utf-8"),
                    cwd=cwd,
                    risk_class=risk_class,
                    reports=reports,
                )
                analysis_dir = root / ".vibesilicon" / "vivado" / "dcp_analysis"
                for name in ("timing_summary.rpt", "critical_paths.rpt", "clock_interaction.rpt"):
                    (analysis_dir / name).write_text("report\n", encoding="utf-8")
                return {
                    "status": "PASS",
                    "report_evidence": {
                        "timing_report": {
                            "evidence_id": "sha256:" + "a" * 64,
                            "metrics": {"wns_ns": -0.1, "whs_ns": 0.02},
                        }
                    },
                }

            try:
                with patch.object(vivado, "_run_vivado", side_effect=fake_run):
                    content = asyncio.run(
                        vivado.call_tool(
                            "analyze_checkpoint",
                            {"checkpoint_path": str(checkpoint), "max_paths": 5},
                        )
                    )
            finally:
                vivado.PROJECT_ROOT = old_root

        result = json.loads(content[0].text)
        self.assertEqual(captured["risk_class"], "R0")
        self.assertIn("open_checkpoint", captured["tcl"])
        for forbidden in ("write_checkpoint", "set_property", "launch_runs", "route_design"):
            self.assertNotIn(forbidden, captured["tcl"])
        self.assertFalse(result["analysis"]["mutation_performed"])


if __name__ == "__main__":
    unittest.main()
