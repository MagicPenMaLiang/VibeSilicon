#!/usr/bin/env python3
"""Fixed read-only Vivado report collection and content-bound bundle verification."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.evidence_contract import content_id, sha256_file, sha256_bytes, validate_receipt
from scripts.quality_gate.vivado_reports import parse_cdc, parse_drc, parse_timing, parse_utilization

REPORTS = {
    "timing": "report_timing_summary -delay_type min_max -report_unconstrained",
    "cdc": "report_cdc -all_checks_per_endpoint",
    "utilization": "report_utilization",
    "drc": "report_drc",
    "hierarchy": "report_utilization -hierarchical",
    "power": "report_power",
    "clocks": "report_clocks",
    "clock_interaction": "report_clock_interaction",
    "exceptions": "report_exceptions -coverage",
    "methodology": "report_methodology",
    "route": "report_route_status",
}
PARSERS = {"timing": parse_timing, "cdc": parse_cdc, "utilization": parse_utilization, "drc": parse_drc}


def verify_execution(root: Path, execution: dict, tcl: str) -> dict:
    receipt = json.loads(bounded(root, execution["receipt_path"], suffix=".json").read_text(encoding="utf-8"))
    validate_receipt(receipt)
    if receipt["evidence_id"] != execution["evidence_id"] or receipt["status"] != execution["status"]:
        raise ValueError("execution does not match raw receipt")
    if receipt["inputs"].get("tcl_hash") != sha256_bytes(tcl.encode("utf-8")):
        raise ValueError("execution Tcl does not match the fixed plan")
    for artifact in receipt["artifacts"]:
        if sha256_file(bounded(root, artifact["path"])) != artifact["sha256"]:
            raise ValueError("raw execution log changed")
    logs = [artifact for artifact in receipt["artifacts"] if artifact["kind"] == "log"]
    if len(logs) != 1:
        raise ValueError("execution requires exactly one raw log")
    log = json.loads(bounded(root, logs[0]["path"]).read_text(encoding="utf-8"))
    if (log["status"] != receipt["status"] or log["exit_code"] != execution["exit_code"] or
            log["stdout"][-3000:] != execution["stdout_tail"] or
            log["stderr"][-3000:] != execution["stderr_tail"] or
            receipt["command_hash"] != execution["command_hash"]):
        raise ValueError("execution summary disagrees with preserved raw log")
    return receipt


def bounded(root: Path, value: str, *, suffix: str | None = None, exists: bool = True) -> Path:
    if not isinstance(value, str) or not value or any(char in value for char in "{}\n\r\x00"):
        raise ValueError("invalid path")
    path = Path(value)
    if path.is_absolute():
        raise ValueError("path must be repository-relative")
    resolved = (root / path).resolve(strict=exists)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError("path escapes repository")
    if suffix and resolved.suffix.lower() != suffix:
        raise ValueError(f"expected {suffix} file")
    if exists and not resolved.is_file():
        raise ValueError("input must be a file")
    return resolved


def tcl_word(value: str | Path) -> str:
    value = str(value).replace("\\", "/")
    if any(char in value for char in "{}\r\n\x00"):
        raise ValueError("unsafe Tcl word")
    return "{" + value + "}"


def report_plan(root: Path, checkpoint: str, output_dir: str) -> dict:
    root = root.resolve(strict=True)
    dcp = bounded(root, checkpoint, suffix=".dcp")
    output = bounded(root, output_dir, exists=False)
    if output.exists() or not output.is_relative_to(root / ".vibesilicon/reports"):
        raise ValueError("output must be a new run directory under .vibesilicon/reports")
    paths = {name: (output / f"{name}.rpt").relative_to(root).as_posix() for name in REPORTS}
    tcl = f"open_checkpoint {tcl_word(dcp)}\n"
    tcl += "check_timing -verbose -file " + tcl_word(output / "check_timing.rpt") + "\n"
    tcl += "".join(f"{command} -file {tcl_word(root / paths[name])}\n" for name, command in REPORTS.items())
    tcl += "close_design\nexit\n"
    paths["check_timing"] = (output / "check_timing.rpt").relative_to(root).as_posix()
    plan = {"schema_version": 1, "checkpoint": dcp.relative_to(root).as_posix(),
            "checkpoint_sha256": sha256_file(dcp), "reports": paths, "tcl": tcl,
            "risk_class": "R0", "plan_id": ""}
    plan["plan_id"] = content_id(plan, "plan_id")
    return plan


def collect_bundle(root: Path, plan: dict, execution: dict) -> dict:
    if plan.get("plan_id") != content_id(plan, "plan_id"):
        raise ValueError("report plan identity mismatch")
    dcp = bounded(root, plan["checkpoint"], suffix=".dcp")
    if sha256_file(dcp) != plan["checkpoint_sha256"]:
        raise ValueError("checkpoint changed during collection")
    artifacts = {}
    errors = []
    try:
        verify_execution(root, execution, plan["tcl"])
    except (KeyError, OSError, ValueError) as exc:
        errors.append(f"execution: {exc}")
    for name, relative in plan["reports"].items():
        try:
            path = bounded(root, relative)
            if path.stat().st_size == 0:
                raise ValueError("empty report")
            item = {"path": relative, "sha256": sha256_file(path), "metrics": None}
            if name in PARSERS:
                item["metrics"] = PARSERS[name](path)["metrics"]
            artifacts[name] = item
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
    bundle = {"schema_version": 1, "scope": "report_collection", "plan": plan,
              "execution": execution, "artifacts": artifacts, "errors": errors,
              "status": "PASS" if execution.get("status") == "PASS" and not errors else "BLOCKED",
              "limitations": ["collection PASS is not timing/CDC/DRC closure or production sign-off",
                              "raw clock, exception, methodology and route reports require review",
                              "power uses current checkpoint activity assumptions; not measured board power"],
              "evidence_id": ""}
    bundle["evidence_id"] = content_id(bundle, "evidence_id")
    return bundle


def verify_bundle(root: Path, bundle: dict) -> dict:
    if bundle.get("evidence_id") != content_id(bundle, "evidence_id"):
        raise ValueError("report bundle identity mismatch")
    rebuilt = collect_bundle(root, bundle["plan"], bundle["execution"])
    if rebuilt != bundle:
        raise ValueError("report bundle no longer matches artifacts/parser")
    return bundle


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    bundle = verify_bundle(args.root, json.loads(args.bundle.read_text(encoding="utf-8")))
    print(json.dumps({"status": bundle["status"], "evidence_id": bundle["evidence_id"]}))
    return 0 if bundle["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
