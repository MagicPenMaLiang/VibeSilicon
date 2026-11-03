#!/usr/bin/env python3
"""Reviewed, exact-target native FPGA operations; default CLI action is preview."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid

from scripts.evidence_contract import content_id, sha256_file
from scripts.fpga_reports import bounded, tcl_word, verify_execution
from scripts.vivado_backend import NativeVivadoBackend

IDENTITY = re.compile(r"[A-Za-z0-9_./:-]{1,240}\Z")
PART = re.compile(r"xc[a-z0-9-]{3,80}\Z")
ARTIFACT_SUFFIXES = {"bitstream": ".bit", "probes": ".ltx", "image": ".mcs", "build": ".json"}


def exact_fields(value: dict, fields: set[str], kind: str) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"invalid {kind} fields")


def validate_request(root: Path, request: dict) -> dict:
    exact_fields(request, {"schema_version", "operation", "device", "artifacts", "options", "timeout_seconds"}, "board request")
    if type(request["schema_version"]) is not int or request["schema_version"] != 1:
        raise ValueError("unsupported board schema")
    operation = request["operation"]
    if operation not in {"program", "capture", "flash"}:
        raise ValueError("unsupported board operation")
    exact_fields(request["device"], {"target", "name", "part"}, "device")
    for value in request["device"].values():
        if not isinstance(value, str) or not IDENTITY.fullmatch(value):
            raise ValueError("invalid exact device identity")
    if not PART.fullmatch(request["device"]["part"]):
        raise ValueError("invalid hardware silicon part")
    if not request["device"]["target"].startswith("localhost:3121/"):
        raise ValueError("only the declared local hardware server is supported")
    timeout = request["timeout_seconds"]
    if type(timeout) is not int or not 10 <= timeout <= 600:
        raise ValueError("board timeout must be 10..600 seconds")
    required = {"bitstream", "build"} | ({"probes"} if operation == "capture" else {"image"} if operation == "flash" else set())
    exact_fields(request["artifacts"], required, "artifacts")
    paths = {}
    for kind, artifact in request["artifacts"].items():
        exact_fields(artifact, {"path", "sha256"}, "artifact")
        path = bounded(root, artifact["path"], suffix=ARTIFACT_SUFFIXES[kind])
        if path.stat().st_size == 0 or artifact["sha256"] != sha256_file(path):
            raise ValueError(f"empty or changed {kind} artifact")
        paths[kind] = path
    build = json.loads(paths["build"].read_text(encoding="utf-8"))
    expected = {"schema_version", "device_part"} | {f"{kind}_sha256" for kind in required - {"build"}}
    exact_fields(build, expected, "reviewed hardware artifact binding")
    if type(build["schema_version"]) is not int or build["schema_version"] != 1 or build["device_part"] != request["device"]["part"]:
        raise ValueError("build/device binding mismatch")
    for kind in required - {"build"}:
        if build[f"{kind}_sha256"] != request["artifacts"][kind]["sha256"]:
            raise ValueError("build/artifact binding mismatch")
    options = request["options"]
    fields = {"core", "depth"} if operation == "capture" else {"flash_part"} if operation == "flash" else set()
    exact_fields(options, fields, "operation options")
    if operation == "capture":
        if not isinstance(options["core"], str) or not IDENTITY.fullmatch(options["core"]):
            raise ValueError("invalid ILA core identity")
        if type(options["depth"]) is not int or options["depth"] < 16 or options["depth"] > 131072 or options["depth"] & (options["depth"] - 1):
            raise ValueError("ILA depth must be a power of two in 16..131072")
    if operation == "flash" and (not isinstance(options["flash_part"], str) or not IDENTITY.fullmatch(options["flash_part"])):
        raise ValueError("invalid exact configuration-memory part")
    return paths


def request_id(request: dict) -> str:
    return content_id(request, "request_id")


def _select_exact(command: str, expected: str, variable: str, property_name: str | None = None) -> str:
    observed = f"[get_property {property_name} $candidate]" if property_name else "$candidate"
    return (f"set matches {{}}\nforeach candidate [{command}] {{\n"
            f"  if {{[string equal {observed} {tcl_word(expected)}]}} {{lappend matches $candidate}}\n"
            "}\nif {[llength $matches] != 1} {error {exact hardware identity not unique}}\n"
            f"set {variable} [lindex $matches 0]\n")


def generate_tcl(root: Path, request: dict, output: Path) -> str:
    paths = validate_request(root, request)
    base = (root / ".vibesilicon/board").resolve()
    if not base.is_relative_to(root.resolve(strict=True)) or not output.resolve().is_relative_to(base):
        raise ValueError("board output outside owned run directory")
    device = request["device"]
    text = "open_hw_manager\nconnect_hw_server -url localhost:3121\n"
    text += _select_exact("get_hw_targets", device["target"], "target")
    text += "current_hw_target $target\nopen_hw_target $target\n"
    text += _select_exact("get_hw_devices -of_objects $target", device["name"], "device", "NAME")
    text += f"if {{![string equal [get_property PART $device] {tcl_word(device['part'])}]}} {{error {{hardware part mismatch}}}}\n"
    text += "current_hw_device $device\n"
    operation = request["operation"]
    if operation == "flash":
        text += _select_exact("get_cfgmem_parts", request["options"]["flash_part"], "flashpart")
        text += "create_hw_cfgmem -hw_device $device $flashpart\nset memory [get_property PROGRAM.HW_CFGMEM $device]\n"
        text += f"set_property PROGRAM.FILES [list {tcl_word(paths['image'])}] $memory\n"
        text += "set_property PROGRAM.ADDRESS_RANGE {use_file} $memory\n"
        for prop in ("ERASE", "BLANK_CHECK", "CFG_PROGRAM", "VERIFY"):
            text += f"set_property PROGRAM.{prop} 1 $memory\n"
        # Native flash access needs the vendor-generated helper bitstream first.
        text += "create_hw_bitstream -hw_device $device [get_property PROGRAM.HW_CFGMEM_BITFILE $device]\n"
        text += "program_hw_devices $device\nprogram_hw_cfgmem $memory\n"
    else:
        text += f"set_property PROGRAM.FILE {tcl_word(paths['bitstream'])} $device\n"
        if operation == "capture":
            text += f"set_property PROBES.FILE {tcl_word(paths['probes'])} $device\n"
        text += "program_hw_devices $device\nrefresh_hw_device $device\n"
        if operation == "capture":
            text += _select_exact("get_hw_ilas -of_objects $device", request["options"]["core"], "ila", "CELL_NAME")
            text += "reset_hw_ila $ila\n"
            text += f"set_property CONTROL.DATA_DEPTH {request['options']['depth']} $ila\n"
            text += "run_hw_ila -trigger_now $ila\n"
            text += f"wait_on_hw_ila -timeout {request['timeout_seconds'] / 60:.6f} $ila\n"
            text += "set samples [upload_hw_ila_data $ila]\n"
            text += f"write_hw_ila_data -csv_file {tcl_word(output / 'capture.csv')} $samples\n"
    text += "close_hw_target $target\ndisconnect_hw_server\nclose_hw_manager\nputs {VIBESILICON_BOARD_OPERATION_COMPLETE}\nexit\n"
    return text


@contextmanager
def board_lock(root: Path):
    # One hardware server per machine. A lock outside the checkout prevents
    # concurrent programming from different VibeSilicon worktrees.
    import tempfile
    lock = Path(tempfile.gettempdir()) / "vibesilicon-local-hw-server.lock"
    try:
        stream = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ValueError("local hardware server is busy; stale locks require operator review") from exc
    try:
        with stream:
            stream.write(json.dumps({"pid": os.getpid(), "root": str(root), "created": datetime.now(timezone.utc).isoformat()}))
        yield
    finally:
        lock.unlink()


def verify_approval(root: Path, request: dict, approval_file: Path | None) -> str:
    if approval_file is None:
        raise ValueError("live hardware operation requires external human approval")
    path = approval_file.resolve(strict=True)
    if path.is_relative_to(root.resolve()):
        raise ValueError("hardware approvals must be outside the agent-writable checkout")
    digest = sha256_file(path)
    trusted = os.environ.get("VIBESILICON_BOARD_APPROVAL_SHA256", "")
    if not trusted or digest != trusted:
        raise ValueError("approval not pinned by the operator environment")
    approval = json.loads(path.read_text(encoding="utf-8"))
    exact_fields(approval, {"schema_version", "request_id", "operator", "reviewer", "expires_at"}, "approval")
    if type(approval["schema_version"]) is not int or approval["schema_version"] != 1 or approval["request_id"] != request_id(request):
        raise ValueError("approval is not bound to this exact operation")
    if not all(isinstance(approval[key], str) and approval[key].strip() for key in ("operator", "reviewer")) or approval["operator"] == approval["reviewer"]:
        raise ValueError("independent human reviewer required")
    expiry = datetime.fromisoformat(approval["expires_at"].replace("Z", "+00:00"))
    if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
        raise ValueError("approval expired or missing timezone")
    return digest


def run_request(root: Path, request: dict, *, execute: bool = False,
                approval_file: Path | None = None, backend=None) -> dict:
    root = root.resolve(strict=True)
    validate_request(root, request)
    identity = request_id(request)
    output = root / ".vibesilicon/board" / uuid.uuid4().hex
    tcl = generate_tcl(root, request, output)
    preview = {"schema_version": 1, "status": "PREVIEW", "request_id": identity,
               "request": request, "risk_class": "R3" if request["operation"] == "flash" else "R2",
               "tcl": tcl, "hardware_validated": False}
    if not execute:
        return preview
    approval_hash = verify_approval(root, request, approval_file)
    session = None
    result = None
    with board_lock(root):
        validate_request(root, request)
        verify_approval(root, request, approval_file)
        output.mkdir(parents=True, exist_ok=False)
        backend = backend or NativeVivadoBackend(root=root, vivado_bin=os.environ.get("VIVADO_BIN", "vivado"))
        try:
            capabilities = backend.discover_capabilities(probe=True)
            if not capabilities["available"]:
                raise ValueError("native Vivado unavailable")
            session = backend.start_session(output, mode="batch", gui=False, tool_version=capabilities["vivado_version"])
            result = backend.execute_tcl(session, tcl, preview["risk_class"], request["timeout_seconds"], approved=True)
        finally:
            if session is not None:
                backend.stop_session(session)
        status = result["status"]
        try:
            verify_execution(root, result, tcl)
        except (KeyError, OSError, ValueError):
            status = "BLOCKED"
        if status == "PASS" and "VIBESILICON_BOARD_OPERATION_COMPLETE" not in result.get("stdout_tail", ""):
            status = "BLOCKED"
        if status == "PASS" and request["operation"] == "capture" and (not (output / "capture.csv").is_file() or (output / "capture.csv").stat().st_size == 0):
            status = "BLOCKED"
        try:
            validate_request(root, request)
        except (OSError, ValueError):
            status = "BLOCKED"
        evidence = {"schema_version": 1, "scope": "hardware_tool_operation", "request": request,
                    "request_id": identity, "approval_sha256": approval_hash, "execution": result,
                    "tcl": tcl,
                    "status": status, "hardware_validated": False,
                    "artifacts": {path.relative_to(root).as_posix(): sha256_file(path)
                                  for path in output.iterdir() if path.is_file()},
                    "limitations": ["tool completion only; independent board application tests remain required",
                                    "flash verification is not cold-boot verification"], "evidence_id": ""}
        evidence["evidence_id"] = content_id(evidence, "evidence_id")
        (output / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        return evidence


def verify_board_evidence(root: Path, evidence: dict) -> dict:
    if evidence.get("evidence_id") != content_id(evidence, "evidence_id"):
        raise ValueError("hardware evidence identity mismatch")
    if evidence["request_id"] != request_id(evidence["request"]):
        raise ValueError("hardware request identity mismatch")
    validate_request(root, evidence["request"])
    verify_execution(root, evidence["execution"], evidence["tcl"])
    for relative, digest in evidence["artifacts"].items():
        if sha256_file(bounded(root, relative)) != digest:
            raise ValueError("hardware artifact changed")
    if evidence["status"] == "PASS" and (evidence["execution"]["status"] != "PASS" or
            "VIBESILICON_BOARD_OPERATION_COMPLETE" not in evidence["execution"].get("stdout_tail", "")):
        raise ValueError("hardware PASS contradicts raw execution")
    return evidence


def validate_soc(root: Path, plan: dict) -> dict:
    exact_fields(plan, {"schema_version", "family", "part", "preset", "initialization", "interface_contract", "board_tests"}, "SoC plan")
    if type(plan["schema_version"]) is not int or plan["schema_version"] != 1:
        raise ValueError("unsupported SoC schema")
    prefixes = {"ps7": "xc7z", "mpsoc": "xczu"}
    if plan["family"] not in prefixes or not isinstance(plan["part"], str) or not PART.fullmatch(plan["part"]) or not plan["part"].startswith(prefixes[plan["family"]]):
        raise ValueError("SoC family/part mismatch")
    for kind in ("preset", "initialization", "interface_contract"):
        exact_fields(plan[kind], {"path", "sha256"}, kind)
        path = bounded(root, plan[kind]["path"])
        if path.stat().st_size == 0 or sha256_file(path) != plan[kind]["sha256"]:
            raise ValueError(f"missing or stale {kind}")
    if plan["board_tests"] != ["identity", "boot_log", "ddr_memory", "peripheral", "clock_reset"]:
        raise ValueError("SoC plan must declare the ordered bring-up checkpoints")
    report = {"schema_version": 1, "scope": "soc_input_preflight", "status": "PASS", "plan": plan,
              "hardware_validated": False, "checkpoints": {name: "BLOCKED" for name in plan["board_tests"]},
              "limitations": ["input binding only; preset/DDR electrical correctness requires independent board review",
                              "no PS configuration, software generation or board execution is inferred"], "evidence_id": ""}
    report["evidence_id"] = content_id(report, "evidence_id")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "execute", "validate-soc"))
    parser.add_argument("request", type=Path)
    parser.add_argument("--approval-file", type=Path)
    args = parser.parse_args()
    try:
        root = Path.cwd()
        document = json.loads(bounded(root, args.request.as_posix(), suffix=".json").read_text(encoding="utf-8"))
        report = validate_soc(root, document) if args.action == "validate-soc" else run_request(
            root, document, execute=args.action == "execute", approval_file=args.approval_file)
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return 2
    print(json.dumps(report))
    return 0 if report["status"] in {"PASS", "PREVIEW"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
