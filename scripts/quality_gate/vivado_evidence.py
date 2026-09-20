#!/usr/bin/env python3
"""Create and verify parsed Vivado report evidence receipts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from scripts.evidence_contract import (
        EvidenceContractError,
        artifact_record,
        build_manifest,
        build_receipt,
        sha256_file,
        validate_receipt,
    )
    from scripts.quality_gate.vivado_reports import (
        parse_cdc,
        parse_drc,
        parse_timing,
        parse_utilization,
    )
except ImportError:  # pragma: no cover - standalone script execution
    from evidence_contract import (
        EvidenceContractError,
        artifact_record,
        build_manifest,
        build_receipt,
        sha256_file,
        validate_receipt,
    )
    from quality_gate.vivado_reports import (
        parse_cdc,
        parse_drc,
        parse_timing,
        parse_utilization,
    )


PARSER_SCHEMA_VERSION = 1
LEGACY_TIMESTAMP = "1970-01-01T00:00:00Z"
Parser = Callable[[Path], dict[str, Any]]
REPORT_SPECS: dict[str, tuple[str, Parser]] = {
    "timing_report": ("timing-summary", parse_timing),
    "cdc_report": ("cdc", parse_cdc),
    "utilization_report": ("utilization", parse_utilization),
    "drc_report": ("drc", parse_drc),
}


def _spec(kind: str) -> tuple[str, Parser]:
    try:
        return REPORT_SPECS[kind]
    except KeyError as exc:
        raise EvidenceContractError(f"unsupported parsed Vivado report kind: {kind}") from exc


def _relative(path: Path, root: Path) -> str:
    resolved_root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        return resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise EvidenceContractError(f"report is outside project root: {resolved}") from exc


def create_report_evidence(
    report_path: Path,
    *,
    root: Path,
    kind: str,
    task_id: str,
    tool: Mapping[str, str],
    command_argv: list[str],
    command_cwd: str,
    started_at: str,
    duration_s: float,
    provenance: Mapping[str, str],
    inputs: Mapping[str, str],
    created_at: str | None = None,
) -> dict[str, Any]:
    """Parse one report and bind its metrics to an immutable artifact receipt."""
    parser_name, parser = _spec(kind)
    parsed = parser(report_path)
    artifact = artifact_record(report_path, root, kind)
    manifest = build_manifest(
        project=root.resolve(strict=True).name,
        task_id=task_id,
        root=root,
        artifacts=[(report_path, kind)],
        created_at=created_at or started_at,
        reproduce_commands=[],
        environment={"parser": parser_name, "parser_schema": str(PARSER_SCHEMA_VERSION)},
    )
    receipt = build_receipt(
        task_id=task_id,
        tool=tool,
        inputs=inputs,
        command_argv=command_argv,
        command_cwd=command_cwd,
        started_at=started_at,
        duration_s=duration_s,
        status="PASS",
        metrics=parsed["metrics"],
        artifacts=[artifact],
        parser={"name": parser_name, "schema_version": PARSER_SCHEMA_VERSION},
        provenance=provenance,
    )
    return {"manifest": manifest, "receipt": receipt, "parsed": parsed}


def create_legacy_import_evidence(report_path: Path, *, root: Path, kind: str) -> dict[str, Any]:
    """Wrap a historical report in an explicit, deterministic import receipt."""
    relative = _relative(report_path, root)
    digest = sha256_file(report_path)
    return create_report_evidence(
        report_path,
        root=root,
        kind=kind,
        task_id=f"legacy-import-{kind}-{digest.removeprefix('sha256:')[:16]}",
        tool={"name": "vivado-report", "version": "unknown", "backend": "legacy-import"},
        command_argv=["legacy-import", relative],
        command_cwd=".",
        started_at=LEGACY_TIMESTAMP,
        duration_s=0,
        provenance={"agent": "quality-gate", "prompt_version": "legacy-import-v1"},
        inputs={"report_hash": digest},
        created_at=LEGACY_TIMESTAMP,
    )


def verify_report_evidence(
    receipt: Mapping[str, Any],
    report_path: Path,
    *,
    root: Path,
    kind: str,
) -> dict[str, Any]:
    """Verify receipt identity, artifact bytes, parser version and parsed metrics."""
    validate_receipt(receipt)
    parser_name, parser = _spec(kind)
    if receipt["status"] != "PASS":
        raise EvidenceContractError(f"report evidence status is not PASS: {receipt['status']}")
    if receipt["parser"] != {"name": parser_name, "schema_version": PARSER_SCHEMA_VERSION}:
        raise EvidenceContractError(
            f"report evidence parser must be {parser_name}/v{PARSER_SCHEMA_VERSION}"
        )
    artifacts = receipt["artifacts"]
    if len(artifacts) != 1 or artifacts[0]["kind"] != kind:
        raise EvidenceContractError(f"report evidence must contain exactly one {kind} artifact")
    artifact = artifacts[0]
    relative = _relative(report_path, root)
    if artifact["path"] != relative:
        raise EvidenceContractError(
            f"report evidence path mismatch: expected {relative}, got {artifact['path']}"
        )
    actual_hash = sha256_file(report_path)
    if artifact["sha256"] != actual_hash or artifact["artifact_id"] != actual_hash:
        raise EvidenceContractError("report artifact hash does not match receipt")
    parsed = parser(report_path)
    if receipt["metrics"] != parsed["metrics"]:
        raise EvidenceContractError("report metrics do not match the canonical parser output")
    return {
        "evidence_id": receipt["evidence_id"],
        "task_id": receipt["task_id"],
        "backend": receipt["tool"]["backend"],
        "parser": dict(receipt["parser"]),
        "artifact": dict(artifact),
        "metrics": dict(receipt["metrics"]),
        "tool_version": parsed["tool_version"],
        "design": parsed["design"],
        "design_state": parsed["design_state"],
    }


def load_verified_report(report_path: Path, *, root: Path, kind: str) -> dict[str, Any]:
    """Prefer a persisted sidecar; explicitly import historical reports otherwise."""
    sidecar = report_path.with_suffix(report_path.suffix + ".receipt.json")
    if sidecar.is_file():
        receipt = json.loads(sidecar.read_text(encoding="utf-8"))
        source = "sidecar"
    else:
        receipt = create_legacy_import_evidence(report_path, root=root, kind=kind)["receipt"]
        source = "legacy-import"
    verified = verify_report_evidence(receipt, report_path, root=root, kind=kind)
    verified["receipt_source"] = source
    return verified
