import asyncio
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.fpga_reports import report_plan, collect_bundle, verify_bundle, REPORTS
from scripts.vivado_backend import NativeVivadoBackend
from tests.support import ROOT, load_module

vivado = load_module("vibesilicon_reports_mcp", "mcp/vivado-mcp/server.py")


class ReportCollectionTests(unittest.TestCase):
    def make_bundle(self, root):
        (root / "design.dcp").write_bytes(b"neutral checkpoint fixture")
        plan = report_plan(root, "design.dcp", ".vibesilicon/reports/test")
        output = root / ".vibesilicon/reports/test"
        output.mkdir(parents=True)
        for kind, relative in plan["reports"].items():
            source = ROOT / f"tests/fixtures/vivado/impl_{kind if kind != 'timing' else 'timing_summary'}.rpt"
            if kind == "utilization":
                source = ROOT / "tests/fixtures/vivado/impl_util.rpt"
            (root / relative).write_bytes(source.read_bytes() if source.is_file() else b"neutral raw report fixture\n")
        backend = NativeVivadoBackend(root=root, vivado_bin="vivado", assume_available=True,
                                      runner=lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "reports collected", ""))
        session = backend.start_session(output, tool_version="2024.2")
        result = backend.execute_tcl(session, plan["tcl"], "R0", 60)
        backend.stop_session(session)
        return collect_bundle(root, plan, result)

    def test_collection_pass_is_distinct_from_design_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            bundle = self.make_bundle(root)
            self.assertEqual(bundle["status"], "PASS", bundle["errors"])
            self.assertGreater(bundle["artifacts"]["drc"]["metrics"]["critical"], 0)
            self.assertEqual(verify_bundle(root, bundle), bundle)
            self.assertEqual(set(bundle["artifacts"]), set(REPORTS) | {"check_timing"})

    def test_changed_checkpoint_report_and_raw_log_rejected(self):
        for kind in ("checkpoint", "report", "log"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                bundle = self.make_bundle(root)
                relative = {"checkpoint": bundle["plan"]["checkpoint"],
                            "report": bundle["artifacts"]["timing"]["path"],
                            "log": bundle["execution"]["log_path"]}[kind]
                with (root / relative).open("ab") as stream:
                    stream.write(b"changed")
                with self.assertRaises(ValueError):
                    verify_bundle(root, bundle)

    def test_forged_pass_and_empty_report_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            bundle = self.make_bundle(root)
            execution = copy.deepcopy(bundle["execution"])
            execution["stdout_tail"] = "forged completion"
            self.assertEqual(collect_bundle(root, bundle["plan"], execution)["status"], "BLOCKED")
            (root / bundle["artifacts"]["power"]["path"]).write_text("")
            self.assertEqual(collect_bundle(root, bundle["plan"], bundle["execution"])["status"], "BLOCKED")

    def test_plan_refuses_escape_and_reused_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "design.dcp").write_bytes(b"dcp")
            for destination in ("../outside", "user/output", ".vibesilicon/reports"):
                if destination == ".vibesilicon/reports":
                    (root / destination).mkdir(parents=True)
                with self.subTest(destination=destination), self.assertRaises(ValueError):
                    report_plan(root, "design.dcp", destination)

    def test_mcp_additional_arguments_never_execute(self):
        with patch.object(vivado, "_run_vivado") as run:
            reply = asyncio.run(vivado.call_tool("collect_reports", {"checkpoint_path": "x.dcp", "tcl": "exec bad"}))
            self.assertIn("error", json.loads(reply[0].text))
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
