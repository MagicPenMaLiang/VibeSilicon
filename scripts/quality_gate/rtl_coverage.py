#!/usr/bin/env python3
"""Preserve Verilator line-coverage artifacts and gate only declared source scope."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import uuid

from scripts.evidence_contract import content_id, sha256_file
from scripts.fpga_reports import bounded
from scripts.quality_gate.rtl_manifest import validate_manifest
from scripts.quality_gate.rtl_project_smoke import _contract, _run, _tool
from scripts.quality_gate.rtl_quality_config import load_policy
from scripts.rtl_source_mutation import _msys_path


def parse_lcov(text: str, root: Path, scope: list[str]) -> dict:
    """Count instrumented lines, not statements or functional bins."""
    records = {}
    source = None
    points = {}
    for line in text.splitlines():
        if line.startswith("SF:"):
            if source is not None:
                raise ValueError("unterminated LCOV source record")
            value = line[3:]
            if os.name == "nt" and re.match(r"^/[a-zA-Z]/", value):
                value = value[1] + ":/" + value[3:]
            path = Path(value)
            path = (path if path.is_absolute() else root / path).resolve(strict=True)
            if not path.is_relative_to(root.resolve(strict=True)):
                raise ValueError("coverage source outside repository")
            source = path.relative_to(root).as_posix()
            if source in records:
                raise ValueError("duplicate LCOV source")
            points = {}
        elif line.startswith("DA:"):
            if source is None:
                raise ValueError("coverage points outside source record")
            fields = line[3:].split(",")
            if len(fields) < 2 or not fields[0].isdigit() or not fields[1].isdigit():
                raise ValueError("invalid LCOV line counts")
            number, count = int(fields[0]), int(fields[1])
            if number < 1 or number in points:
                raise ValueError("invalid/duplicate LCOV line")
            points[number] = count
        elif line == "end_of_record":
            if source is None:
                raise ValueError("unexpected LCOV record end")
            records[source] = points
            source = None
    if source is not None:
        raise ValueError("truncated LCOV")
    metrics = {}
    for relative in scope:
        if not records.get(relative):
            raise ValueError(f"no instrumented lines in declared scope: {relative}")
        counts = records[relative]
        metrics[relative] = {"hit": sum(count > 0 for count in counts.values()), "total": len(counts),
                             "uncovered_lines": sorted(number for number, count in counts.items() if count == 0)}
    hit = sum(item["hit"] for item in metrics.values())
    total = sum(item["total"] for item in metrics.values())
    return {"metric": "verilator_instrumented_line", "hit": hit, "total": total,
            "percent": 100 * hit / total, "sources": metrics}


def validate_contract(root: Path, manifest: dict, value: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "backend", "metric", "scope", "minimum_percent", "simulation_contract"
    }:
        raise ValueError("invalid coverage contract fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("unsupported coverage schema")
    if value["backend"] != "verilator" or value["metric"] != "line":
        raise ValueError("initial backend supports Verilator line coverage only")
    target = value["minimum_percent"]
    if type(target) not in {int, float} or not math.isfinite(target) or not 0 < target <= 100:
        raise ValueError("coverage target must be finite and in (0,100]")
    scope = value["scope"]
    if not isinstance(scope, list) or not scope or not all(isinstance(item, str) for item in scope):
        raise ValueError("coverage scope must be explicit")
    if len(set(scope)) != len(scope) or not set(scope) <= set(manifest["sources"] + manifest["headers"]):
        raise ValueError("coverage scope must contain unique manifest source/header paths")
    for relative in scope:
        bounded(root, relative)
    bounded(root, value["simulation_contract"], suffix=".json")
    return value


def converter_command(tool: dict) -> list[str]:
    command = list(tool["command"])
    if tool["kind"] == "MSYS2_FIXED_BRIDGE":
        command = [word.replace('exec verilator "$@"', 'exec verilator_coverage "$@"') for word in command]
    else:
        command[0] = str(Path(command[0]).with_name("verilator_coverage"))
    return command


def run_coverage(manifest_path: str, contract_path: str, root: Path) -> dict:
    root = root.resolve(strict=True)
    manifest = validate_manifest(Path(manifest_path), repository_root=root)
    if manifest["parameters"]:
        raise ValueError("parameterized simulation needs a reviewed adapter")
    contract_file = bounded(root, contract_path, suffix=".json")
    coverage = validate_contract(root, manifest, json.loads(contract_file.read_text(encoding="utf-8")))
    simulation, testbench = _contract(root, manifest, Path(coverage["simulation_contract"]))
    paths = sorted(set([manifest_path, contract_path, coverage["simulation_contract"], simulation["testbench"]]
                       + manifest["sources"] + manifest["headers"]))
    inputs = {path: sha256_file(bounded(root, path)) for path in paths}
    output = root / ".vibesilicon/coverage" / uuid.uuid4().hex
    if not output.resolve().is_relative_to(root):
        raise ValueError("coverage output escapes root")
    output.mkdir(parents=True, exist_ok=False)
    tool = _tool()
    execution = {"compile": "NOT_RUN", "run": "NOT_RUN", "pass_token_count": 0}
    metrics = None
    status = "BLOCKED"
    errors = []
    command = None
    try:
        if tool["status"] != "AVAILABLE":
            raise ValueError("Verilator unavailable")
        match = re.search(r"Verilator (\d+)\.", tool["version"] or "")
        if not match or int(match[1]) not in load_policy()["tool_versions"]["verilator"]["accepted_major"]:
            raise ValueError("unapproved Verilator version")
        execution = _run(root, manifest, simulation, testbench, tool, artifact_dir=output, coverage=True)
        if execution != {"compile": "PASS", "run": "PASS", "pass_token_count": 1}:
            status = "FAIL" if "FAIL" in execution.values() else "BLOCKED"
            raise ValueError("self-checking simulation did not pass")
        dat, info = output / "coverage.dat", output / "coverage.info"
        if not dat.is_file() or dat.stat().st_size == 0:
            raise ValueError("simulation produced no coverage data")
        path_arg = _msys_path if tool["kind"] == "MSYS2_FIXED_BRIDGE" else str
        command = converter_command(tool) + ["--write-info", path_arg(info), path_arg(dat)]
        converted = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=60, check=False)
        (output / "conversion.log").write_text(converted.stdout + "\n" + converted.stderr, encoding="utf-8")
        if converted.returncode != 0:
            raise ValueError("coverage converter failed")
        metrics = parse_lcov(info.read_text(encoding="utf-8"), root, coverage["scope"])
        status = "PASS" if metrics["percent"] >= coverage["minimum_percent"] else "FAIL"
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        errors.append(str(exc))
    if inputs != {path: sha256_file(bounded(root, path)) for path in paths}:
        status = "BLOCKED"
        errors.append("inputs changed during coverage run")
    artifacts = {path.relative_to(root).as_posix(): sha256_file(path) for path in output.iterdir() if path.is_file()}
    report = {"schema_version": 1, "scope": "declared_instrumented_line_coverage", "status": status,
              "inputs": inputs, "contract": coverage, "execution": execution, "tool": tool,
              "conversion_command": command, "metrics": metrics, "artifacts": artifacts, "errors": errors,
              "limitations": ["instrumented lines only; not functional/branch/toggle/FSM closure",
                              "no user exclusions; not full G2, hardware validation or production sign-off"],
              "evidence_id": ""}
    report["evidence_id"] = content_id(report, "evidence_id")
    (output / "evidence.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def verify_report(root: Path, report: dict) -> dict:
    if report.get("evidence_id") != content_id(report, "evidence_id"):
        raise ValueError("coverage evidence identity mismatch")
    for relative, digest in (report["inputs"] | report["artifacts"]).items():
        if sha256_file(bounded(root, relative)) != digest:
            raise ValueError("coverage artifact/input changed")
    if report["metrics"] is not None:
        info = [path for path in report["artifacts"] if path.endswith("/coverage.info")]
        if len(info) != 1 or parse_lcov(bounded(root, info[0]).read_text(encoding="utf-8"), root,
                                     report["contract"]["scope"]) != report["metrics"]:
            raise ValueError("coverage metrics mismatch")
        expected = "PASS" if report["metrics"]["percent"] >= report["contract"]["minimum_percent"] else "FAIL"
        if report["status"] == "PASS" and (expected != "PASS" or report["errors"] or
            report["execution"] != {"compile": "PASS", "run": "PASS", "pass_token_count": 1}):
            raise ValueError("coverage PASS contradicts execution/metrics")
    elif report["status"] == "PASS":
        raise ValueError("coverage PASS requires metrics")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest")
    parser.add_argument("contract")
    args = parser.parse_args()
    try:
        report = run_coverage(args.manifest, args.contract, Path.cwd())
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return 2
    print(json.dumps(report))
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
