import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import fpga_board as board
from scripts.evidence_contract import content_id, sha256_file
from scripts.vivado_backend import NativeVivadoBackend
from tests.support import ROOT


class BoardAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.external = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.external.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.outside = Path(self.external.name).resolve()
        self.request = self.make_request("program")

    def make_request(self, operation):
        artifacts = {}
        kinds = ["bitstream"] + (["probes"] if operation == "capture" else ["image"] if operation == "flash" else [])
        for kind in kinds:
            path = self.root / (kind + board.ARTIFACT_SUFFIXES[kind])
            path.write_bytes(b"neutral fixture; never a programmable image")
            artifacts[kind] = {"path": path.name, "sha256": sha256_file(path)}
        binding = {"schema_version": 1, "device_part": "xc7z020"} | {
            f"{kind}_sha256": item["sha256"] for kind, item in artifacts.items()
        }
        path = self.root / "build.json"
        path.write_text(json.dumps(binding))
        artifacts["build"] = {"path": path.name, "sha256": sha256_file(path)}
        return {"schema_version": 1, "operation": operation,
                "device": {"target": "localhost:3121/vendor/cable/EXACT_SERIAL", "name": "xc7z020_1", "part": "xc7z020"},
                "artifacts": artifacts, "options": {"core": "top/ila_0", "depth": 1024} if operation == "capture" else
                {"flash_part": "reviewed-spi-part"} if operation == "flash" else {}, "timeout_seconds": 120}

    def approve(self, request=None, *, expires=None):
        approval = {"schema_version": 1, "request_id": board.request_id(request or self.request),
                    "operator": "test operator", "reviewer": "independent test reviewer",
                    "expires_at": (expires or datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
        path = self.outside / "approval.json"
        path.write_text(json.dumps(approval))
        return path, {"VIBESILICON_BOARD_APPROVAL_SHA256": sha256_file(path)}

    def test_preview_never_initializes_backend_or_touches_board(self):
        with patch.object(board, "NativeVivadoBackend") as backend:
            report = board.run_request(self.root, self.request)
        self.assertEqual(report["status"], "PREVIEW")
        self.assertFalse(report["hardware_validated"])
        self.assertFalse((self.root / ".vibesilicon").exists())
        backend.assert_not_called()

    def test_missing_approval_cannot_execute(self):
        with patch.object(board, "NativeVivadoBackend") as backend, self.assertRaises(ValueError):
            board.run_request(self.root, self.request, execute=True)
        backend.assert_not_called()

    def test_output_cannot_escape_owned_directory(self):
        with self.assertRaises(ValueError):
            board.generate_tcl(self.root, self.request, self.outside / "board-output")

    def test_approval_is_exact_external_pinned_and_not_expired(self):
        approval, env = self.approve()
        with patch.dict(os.environ, env):
            self.assertEqual(board.verify_approval(self.root, self.request, approval), env["VIBESILICON_BOARD_APPROVAL_SHA256"])
            changed = copy.deepcopy(self.request)
            changed["operation"] = "flash"
            with self.assertRaises(ValueError):
                board.verify_approval(self.root, changed, approval)
            local = self.root / "approval.json"
            local.write_bytes(approval.read_bytes())
            with self.assertRaises(ValueError):
                board.verify_approval(self.root, self.request, local)
        with patch.dict(os.environ, {"VIBESILICON_BOARD_APPROVAL_SHA256": ""}), self.assertRaises(ValueError):
            board.verify_approval(self.root, self.request, approval)
        expired, env = self.approve(expires=datetime.now(timezone.utc) - timedelta(minutes=1))
        with patch.dict(os.environ, env), self.assertRaises(ValueError):
            board.verify_approval(self.root, self.request, expired)

    def test_artifact_and_build_binding_cannot_be_changed(self):
        (self.root / "bitstream.bit").write_bytes(b"different image")
        with self.assertRaises(ValueError):
            board.run_request(self.root, self.request)
        self.request["artifacts"]["bitstream"]["sha256"] = sha256_file(self.root / "bitstream.bit")
        with self.assertRaisesRegex(ValueError, "build/artifact"):
            board.run_request(self.root, self.request)

    def test_injection_extra_fields_remote_target_and_bad_depth_rejected(self):
        for field, value in (("name", "dev;exec bad"), ("target", "remote:3121/vendor/cable"),
                             ("name", "[exec bad]"), ("target", "localhost:3121/*")):
            request = copy.deepcopy(self.request)
            request["device"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                board.run_request(self.root, request)
        request = self.request | {"tcl": "exec bad"}
        with self.assertRaises(ValueError):
            board.run_request(self.root, request)
        request = self.make_request("capture")
        request["options"]["depth"] = 1000
        with self.assertRaises(ValueError):
            board.run_request(self.root, request)

    def test_lock_excludes_other_checkout_and_releases_on_error(self):
        with patch("tempfile.gettempdir", return_value=str(self.outside)):
            with self.assertRaisesRegex(RuntimeError, "test error"):
                with board.board_lock(self.root):
                    with self.assertRaises(ValueError):
                        with board.board_lock(self.outside):
                            pass
                    raise RuntimeError("test error")
            with board.board_lock(self.root):
                pass

    def interpreter(self, request, *, wrong_part=False, wrong_target=False):
        try:
            import tkinter
            interpreter = tkinter.Tcl()
        except (ImportError, RuntimeError):
            self.skipTest("Tcl interpreter unavailable")
        writes = []
        interpreter.createcommand("get_hw_targets", lambda: "wrong-target" if wrong_target else request["device"]["target"])
        interpreter.createcommand("get_hw_devices", lambda *args: "device-object")
        interpreter.createcommand("get_hw_ilas", lambda *args: "ila-object")
        interpreter.createcommand("get_cfgmem_parts", lambda: request["options"].get("flash_part", "none"))
        properties = {"NAME": request["device"]["name"], "PART": "xc7z010" if wrong_part else request["device"]["part"],
                      "CELL_NAME": request["options"].get("core", "none"), "PROGRAM.HW_CFGMEM": "memory-object",
                      "PROGRAM.HW_CFGMEM_BITFILE": "vendor-helper.bit"}
        interpreter.createcommand("get_property", lambda name, obj: properties[name])
        for command in ("open_hw_manager", "connect_hw_server", "current_hw_target", "open_hw_target", "current_hw_device",
                        "set_property", "refresh_hw_device", "reset_hw_ila", "run_hw_ila", "wait_on_hw_ila",
                        "close_hw_target", "disconnect_hw_server", "close_hw_manager", "puts", "exit", "create_hw_cfgmem", "create_hw_bitstream"):
            interpreter.createcommand(command, lambda *args: "")
        for command in ("program_hw_devices", "program_hw_cfgmem"):
            interpreter.createcommand(command, lambda *args, name=command: writes.append(name) or "")
        interpreter.createcommand("upload_hw_ila_data", lambda *args: "sample-object")
        def capture(*args):
            path = Path(args[1])
            path.write_text("Sample,value\n0,1\n")
            return str(path)
        interpreter.createcommand("write_hw_ila_data", capture)
        return interpreter, writes

    def test_generated_tcl_wrong_identity_stops_before_programming(self):
        for wrong in ("part", "target"):
            with self.subTest(wrong=wrong):
                interpreter, writes = self.interpreter(self.request, wrong_part=wrong == "part", wrong_target=wrong == "target")
                text = board.generate_tcl(self.root, self.request, self.root / ".vibesilicon/board/test")
                with self.assertRaises(Exception):
                    interpreter.eval(text)
                self.assertEqual(writes, [])

    def test_fixed_tcl_program_capture_and_flash_receipts(self):
        for operation in ("program", "capture", "flash"):
            with self.subTest(operation=operation):
                request = self.make_request(operation)
                interpreter, writes = self.interpreter(request)
                def runner(argv, **kwargs):
                    if "-version" in argv:
                        return subprocess.CompletedProcess(argv, 0, "Vivado v2024.2", "")
                    tcl = Path(argv[argv.index("-source") + 1]).read_text(encoding="utf-8")
                    try:
                        interpreter.eval(tcl)
                        return subprocess.CompletedProcess(argv, 0, "VIBESILICON_BOARD_OPERATION_COMPLETE\n", "")
                    except Exception as exc:
                        return subprocess.CompletedProcess(argv, 1, "", str(exc))
                backend = NativeVivadoBackend(root=self.root, vivado_bin="vivado", assume_available=True, runner=runner)
                approval, env = self.approve(request)
                with patch.dict(os.environ, env), patch("tempfile.gettempdir", return_value=str(self.outside)):
                    evidence = board.run_request(self.root, request, execute=True, approval_file=approval, backend=backend)
                self.assertEqual(evidence["status"], "PASS", evidence)
                self.assertFalse(evidence["hardware_validated"])
                board.verify_board_evidence(self.root, evidence)
                self.assertEqual(writes, ["program_hw_devices"] + (["program_hw_cfgmem"] if operation == "flash" else []))
                forged = copy.deepcopy(evidence)
                forged["execution"]["stdout_tail"] = "changed"
                forged["evidence_id"] = content_id(forged, "evidence_id")
                with self.assertRaises(ValueError):
                    board.verify_board_evidence(self.root, forged)

    def test_soc_input_preflight_does_not_pass_board_checkpoints(self):
        artifact = self.request["artifacts"]["build"]
        plan = {"schema_version": 1, "family": "ps7", "part": "xc7z020clg400-1", "preset": artifact,
                "initialization": artifact, "interface_contract": artifact,
                "board_tests": ["identity", "boot_log", "ddr_memory", "peripheral", "clock_reset"]}
        report = board.validate_soc(self.root, plan)
        self.assertEqual(set(report["checkpoints"].values()), {"BLOCKED"})
        self.assertFalse(report["hardware_validated"])
        with self.assertRaises(ValueError):
            board.validate_soc(self.root, plan | {"family": "mpsoc"})
        report = board.validate_soc(self.root, plan | {"family": "mpsoc", "part": "xczu9eg-ffvb1156-2-e"})
        self.assertEqual(report["status"], "PASS")

    def test_board_request_matches_schema(self):
        import jsonschema
        schema = json.loads((ROOT / "schemas/fpga_board_request.schema.json").read_text())
        for operation in ("program", "capture", "flash"):
            jsonschema.validate(self.make_request(operation), schema)
        for template, schema_name in (("fpga_board_request", "fpga_board_request"), ("fpga_soc_plan", "fpga_soc_plan")):
            document = json.loads((ROOT / f"templates/{template}.json.tpl").read_text())
            jsonschema.validate(document, json.loads((ROOT / f"schemas/{schema_name}.schema.json").read_text()))
        path, _ = self.approve()
        jsonschema.validate(json.loads(path.read_text()),
                            json.loads((ROOT / "schemas/fpga_board_approval.schema.json").read_text()),
                            format_checker=jsonschema.FormatChecker())


if __name__ == "__main__":
    unittest.main()
