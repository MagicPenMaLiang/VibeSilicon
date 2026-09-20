#!/usr/bin/env python3
"""Run a bounded self-checking Verilator testbench for one RTL manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.quality_gate.rtl_manifest import IDENTIFIER, ManifestError, _bounded_path, validate_manifest
from scripts.quality_gate.rtl_quality_config import load_policy
from scripts.quality_gate.rtl_xpr_shadow import _mask_non_code
from scripts.rtl_source_mutation import _msys_path, _tool


ROOT = Path(__file__).resolve().parents[2]
TOKEN = re.compile(r"[A-Z][A-Z0-9_]{4,80}\Z")


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _content_id(report: dict) -> str:
    payload = json.dumps({key: value for key, value in report.items() if key != "evidence_id"},
                         sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha(payload)


def verify_report(report: dict) -> dict:
    """Reject malformed or content-ID-tampered directed-smoke evidence."""
    required = {
        "schema_version", "gate", "status", "evidence_id", "manifest_sha256",
        "contract_sha256", "input_set_sha256", "top", "tool_version",
        "execution", "limitations",
    }
    if not isinstance(report, dict) or set(report) != required:
        raise ManifestError("invalid project smoke evidence shape")
    if type(report["schema_version"]) is not int or report["schema_version"] != 1 or report["gate"] != "G2_PROJECT_RTL_SMOKE":
        raise ManifestError("unsupported project smoke evidence")
    if report["status"] not in {"PASS", "FAIL", "BLOCKED"}:
        raise ManifestError("invalid project smoke evidence status")
    for field in ("evidence_id", "manifest_sha256", "contract_sha256", "input_set_sha256"):
        if not isinstance(report[field], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", report[field]):
            raise ManifestError("invalid project smoke evidence hash")
    execution = report["execution"]
    if not isinstance(execution, dict) or set(execution) != {"compile", "run", "pass_token_count"}:
        raise ManifestError("invalid project smoke execution evidence")
    states = {"PASS", "FAIL", "TIMEOUT", "ERROR", "NOT_RUN"}
    if execution["compile"] not in states or execution["run"] not in states:
        raise ManifestError("invalid project smoke execution state")
    if type(execution["pass_token_count"]) is not int or execution["pass_token_count"] < 0:
        raise ManifestError("invalid project smoke pass-token count")
    if (not isinstance(report["top"], str) or not IDENTIFIER.fullmatch(report["top"])
            or report["tool_version"] is not None and not isinstance(report["tool_version"], str)
            or not isinstance(report["limitations"], list) or not report["limitations"]
            or not all(isinstance(item, str) and item for item in report["limitations"])):
        raise ManifestError("invalid project smoke evidence metadata")
    if report["evidence_id"] != _content_id(report):
        raise ManifestError("project smoke evidence content ID mismatch")
    expected_status = (
        "PASS" if execution == {"compile": "PASS", "run": "PASS", "pass_token_count": 1}
        else "BLOCKED" if ("TIMEOUT" in execution.values() or "ERROR" in execution.values()
                           or execution["compile"] == execution["run"] == "NOT_RUN")
        else "FAIL"
    )
    if report["status"] != expected_status:
        raise ManifestError("project smoke status does not match execution evidence")
    return report


def _contract(root: Path, manifest: dict, path: Path) -> tuple[dict, Path]:
    if path.is_absolute():
        raise ManifestError("simulation contract must be repository-relative")
    contract_file = _bounded_path(root, path.as_posix(), kind="simulation contract")
    project = _bounded_path(root, manifest["project_root"], kind="project_root")
    if contract_file.parent != project:
        raise ManifestError("simulation contract must be at project root")
    data = json.loads(contract_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {
        "schema_version", "simulator", "top", "dut_instance", "testbench",
        "pass_token", "timeout_seconds"
    }:
        raise ManifestError("invalid simulation contract shape")
    if data["schema_version"] != 1 or data["simulator"] != "verilator":
        raise ManifestError("unsupported simulation contract")
    if not isinstance(data["top"], str) or not IDENTIFIER.fullmatch(data["top"]):
        raise ManifestError("invalid simulation top")
    if data["top"] == manifest["top"]:
        raise ManifestError("simulation top must be a separate self-checking testbench")
    if not isinstance(data["dut_instance"], str) or not IDENTIFIER.fullmatch(data["dut_instance"]):
        raise ManifestError("invalid DUT instance name")
    if not isinstance(data["pass_token"], str) or not TOKEN.fullmatch(data["pass_token"]):
        raise ManifestError("invalid simulation pass token")
    timeout = data["timeout_seconds"]
    if type(timeout) is not int or not 10 <= timeout <= 300:
        raise ManifestError("simulation timeout must be 10..300 seconds")
    testbench = _bounded_path(root, data["testbench"], kind="testbench")
    if not testbench.is_file() or testbench.suffix.lower() not in {".v", ".sv"}:
        raise ManifestError("simulation testbench must be a Verilog file")
    if not testbench.is_relative_to(project) or data["testbench"] in manifest["sources"]:
        raise ManifestError("simulation testbench must be project-local and separate from design sources")
    if data["testbench"] in manifest.get("excluded_sources", {}):
        raise ManifestError("excluded RTL cannot silently become a simulation testbench")
    design = re.escape(manifest["top"])
    instance = re.escape(data["dut_instance"])
    code = _mask_non_code(testbench.read_text(encoding="utf-8"))
    if not re.search(rf"\b{design}\s+{instance}\s*\(", code):
        raise ManifestError("self-checking testbench does not instantiate the manifest top")
    return data, testbench


def _run(root: Path, manifest: dict, contract: dict, testbench: Path, tool: dict) -> dict:
    timeout = contract["timeout_seconds"]
    with tempfile.TemporaryDirectory(prefix="vibesilicon-project-smoke-") as directory:
        object_dir = Path(directory) / "obj"
        source_paths = [root / path for path in manifest["sources"]] + [testbench]
        include_paths = [root / path for path in manifest["include_dirs"]]
        if tool["kind"] == "MSYS2_FIXED_BRIDGE":
            source_args = [_msys_path(path) for path in source_paths]
            include_args = [_msys_path(path) for path in include_paths]
            object_arg = _msys_path(object_dir)
        else:
            source_args = [str(path) for path in source_paths]
            include_args = [str(path) for path in include_paths]
            object_arg = str(object_dir)
        args = [
            "--binary", "--timing", "--assert", "--top-module", contract["top"],
            "--Mdir", object_arg, "-Wno-fatal",
        ]
        args.extend(f"-I{path}" for path in include_args)
        args.extend(f"+define+{key}={value}" for key, value in sorted(manifest["defines"].items()))
        args.extend(f"-G{key}={value}" for key, value in sorted(manifest["parameters"].items()))
        if os.name == "nt":
            args.extend(["-CFLAGS", "-D_GLIBCXX_USE_CXX11_ABI=0"])
        args.extend(source_args)
        try:
            built = subprocess.run(
                list(tool["command"]) + args, cwd=root, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"compile": "TIMEOUT", "run": "NOT_RUN", "pass_token_count": 0}
        except OSError:
            return {"compile": "ERROR", "run": "NOT_RUN", "pass_token_count": 0}
        if built.returncode:
            return {"compile": "FAIL", "run": "NOT_RUN", "pass_token_count": 0}
        binary = object_dir / (f"V{contract['top']}.exe" if os.name == "nt" else f"V{contract['top']}")
        if not binary.is_file():
            return {"compile": "ERROR", "run": "NOT_RUN", "pass_token_count": 0}
        environment = os.environ.copy()
        if os.name == "nt":
            wrapper = shutil.which("verilator")
            if wrapper:
                environment["PATH"] = str(Path(wrapper).parent) + os.pathsep + environment.get("PATH", "")
        try:
            ran = subprocess.run(
                [str(binary)], cwd=root, env=environment, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"compile": "PASS", "run": "TIMEOUT", "pass_token_count": 0}
        except OSError:
            return {"compile": "PASS", "run": "ERROR", "pass_token_count": 0}
        return {
            "compile": "PASS", "run": "PASS" if ran.returncode == 0 else "FAIL",
            "pass_token_count": (ran.stdout or "").count(contract["pass_token"]),
        }


def run_project(manifest_path: Path, contract_path: Path, *, repository_root: Path = ROOT) -> dict:
    root = repository_root.resolve(strict=True)
    if manifest_path.is_absolute():
        raise ManifestError("simulation manifest must be repository-relative")
    manifest = validate_manifest(manifest_path, repository_root=repository_root)
    if manifest["parameters"]:
        raise ManifestError("parameterized RTL requires a reviewed simulation adapter")
    manifest_file = _bounded_path(root, manifest_path.as_posix(), kind="manifest")
    contract, testbench = _contract(root, manifest, contract_path)
    contract_file = _bounded_path(root, contract_path.as_posix(), kind="simulation contract")
    inputs = {path.as_posix(): _sha(_bounded_path(root, path.as_posix(), kind="input").read_bytes())
              for path in [manifest_path, contract_path]}
    inputs.update({path: _sha(_bounded_path(root, path, kind="source").read_bytes())
                   for path in manifest["sources"] + manifest["headers"]})
    inputs[contract["testbench"]] = _sha(testbench.read_bytes())
    tool = _tool()
    if tool["status"] != "AVAILABLE":
        execution = {"compile": "NOT_RUN", "run": "NOT_RUN", "pass_token_count": 0}
        status = "BLOCKED"
    else:
        major = re.search(r"Verilator (\d+)\.", tool["version"] or "")
        if not major or int(major.group(1)) not in load_policy()["tool_versions"]["verilator"]["accepted_major"]:
            raise ManifestError("unapproved Verilator version for simulation")
        execution = _run(root, manifest, contract, testbench, tool)
        status = (
            "PASS" if execution == {"compile": "PASS", "run": "PASS", "pass_token_count": 1}
            else "BLOCKED" if "TIMEOUT" in execution.values() or "ERROR" in execution.values()
            else "FAIL"
        )
    after = {path: _sha(_bounded_path(root, path, kind="input").read_bytes()) for path in inputs}
    if after != inputs:
        raise ManifestError("manifest, contract or RTL changed during simulation")
    report = {
        "schema_version": 1, "gate": "G2_PROJECT_RTL_SMOKE", "status": status, "evidence_id": "",
        "manifest_sha256": inputs[manifest_file.relative_to(root).as_posix()],
        "contract_sha256": inputs[contract_file.relative_to(root).as_posix()],
        "input_set_sha256": _content_id(inputs),
        "top": contract["top"], "tool_version": tool["version"],
        "execution": execution,
        "limitations": ["one directed self-checking testbench", "not full G2 or implementation signoff"],
    }
    report["evidence_id"] = _content_id(report)
    return verify_report(report)


def _summary(report: dict) -> str:
    execution = report["execution"]
    return (
        "## Project RTL G2 directed smoke\n\n"
        f"Status: **{report['status']}**; Evidence: `{report['evidence_id']}`\n\n"
        "| Check | Result |\n|---|---|\n"
        f"| Compile | {execution['compile']} |\n"
        f"| Run | {execution['run']} |\n"
        f"| Unique pass token count | {execution['pass_token_count']} |\n\n"
        "Scope: one project-bound self-checking testbench; not full G2, "
        "CDC/RDC, implementation, or product signoff.\n"
    )


def _write_summary(markdown: str) -> None:
    destination = os.environ.get("GITHUB_STEP_SUMMARY")
    if destination:
        with Path(destination).open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(markdown)


def _annotate_failure(status: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::error title=Project RTL G2 smoke::{status}; see the job summary and step log")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        report = run_project(args.manifest, args.contract, repository_root=args.repository_root)
        _write_summary(_summary(report))
    except (ManifestError, OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        try:
            _write_summary("## Project RTL G2 directed smoke\n\nStatus: **BLOCKED**. See the step log.\n")
        except OSError:
            pass
        _annotate_failure("BLOCKED")
        reason = "required input or summary output unavailable" if isinstance(exc, OSError) else str(exc)
        print(json.dumps({"status": "BLOCKED", "reason": reason}), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    if report["status"] != "PASS":
        _annotate_failure(report["status"])
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
