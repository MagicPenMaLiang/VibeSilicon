import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT, load_module


backend_module = load_module("vibesilicon_native_backend", "scripts/vivado_backend.py")
evidence = load_module("vibesilicon_backend_evidence", "scripts/evidence_contract.py")


class FakeRunner:
    def __init__(self, returncode=0, stdout="Vivado v2024.2\n", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, self.stderr)


class NativeVivadoBackendContractTests(unittest.TestCase):
    WINDOWS_VIVADO = "D:" + "/toolchain/vivado.bat"

    def make_backend(self, root, runner=None, available=True, max_sessions=1):
        return backend_module.NativeVivadoBackend(
            root=Path(root),
            vivado_bin="vivado",
            runner=runner or FakeRunner(),
            assume_available=available,
            max_sessions=max_sessions,
        )

    def test_capabilities_are_explicit_and_private_by_default(self):
        with tempfile.TemporaryDirectory() as root:
            capabilities = self.make_backend(root).discover_capabilities(probe=False)
        self.assertTrue(capabilities["available"])
        self.assertFalse(capabilities["telemetry"])
        self.assertFalse(capabilities["remote_connection"])
        self.assertFalse(capabilities["remote_ssh"])
        self.assertEqual(capabilities["max_concurrent_sessions"], 1)

    @unittest.skipUnless(backend_module.os.name == "nt", "Windows batch semantics only")
    def test_windows_batch_version_output_accepts_vivado_exit_one(self):
        with tempfile.TemporaryDirectory() as root:
            backend = backend_module.NativeVivadoBackend(
                root=Path(root),
                vivado_bin=self.WINDOWS_VIVADO,
                runner=FakeRunner(returncode=1, stdout="vivado v2024.2 (64-bit)\n"),
                assume_available=True,
            )
            capabilities = backend.discover_capabilities(probe=True)
        self.assertTrue(capabilities["available"])
        self.assertEqual("2024.2", capabilities["vivado_version"])

    @unittest.skipUnless(backend_module.os.name == "nt", "Windows batch semantics only")
    def test_windows_batch_version_probe_rejects_other_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as root:
            backend = backend_module.NativeVivadoBackend(
                root=Path(root),
                vivado_bin=self.WINDOWS_VIVADO,
                runner=FakeRunner(returncode=2, stdout="vivado v2024.2 (64-bit)\n"),
                assume_available=True,
            )
            capabilities = backend.discover_capabilities(probe=True)
        self.assertFalse(capabilities["available"])

    @unittest.skipUnless(backend_module.os.name == "nt", "Windows invocation only")
    def test_windows_without_settings_uses_argument_array(self):
        with tempfile.TemporaryDirectory() as root:
            backend = backend_module.NativeVivadoBackend(
                root=Path(root),
                vivado_bin=self.WINDOWS_VIVADO,
                runner=FakeRunner(),
                assume_available=True,
            )
            command = backend._command(["-version"])
        self.assertEqual(
            [self.WINDOWS_VIVADO, "-version"],
            command,
        )

    def test_session_rejects_workdir_outside_root(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            with self.assertRaises(ValueError):
                self.make_backend(root).start_session(Path(outside))

    def test_unsupported_gui_is_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(backend_module.BackendBlockedError):
                self.make_backend(root).start_session(Path(root), gui=True)

    def test_unsupported_document_search_is_explicitly_blocked(self):
        with tempfile.TemporaryDirectory() as root:
            outcome = self.make_backend(root).search_docs("report_timing_summary", "2024.2")
        self.assertEqual(outcome["status"], "BLOCKED")
        self.assertEqual(outcome["citations"], [])

    def test_session_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as root:
            backend = self.make_backend(root)
            backend.start_session(Path(root))
            with self.assertRaises(backend_module.BackendBlockedError):
                backend.start_session(Path(root))

    def test_successful_command_creates_valid_receipt_manifest_and_audit(self):
        with tempfile.TemporaryDirectory() as root:
            runner = FakeRunner(stdout="Vivado completed")
            backend = self.make_backend(root, runner)
            session = backend.start_session(Path(root), tool_version="2024.2")
            outcome = backend.execute_tcl(session, "puts {hello}\nexit", "R0", 30)
            self.assertEqual(outcome["status"], "PASS")
            self.assertFalse(runner.calls[0][1]["shell"])
            receipt = json.loads((Path(root) / outcome["receipt_path"]).read_text(encoding="utf-8"))
            evidence.validate_receipt(receipt)
            manifest_path = session.session_dir / "manifest_0001.json"
            evidence.validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
            self.assertEqual(receipt["evidence_id"], outcome["evidence_id"])
            self.assertGreaterEqual(len(backend.get_log_messages(session)["messages"]), 2)

    def test_nonzero_exit_is_fail_not_pass(self):
        with tempfile.TemporaryDirectory() as root:
            backend = self.make_backend(root, FakeRunner(returncode=1, stderr="implementation failed"))
            session = backend.start_session(Path(root))
            outcome = backend.execute_tcl(session, "exit 1", "R1", 30)
        self.assertEqual(outcome["status"], "FAIL")
        self.assertFalse(outcome["success"])

    def test_parsed_report_receipt_is_bound_to_raw_command(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            report = root_path / "timing_summary.rpt"
            shutil.copyfile(
                ROOT / "tests/fixtures/vivado/impl_timing_summary.rpt",
                report,
            )
            backend = self.make_backend(root, FakeRunner(stdout="Vivado completed"))
            session = backend.start_session(root_path, tool_version="2024.2")
            raw = backend.execute_tcl(session, "report_timing_summary\nexit", "R0", 30)
            parsed = backend.record_report_evidence(session, raw, report, "timing_report")
            receipt = json.loads(
                (root_path / parsed["receipt_path"]).read_text(encoding="utf-8")
            )
            evidence.validate_receipt(receipt)
            self.assertEqual(receipt["inputs"]["raw_evidence_id"], raw["evidence_id"])
            self.assertEqual(receipt["parser"], {"name": "timing-summary", "schema_version": 1})
            self.assertAlmostEqual(receipt["metrics"]["wns_ns"], 13.220)
            self.assertTrue((root_path / parsed["sidecar_path"]).is_file())

    def test_unapproved_high_risk_and_r4_are_blocked_without_execution(self):
        with tempfile.TemporaryDirectory() as root:
            runner = FakeRunner()
            backend = self.make_backend(root, runner)
            session = backend.start_session(Path(root))
            r2 = backend.execute_tcl(session, "set_property foo bar [current_project]", "R2", 30)
            r4 = backend.execute_tcl(session, "puts forbidden", "R4", 30)
        self.assertEqual(r2["status"], "BLOCKED")
        self.assertEqual(r4["status"], "BLOCKED")
        self.assertEqual(runner.calls, [])

    def test_forbidden_tcl_is_blocked_even_at_low_risk(self):
        with tempfile.TemporaryDirectory() as root:
            runner = FakeRunner()
            backend = self.make_backend(root, runner)
            session = backend.start_session(Path(root))
            outcome = backend.execute_tcl(session, "exec calc", "R0", 30)
        self.assertEqual(outcome["status"], "BLOCKED")
        self.assertEqual(runner.calls, [])

    def test_timeout_is_error_and_session_can_be_stopped(self):
        def timeout_runner(command, **kwargs):
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with tempfile.TemporaryDirectory() as root:
            backend = self.make_backend(root, timeout_runner)
            session = backend.start_session(Path(root))
            outcome = backend.execute_tcl(session, "after 100000", "R0", 1)
            stopped = backend.stop_session(session)
        self.assertEqual(outcome["status"], "ERROR")
        self.assertEqual(stopped["state"], "STOPPED")


if __name__ == "__main__":
    unittest.main()
