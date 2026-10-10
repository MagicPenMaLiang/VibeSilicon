"""Exercise the public OpenCode hook with the documented event payload."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
HARNESS = """
import { pathToFileURL } from 'node:url';
const mod = await import(pathToFileURL(process.argv[1]).href);
const exports = Object.values(mod);
if (exports.length !== 1 || typeof exports[0] !== 'function') {
  throw new Error('OpenCode legacy loading requires only plugin factories');
}
const hooks = await exports[0]({directory: process.argv[2]});
try {
  await hooks['tool.execute.after'](JSON.parse(process.argv[3]), {title: 'edit', output: '', metadata: {}});
  console.log(JSON.stringify({ok: true}));
} catch (error) {
  console.log(JSON.stringify({ok: false, error: error.message}));
}
"""


@unittest.skipUnless(NODE, "Node.js is required for OpenCode plugin regression tests")
class OpenCodePluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vibesilicon-opencode-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plugin = self.root / "plugin.mjs"
        self.plugin.write_bytes((ROOT / ".opencode/plugins/vibesilicon-quality-gate.js").read_bytes())
        checker = self.root / "scripts/quality_gate/post_run_check.py"
        checker.parent.mkdir(parents=True)
        checker.write_text(
            "import json, pathlib, sys\n"
            "source = pathlib.Path(sys.argv[sys.argv.index('--source') + 1])\n"
            "with open('invocations.jsonl', 'a') as log:\n"
            "    log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "if not source.is_file() or source.name.startswith('bad'):\n"
            "    print('required check failed', file=sys.stderr)\n"
            "    sys.exit(1)\n",
            encoding="utf-8",
        )
        (self.root / "good.sv").write_text("module good; endmodule\n", encoding="utf-8")
        (self.root / "bad.sv").write_text("module bad; endmodule\n", encoding="utf-8")

    def hook(self, tool, args, python=None):
        env = os.environ.copy()
        env["VIBESILICON_PYTHON"] = python or sys.executable
        completed = subprocess.run(
            [NODE, "--input-type=module", "-e", HARNESS, str(self.plugin), str(self.root),
             json.dumps({"tool": tool, "sessionID": "test", "callID": "test", "args": args})],
            env=env, capture_output=True, text=True, timeout=25, check=True,
        )
        return json.loads(completed.stdout)

    def invocations(self):
        path = self.root / "invocations.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_after_input_args_runs_gate_and_keeps_report_local(self):
        self.assertTrue(self.hook("write", {"filePath": "good.sv"})["ok"])
        calls = self.invocations()
        self.assertEqual(len(calls), 1)
        self.assertEqual(Path(calls[0][calls[0].index("--source") + 1]), self.root / "good.sv")
        report = Path(calls[0][calls[0].index("--output") + 1])
        self.assertEqual(report.parent, self.root / ".vibesilicon/reports")

    def test_failed_check_rejects_edit(self):
        result = self.hook("edit", {"filePath": "bad.sv"})
        self.assertFalse(result["ok"])
        self.assertIn("required check failed", result["error"])

    def test_missing_source_rejects_edit(self):
        self.assertFalse(self.hook("write", {"filePath": "missing.sv"})["ok"])

    def test_missing_python_rejects_edit(self):
        self.assertFalse(self.hook("write", {"filePath": "good.sv"}, str(self.root / "absent-python"))["ok"])

    def test_outside_workspace_is_rejected_before_gate(self):
        self.assertFalse(self.hook("edit", {"filePath": "../outside.sv"})["ok"])
        self.assertEqual(self.invocations(), [])

    def test_patch_move_checks_destination_once_and_ignores_delete(self):
        patch = ("*** Begin Patch\n*** Update File: old.sv\n*** Move to: good.sv\n"
                 "@@\n-old\n+new\n*** Delete File: bad.sv\n*** Update File: good.sv\n"
                 "@@\n-old\n+new\n*** End Patch")
        self.assertTrue(self.hook("apply_patch", {"patchText": patch})["ok"])
        self.assertEqual(len(self.invocations()), 1)

    def test_non_rtl_and_non_edit_tool_do_not_run_gate(self):
        self.assertTrue(self.hook("write", {"filePath": "README.md"})["ok"])
        self.assertTrue(self.hook("read", {"filePath": "bad.sv"})["ok"])
        self.assertEqual(self.invocations(), [])

    def test_header_patch_is_checked(self):
        (self.root / "good.svh").write_text("`define WIDTH 8\n", encoding="utf-8")
        self.assertTrue(self.hook("apply_patch", {"patchText": "*** Add File: good.svh\n+`define WIDTH 8"})["ok"])
        self.assertEqual(len(self.invocations()), 1)

    def test_symlink_outside_workspace_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="vibesilicon-outside-") as outside:
            target = Path(outside) / "outside.sv"
            target.write_text("module outside; endmodule\n", encoding="utf-8")
            try:
                (self.root / "linked.sv").symlink_to(target)
            except OSError:
                self.skipTest("creating symlinks requires OS privileges")
            self.assertFalse(self.hook("write", {"filePath": "linked.sv"})["ok"])
            self.assertEqual(self.invocations(), [])


if __name__ == "__main__":
    unittest.main()
