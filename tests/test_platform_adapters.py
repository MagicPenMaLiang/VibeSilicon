import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

from tests.support import ROOT, load_module


hook = load_module("vibesilicon_post_edit_hook", "scripts/quality_gate/post_edit_hook.py")
launcher = load_module("vibesilicon_mcp_launcher", "scripts/mcp_launcher.py")


class PlatformAdapterTests(unittest.TestCase):
    def test_claude_hook_extracts_one_rtl_path(self):
        payload = {"tool_input": {"file_path": "rtl/top.sv"}}
        self.assertEqual(hook.extract_edited_rtl(payload, "claude", ROOT), [ROOT / "rtl/top.sv"])

    def test_codex_hook_extracts_added_updated_and_moved_rtl(self):
        payload = {
            "tool_input": {
                "command": "\n".join(
                    [
                        "*** Begin Patch",
                        "*** Update File: rtl/top.sv",
                        "*** Move to: rtl/renamed.sv",
                        "*** Add File: rtl/helper.v",
                        "*** Delete File: rtl/obsolete.v",
                        "*** End Patch",
                    ]
                )
            }
        }
        actual = hook.extract_edited_rtl(payload, "codex", ROOT)
        self.assertEqual(
            actual,
            [ROOT / "rtl/renamed.sv", ROOT / "rtl/helper.v"],
        )

    def test_hook_rejects_paths_outside_repository(self):
        payload = {"tool_input": {"file_path": "../outside.sv"}}
        self.assertEqual(hook.extract_edited_rtl(payload, "claude", ROOT), [])

    def test_team_configs_are_valid_json(self):
        claude = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
        mcp = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        codex_hooks = json.loads((ROOT / ".codex/hooks.json").read_text(encoding="utf-8"))
        self.assertIn("PostToolUse", claude["hooks"])
        self.assertEqual(set(mcp["mcpServers"]), set(launcher.SERVER_PATHS))
        self.assertIn("PostToolUse", codex_hooks["hooks"])

    def test_both_platforms_expose_all_agents_and_skills(self):
        expected_agents = {"architect-fpga", "coder-fpga", "reviewer-fpga", "orchestrator-fpga"}
        expected_skills = set(launcher_path.parent.name for launcher_path in (ROOT / "skills").glob("*/SKILL.md"))
        self.assertEqual({path.stem for path in (ROOT / ".claude/agents").glob("*.md")}, expected_agents)
        self.assertEqual({path.stem for path in (ROOT / ".codex/agents").glob("*.toml")}, expected_agents)
        self.assertEqual({path.parent.name for path in (ROOT / ".claude/skills").glob("*/SKILL.md")}, expected_skills)
        self.assertEqual({path.parent.name for path in (ROOT / ".agents/skills").glob("*/SKILL.md")}, expected_skills)

    def test_mcp_launcher_probe_finds_compatible_runtime(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/mcp_launcher.py"), "python-sim", "--probe"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 0, result)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["runtime"])

    def test_codex_mcp_configured_working_directory_can_find_launcher(self):
        config = (ROOT / ".codex/config.toml").read_text(encoding="utf-8")
        for section in config.split("[mcp_servers.")[1:]:
            name = section.split("]", 1)[0]
            cwd = re.search(r'^cwd = "([^"]+)"$', section, re.MULTILINE).group(1)
            completed = subprocess.run(
                [sys.executable, "scripts/mcp_launcher.py", name, "--probe"],
                cwd=ROOT / cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            with self.subTest(server=name):
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads(completed.stdout)["status"], "PASS")

    def test_claude_mcp_configured_commands_can_find_runtime(self):
        config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
        environment = os.environ.copy()
        # The test runtime has the locked dependencies even in a checkout
        # without its own .venv (for example CI or an isolated worktree).
        environment["VIBESILICON_MCP_PYTHON"] = sys.executable
        for name, server in config["mcpServers"].items():
            # Claude expands the default when its own environment has no
            # CLAUDE_PROJECT_DIR; it injects that variable only in the child.
            args = [arg.replace("${CLAUDE_PROJECT_DIR:-.}", ".") for arg in server["args"]]
            completed = subprocess.run(
                [server["command"], *args, "--probe"], cwd=ROOT,
                env=environment, capture_output=True, text=True, timeout=30,
            )
            with self.subTest(server=name):
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads(completed.stdout)["status"], "PASS")

    def test_claude_configured_hook_checks_edit_payload(self):
        config = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))
        group = config["hooks"]["PostToolUse"][0]
        self.assertRegex("Edit", group["matcher"])
        command = shlex.split(group["hooks"][0]["command"])
        command[0] = sys.executable
        command = [arg.replace("${CLAUDE_PROJECT_DIR}", str(ROOT)) for arg in command]
        for filename, expected_exit in [("rtl/definitely_missing.sv", 2), ("docs/example.md", 0)]:
            payload = {
                "cwd": str(ROOT), "tool_name": "Edit",
                "tool_input": {"file_path": filename},
            }
            completed = subprocess.run(
                command, cwd=ROOT, input=json.dumps(payload), capture_output=True, text=True, timeout=10,
            )
            with self.subTest(filename=filename):
                self.assertEqual(completed.returncode, expected_exit, completed.stderr)

    def test_codex_configured_hook_checks_apply_patch_payload(self):
        config = json.loads((ROOT / ".codex/hooks.json").read_text(encoding="utf-8"))
        group = config["hooks"]["PostToolUse"][0]
        self.assertRegex("apply_patch", group["matcher"])
        command = shlex.split(group["hooks"][0]["command"])
        command[0] = sys.executable
        for filename, expected_exit in [("rtl/definitely_missing.sv", 2), ("docs/example.md", 0)]:
            payload = {
                "cwd": str(ROOT),
                "tool_name": "apply_patch",
                "tool_input": {"command": f"*** Begin Patch\n*** Add File: {filename}\n*** End Patch"},
            }
            completed = subprocess.run(
                command, cwd=ROOT, input=json.dumps(payload), capture_output=True, text=True, timeout=10,
            )
            with self.subTest(filename=filename):
                self.assertEqual(completed.returncode, expected_exit, completed.stderr)

    def test_local_tool_paths_preserve_explicit_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            tool = Path(temp) / "tool.exe"
            tool.touch()
            config = Path(temp) / "mcp-env.json"
            config.write_text(json.dumps({"VIVADO_BIN": str(tool), "VITIS_RUN_BIN": str(tool)}))
            original = {"VIVADO_BIN": "explicit-choice", "PATH": "unchanged"}
            environment = launcher.load_tool_environment(config, original)
            self.assertEqual(environment["VIVADO_BIN"], "explicit-choice")
            self.assertEqual(environment["VITIS_RUN_BIN"], str(tool))
            self.assertEqual(original, {"VIVADO_BIN": "explicit-choice", "PATH": "unchanged"})

    def test_local_tool_config_rejects_unsupported_or_invalid_values(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / "mcp-env.json"
            for values in [[], {"PYTHONPATH": temp}, {"VIVADO_BIN": 42},
                           {"VIVADO_BIN": "relative.exe"}, {"VIVADO_BIN": str(Path(temp) / "missing.exe")}]:
                with self.subTest(values=values):
                    config.write_text(json.dumps(values))
                    with self.assertRaises(ValueError):
                        launcher.load_tool_environment(config, {})

    def test_missing_local_tool_config_is_optional(self):
        with tempfile.TemporaryDirectory() as temp:
            original = {"PATH": "unchanged"}
            self.assertEqual(launcher.load_tool_environment(Path(temp) / "missing.json", original), original)

    def test_codex_mcp_allowlists_match_server_contracts(self):
        config = (ROOT / ".codex/config.toml").read_text(encoding="utf-8")
        self.assertIn('["fxp_sim", "numpy_diff", "load_vectors", "psnr_ssim"]', config)
        self.assertIn('["csim", "csynth", "co_sim", "export"]', config)
        self.assertIn(
            '["synth_design", "place_route", "report_timing", "analyze_checkpoint", "report_cdc", "write_bitstream"]',
            config,
        )
        self.assertNotIn('"run_script"', config)
        self.assertNotIn("VIBESILICON_VIVADO_BACKEND", config)
        claude_mcp = (ROOT / ".mcp.json").read_text(encoding="utf-8")
        self.assertNotIn("VIBESILICON_VIVADO_BACKEND", claude_mcp)

    def test_hook_fails_closed_when_edited_rtl_is_missing(self):
        payload = json.dumps(
            {
                "cwd": str(ROOT),
                "tool_name": "Edit",
                "tool_input": {"file_path": "rtl/definitely_missing.sv"},
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/quality_gate/post_edit_hook.py"),
                "--platform",
                "claude",
            ],
            cwd=ROOT,
            input=payload,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("does not exist", completed.stderr)


if __name__ == "__main__":
    unittest.main()
