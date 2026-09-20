import json
import subprocess
import sys
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
