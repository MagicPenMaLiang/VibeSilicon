#!/usr/bin/env python3
"""Run source-bound RTL mutants in isolated Verilator builds without editing the repository."""

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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class RtlSourceMutationError(ValueError):
    """Raised when a source mutation campaign is unsafe, stale, or ambiguous."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _content_id(value: Mapping[str, Any]) -> str:
    return _sha256(_canonical({key: item for key, item in value.items() if key != "evidence_id"}))


def _fields(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise RtlSourceMutationError(f"{label} fields must be exactly {sorted(expected)}")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        raise RtlSourceMutationError(f"{label} is invalid")
    return value


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise RtlSourceMutationError(f"{label} is not a SHA-256 content ID")
    return value


def _file(root: Path, value: Any, label: str) -> tuple[str, Path]:
    if not isinstance(value, str) or not value or "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise RtlSourceMutationError(f"{label} must be a POSIX repository-relative path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or "." in pure.parts or ".." in pure.parts or value != pure.as_posix():
        raise RtlSourceMutationError(f"{label} must be canonical and repository relative")
    resolved_root = root.resolve(strict=True)
    try:
        path = resolved_root.joinpath(*pure.parts).resolve(strict=True)
        path.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise RtlSourceMutationError(f"{label} escapes repository root") from exc
    if not path.is_file() or path.is_symlink():
        raise RtlSourceMutationError(f"{label} must be a regular non-symlink file")
    return value, path


def _source_contract(value: Any, *, root: Path, label: str, suffixes: set[str]) -> tuple[str, Path]:
    item = _fields(value, {"path", "sha256"}, label)
    relative, path = _file(root, item["path"], f"{label}.path")
    if path.suffix.lower() not in suffixes:
        raise RtlSourceMutationError(f"{label} has an unsupported suffix")
    if _hash(item["sha256"], f"{label}.sha256") != _sha256(path.read_bytes()):
        raise RtlSourceMutationError(f"{label} hash is stale")
    return relative, path


def validate_campaign(campaign: Mapping[str, Any], *, root: Path) -> dict[str, Path]:
    _fields(
        campaign,
        {
            "schema_version", "campaign_id", "project", "plan", "requirement_id", "checker_id",
            "coverage_id", "rtl_source", "testbench", "top", "minimum_score", "timeout_seconds",
            "mutants",
        },
        "campaign",
    )
    if campaign["schema_version"] != SCHEMA_VERSION:
        raise RtlSourceMutationError("unsupported campaign schema_version")
    for field in ("campaign_id", "project", "requirement_id", "checker_id", "coverage_id", "top"):
        _identifier(campaign[field], field)
    plan_relative, plan_path = _source_contract(
        campaign["plan"], root=root, label="plan", suffixes={".json"}
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("project") != campaign["project"]:
        raise RtlSourceMutationError("campaign project does not match verification plan")
    obligations = [
        item for item in plan.get("obligations", [])
        if item.get("requirement_id") == campaign["requirement_id"]
    ]
    if len(obligations) != 1 or campaign["checker_id"] not in obligations[0].get("checker_ids", []) or campaign["coverage_id"] not in obligations[0].get("coverage_ids", []):
        raise RtlSourceMutationError("campaign requirement is not linked to checker and coverage")
    checkers = [item for item in plan.get("checkers", []) if item.get("checker_id") == campaign["checker_id"]]
    if len(checkers) != 1 or checkers[0].get("kind") != "REFERENCE_MODEL" or checkers[0].get("fault_domain") != "CHECKER":
        raise RtlSourceMutationError("RTL mutation requires a REFERENCE_MODEL checker in CHECKER fault domain")
    coverage = [item for item in plan.get("coverage", []) if item.get("coverage_id") == campaign["coverage_id"]]
    if len(coverage) != 1 or coverage[0].get("kind") != "FUNCTIONAL":
        raise RtlSourceMutationError("RTL mutation campaign must bind functional coverage")
    rtl_relative, rtl_path = _source_contract(
        campaign["rtl_source"], root=root, label="rtl_source", suffixes={".v", ".sv"}
    )
    testbench_relative, testbench_path = _source_contract(
        campaign["testbench"], root=root, label="testbench", suffixes={".v", ".sv"}
    )
    score = campaign["minimum_score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
        raise RtlSourceMutationError("minimum_score must be between 0 and 1")
    timeout = campaign["timeout_seconds"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 10 <= timeout <= 300:
        raise RtlSourceMutationError("timeout_seconds must be between 10 and 300")
    mutants = campaign["mutants"]
    if not isinstance(mutants, list) or not mutants:
        raise RtlSourceMutationError("mutants must be a non-empty list")
    source_text = rtl_path.read_text(encoding="utf-8")
    mutation_ids = set()
    originals = set()
    tokens = set()
    for index, raw in enumerate(mutants):
        mutant = _fields(
            raw,
            {"mutation_id", "operator", "original", "replacement", "expected_failure_token"},
            f"mutants[{index}]",
        )
        mutation_id = _identifier(mutant["mutation_id"], f"mutants[{index}].mutation_id")
        if mutation_id in mutation_ids:
            raise RtlSourceMutationError("mutation_id must be unique")
        mutation_ids.add(mutation_id)
        if mutant["operator"] != "EXACT_REPLACE":
            raise RtlSourceMutationError("only EXACT_REPLACE is supported")
        for field in ("original", "replacement", "expected_failure_token"):
            if not isinstance(mutant[field], str) or not mutant[field]:
                raise RtlSourceMutationError(f"mutant {field} must be non-empty")
        if mutant["original"] == mutant["replacement"]:
            raise RtlSourceMutationError("mutation replacement must change source text")
        if source_text.count(mutant["original"]) != 1:
            raise RtlSourceMutationError(f"mutation original must occur exactly once: {mutation_id}")
        if mutant["original"] in originals:
            raise RtlSourceMutationError("mutation originals must be unique")
        originals.add(mutant["original"])
        if mutant["expected_failure_token"] in tokens:
            raise RtlSourceMutationError("expected failure tokens must be unique")
        tokens.add(mutant["expected_failure_token"])
    return {
        "plan": plan_path, "rtl_source": rtl_path, "testbench": testbench_path,
        "plan_relative": Path(plan_relative), "rtl_relative": Path(rtl_relative),
        "testbench_relative": Path(testbench_relative),
    }


def apply_mutation(source: str, mutant: Mapping[str, Any]) -> str:
    original = mutant["original"]
    if source.count(original) != 1:
        raise RtlSourceMutationError("mutation original is no longer unique")
    mutated = source.replace(original, mutant["replacement"], 1)
    if mutated == source:
        raise RtlSourceMutationError("mutation did not alter source")
    return mutated


def _msys_path(path: Path) -> str:
    resolved = str(path.resolve(strict=False))
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", resolved)
    if match is None:
        raise RtlSourceMutationError("Windows Verilator path cannot be mapped into MSYS2")
    return f"/{match.group(1).lower()}/{match.group(2).replace(chr(92), '/')}"


def _tool() -> dict[str, Any]:
    executable = shutil.which("verilator")
    if executable is None:
        return {"status": "MISSING", "version": None, "kind": None, "command": None, "reason": "verilator is not on PATH"}
    command: list[str]
    kind = "DIRECT"
    if os.name == "nt":
        wrapper = Path(executable)
        try:
            is_script = wrapper.read_bytes()[:2] == b"#!"
        except OSError as exc:
            return {"status": "ERROR", "version": None, "kind": None, "command": None, "reason": str(exc)}
        if is_script:
            msys_root = wrapper.parent.parent.parent
            bash = msys_root / "usr" / "bin" / "bash.exe"
            if not bash.is_file():
                return {"status": "MISSING", "version": None, "kind": None, "command": None, "reason": "MSYS2 bash bridge is missing"}
            bridge = (
                "export PATH=/mingw64/bin:/usr/bin:$PATH; export LANG=C LC_ALL=C; "
                "if [ -n \"$TMPDIR\" ]; then export TMP=\"$TMPDIR\" TEMP=\"$TMPDIR\"; fi; "
                "export MAKEFLAGS=\"PYTHON3=$1\"; shift; exec verilator \"$@\""
            )
            command = [
                str(bash), "-lc", bridge, "vibesilicon-verilator",
                _msys_path(Path(sys.executable)),
            ]
            kind = "MSYS2_FIXED_BRIDGE"
        else:
            command = [executable]
    else:
        command = [executable]
    try:
        completed = subprocess.run(
            command + ["--version"], capture_output=True, text=True, shell=False,
            encoding="utf-8", errors="replace", timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "ERROR", "version": None, "kind": kind, "command": None, "reason": str(exc)}
    output = (completed.stdout or completed.stderr).strip().splitlines()
    if completed.returncode != 0 or not output:
        return {"status": "ERROR", "version": None, "kind": kind, "command": None, "reason": "Verilator version probe failed"}
    return {"status": "AVAILABLE", "version": output[-1], "kind": kind, "command": command, "reason": None}


def _run_case(
    source_text: str, testbench_bytes: bytes, *, top: str, timeout: int,
    tool: Mapping[str, Any], label: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"vibesilicon-rtl-mut-{label}-") as temporary:
        work = Path(temporary)
        source = work / "dut.v"
        testbench = work / "mutation_tb.sv"
        object_dir = work / "obj"
        source.write_text(source_text, encoding="utf-8", newline="\n")
        testbench.write_bytes(testbench_bytes)
        paths = [source, testbench, object_dir]
        if tool["kind"] == "MSYS2_FIXED_BRIDGE":
            paths = [_msys_path(path) for path in paths]
        else:
            paths = [str(path) for path in paths]
        args = [
            "--binary", "--timing", "--assert", "--top-module", top, "--Mdir", paths[2],
            "-Wno-fatal",
        ]
        if os.name == "nt":
            args.extend(["-CFLAGS", "-D_GLIBCXX_USE_CXX11_ABI=0"])
        args.extend(paths[:2])
        try:
            built = subprocess.run(
                list(tool["command"]) + args, capture_output=True, text=True, shell=False,
                encoding="utf-8", errors="replace", timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            return {"compile_status": "TIMEOUT", "compile_exit_code": 124, "run_status": "NOT_RUN", "run_exit_code": None, "output": ""}
        except OSError as exc:
            return {"compile_status": "ERROR", "compile_exit_code": 126, "run_status": "NOT_RUN", "run_exit_code": None, "output": str(exc)}
        compile_output = (built.stdout or "") + (built.stderr or "")
        if built.returncode != 0:
            return {"compile_status": "FAIL", "compile_exit_code": built.returncode, "run_status": "NOT_RUN", "run_exit_code": None, "output": compile_output[-8000:]}
        binary = object_dir / (f"V{top}.exe" if os.name == "nt" else f"V{top}")
        if not binary.is_file():
            return {"compile_status": "ERROR", "compile_exit_code": 0, "run_status": "NOT_RUN", "run_exit_code": None, "output": "simulation binary is missing"}
        environment = os.environ.copy()
        if os.name == "nt":
            wrapper = Path(shutil.which("verilator") or "")
            environment["PATH"] = str(wrapper.parent) + os.pathsep + environment.get("PATH", "")
        try:
            ran = subprocess.run(
                [str(binary)], capture_output=True, text=True, shell=False, timeout=timeout,
                encoding="utf-8", errors="replace", check=False, env=environment,
            )
        except subprocess.TimeoutExpired:
            return {"compile_status": "PASS", "compile_exit_code": 0, "run_status": "TIMEOUT", "run_exit_code": 124, "output": compile_output[-4000:]}
        except OSError as exc:
            return {"compile_status": "PASS", "compile_exit_code": 0, "run_status": "ERROR", "run_exit_code": 126, "output": str(exc)}
        run_output = (ran.stdout or "") + (ran.stderr or "")
        return {
            "compile_status": "PASS", "compile_exit_code": 0,
            "run_status": "PASS" if ran.returncode == 0 else "FAIL",
            "run_exit_code": ran.returncode, "output": run_output[-8000:],
        }


def _mutation_row(
    mutant: Mapping[str, Any], source_text: str, testbench_bytes: bytes, *,
    top: str, timeout: int, tool: Mapping[str, Any],
) -> dict[str, Any]:
    mutated = apply_mutation(source_text, mutant)
    raw = _run_case(
        mutated, testbench_bytes, top=top, timeout=timeout, tool=tool,
        label=mutant["mutation_id"],
    )
    token_observed = raw["output"].count(mutant["expected_failure_token"]) == 1
    if raw["compile_status"] != "PASS":
        outcome = "INVALID"
    elif raw["run_status"] == "FAIL" and token_observed:
        outcome = "KILLED"
    elif raw["run_status"] in {"TIMEOUT", "ERROR"}:
        outcome = "ERROR"
    else:
        outcome = "SURVIVED"
    return {
        "mutation_id": mutant["mutation_id"], "operator": mutant["operator"],
        "source_sha256": _sha256(mutated.encode()),
        "expected_failure_token": mutant["expected_failure_token"],
        "failure_token_observed": token_observed,
        "compile_status": raw["compile_status"], "compile_exit_code": raw["compile_exit_code"],
        "run_status": raw["run_status"], "run_exit_code": raw["run_exit_code"],
        "status": outcome,
    }


def build_result(
    campaign: Mapping[str, Any], *, root: Path, campaign_path: str, campaign_bytes: bytes,
) -> dict[str, Any]:
    paths = validate_campaign(campaign, root=root)
    source_bytes = paths["rtl_source"].read_bytes()
    source_text = source_bytes.decode("utf-8")
    testbench_bytes = paths["testbench"].read_bytes()
    tool = _tool()
    tool_evidence = {key: value for key, value in tool.items() if key != "command"}
    if tool["status"] != "AVAILABLE":
        baseline = {"compile_status": "NOT_RUN", "compile_exit_code": None, "run_status": "NOT_RUN", "run_exit_code": None}
        rows = []
        status = "BLOCKED"
        score = None
    else:
        baseline_raw = _run_case(
            source_text, testbench_bytes, top=campaign["top"],
            timeout=campaign["timeout_seconds"], tool=tool, label="baseline",
        )
        baseline = {key: value for key, value in baseline_raw.items() if key != "output"}
        baseline["pass_token_observed"] = "RTL_MUTATION_BASELINE_PASS" in baseline_raw["output"]
        rows = []
        if baseline["compile_status"] == "PASS" and baseline["run_status"] == "PASS" and baseline["pass_token_observed"]:
            mutants = sorted(campaign["mutants"], key=lambda item: item["mutation_id"])
            with ThreadPoolExecutor(max_workers=min(3, len(mutants))) as executor:
                rows = list(executor.map(
                    lambda mutant: _mutation_row(
                        mutant, source_text, testbench_bytes, top=campaign["top"],
                        timeout=campaign["timeout_seconds"], tool=tool,
                    ),
                    mutants,
                ))
        killed = sum(item["status"] == "KILLED" for item in rows)
        score = round(killed / len(campaign["mutants"]), 6) if rows else None
        valid_campaign = len(rows) == len(campaign["mutants"]) and all(
            item["status"] in {"KILLED", "SURVIVED"} for item in rows
        )
        status = (
            "PASS" if valid_campaign and score >= campaign["minimum_score"]
            else "FAIL" if valid_campaign else "BLOCKED"
        )
    result = {
        "schema_version": SCHEMA_VERSION, "evidence_id": "", "status": status,
        "campaign_id": campaign["campaign_id"], "project": campaign["project"],
        "requirement_id": campaign["requirement_id"], "checker_id": campaign["checker_id"],
        "coverage_id": campaign["coverage_id"],
        "inputs": {
            "campaign_path": campaign_path, "campaign_sha256": _sha256(campaign_bytes),
            "plan_path": campaign["plan"]["path"], "plan_sha256": campaign["plan"]["sha256"],
            "rtl_source_path": campaign["rtl_source"]["path"], "rtl_source_sha256": campaign["rtl_source"]["sha256"],
            "testbench_path": campaign["testbench"]["path"], "testbench_sha256": campaign["testbench"]["sha256"],
        },
        "tool": tool_evidence, "baseline": baseline, "mutants": rows,
        "summary": {
            "mutant_count": len(campaign["mutants"]),
            "killed_count": sum(item["status"] == "KILLED" for item in rows),
            "survived_count": sum(item["status"] == "SURVIVED" for item in rows),
            "invalid_count": sum(item["status"] in {"INVALID", "ERROR"} for item in rows),
            "mutation_score": score, "minimum_score": campaign["minimum_score"],
            "repository_files_modified": False, "golden_modified": False,
            "testbench_modified": False,
        },
    }
    result["evidence_id"] = _content_id(result)
    return result


def validate_evidence(value: Mapping[str, Any], *, root: Path) -> None:
    _fields(
        value,
        {
            "schema_version", "evidence_id", "status", "campaign_id", "project",
            "requirement_id", "checker_id", "coverage_id", "inputs", "tool", "baseline",
            "mutants", "summary",
        },
        "evidence",
    )
    if value["schema_version"] != SCHEMA_VERSION or value["status"] not in {"PASS", "FAIL", "BLOCKED"}:
        raise RtlSourceMutationError("evidence schema or status is invalid")
    if _hash(value["evidence_id"], "evidence_id") != _content_id(value):
        raise RtlSourceMutationError("evidence_id does not match content")
    inputs = _fields(
        value["inputs"],
        {
            "campaign_path", "campaign_sha256", "plan_path", "plan_sha256",
            "rtl_source_path", "rtl_source_sha256", "testbench_path", "testbench_sha256",
        },
        "inputs",
    )
    for name in ("campaign", "plan", "rtl_source", "testbench"):
        _, path = _file(root, inputs[f"{name}_path"], f"inputs.{name}_path")
        if inputs[f"{name}_sha256"] != _sha256(path.read_bytes()):
            raise RtlSourceMutationError(f"evidence {name} input is stale")
    _, campaign_path = _file(root, inputs["campaign_path"], "campaign_path")
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    validate_campaign(campaign, root=root)
    for field in ("campaign_id", "project", "requirement_id", "checker_id", "coverage_id"):
        if value[field] != campaign[field]:
            raise RtlSourceMutationError(f"evidence {field} does not match campaign")
    if inputs["plan_path"] != campaign["plan"]["path"] or inputs["plan_sha256"] != campaign["plan"]["sha256"]:
        raise RtlSourceMutationError("evidence plan binding does not match campaign")
    tool = _fields(value["tool"], {"status", "version", "kind", "reason"}, "tool")
    if tool["status"] not in {"AVAILABLE", "MISSING", "ERROR"} or tool["kind"] not in {None, "DIRECT", "MSYS2_FIXED_BRIDGE"}:
        raise RtlSourceMutationError("tool evidence is invalid")
    rows = value["mutants"]
    if not isinstance(rows, list):
        raise RtlSourceMutationError("mutants must be a list")
    campaign_by_id = {item["mutation_id"]: item for item in campaign["mutants"]}
    source_text = (root / campaign["rtl_source"]["path"]).read_bytes().decode("utf-8")
    if [row.get("mutation_id") for row in rows] != sorted(campaign_by_id):
        raise RtlSourceMutationError("evidence mutant rows are incomplete or unsorted")
    for row in rows:
        mutant = campaign_by_id[row["mutation_id"]]
        if row.get("operator") != mutant["operator"] or row.get("expected_failure_token") != mutant["expected_failure_token"]:
            raise RtlSourceMutationError("evidence mutant contract is stale")
        expected_hash = _sha256(apply_mutation(source_text, mutant).encode())
        if row.get("source_sha256") != expected_hash:
            raise RtlSourceMutationError("evidence mutated source hash is stale")
        if row.get("status") == "KILLED" and not (
            row.get("compile_status") == "PASS" and row.get("run_status") == "FAIL"
            and row.get("failure_token_observed") is True
        ):
            raise RtlSourceMutationError("KILLED mutant lacks compile/run/token evidence")
    summary = value["summary"]
    expected_summary = {
        "mutant_count": len(campaign["mutants"]),
        "killed_count": sum(row.get("status") == "KILLED" for row in rows),
        "survived_count": sum(row.get("status") == "SURVIVED" for row in rows),
        "invalid_count": sum(row.get("status") in {"INVALID", "ERROR"} for row in rows),
        "mutation_score": round(sum(row.get("status") == "KILLED" for row in rows) / len(campaign["mutants"]), 6) if rows else None,
        "minimum_score": campaign["minimum_score"],
        "repository_files_modified": False, "golden_modified": False,
        "testbench_modified": False,
    }
    if summary != expected_summary:
        raise RtlSourceMutationError("evidence summary is inconsistent")
    baseline_ok = value["baseline"] == {
        "compile_status": "PASS", "compile_exit_code": 0, "run_status": "PASS",
        "run_exit_code": 0, "pass_token_observed": True,
    }
    pass_expected = (
        baseline_ok and len(rows) == len(campaign["mutants"])
        and summary["mutation_score"] is not None
        and summary["mutation_score"] >= campaign["minimum_score"]
        and summary["invalid_count"] == 0
    )
    if (value["status"] == "PASS") != pass_expected:
        raise RtlSourceMutationError("evidence PASS status is inconsistent")
    valid_rows = len(rows) == len(campaign["mutants"]) and summary["invalid_count"] == 0
    fail_expected = baseline_ok and valid_rows and not pass_expected
    if (value["status"] == "FAIL") != fail_expected:
        raise RtlSourceMutationError("evidence FAIL status is inconsistent")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("campaign")
    build.add_argument("--root", type=Path, default=Path.cwd())
    build.add_argument("--output", required=True, type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("evidence")
    verify.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        if args.command == "build":
            campaign_path, campaign_file = _file(root, args.campaign, "campaign")
            campaign_bytes = campaign_file.read_bytes()
            campaign = json.loads(campaign_bytes.decode("utf-8"))
            result = build_result(
                campaign, root=root, campaign_path=campaign_path, campaign_bytes=campaign_bytes
            )
            output = (args.output if args.output.is_absolute() else root / args.output).resolve(strict=False)
            output.relative_to(root)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        else:
            _, evidence_file = _file(root, args.evidence, "evidence")
            result = json.loads(evidence_file.read_text(encoding="utf-8"))
            validate_evidence(result, root=root)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RtlSourceMutationError) as exc:
        print(json.dumps({"status": "ERROR", "decision": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "evidence_id": result["evidence_id"]}))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
