#!/usr/bin/env python3
"""Collect repository-safe diagnostics from a fixed ORFS reference signoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts import asic_toolchain_provenance as provenance
except ImportError:  # pragma: no cover - standalone execution
    import asic_toolchain_provenance as provenance


SCHEMA_VERSION = 1
STATUS = "A04_REFERENCE_SIGNOFF_DIAGNOSTIC_READY"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
VARIANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
METRIC_KEYS = {
    "setup_wns_ns": "finish__timing__setup__ws",
    "setup_tns_ns": "finish__timing__setup__tns",
    "setup_violation_count": "finish__timing__drv__setup_violation_count",
    "hold_tns_ns": "finish__timing__hold__tns",
    "hold_violation_count": "finish__timing__drv__hold_violation_count",
    "standard_cell_area_um2": "finish__design__instance__area__stdcell",
    "total_power_w": "finish__power__total",
}
ARTIFACT_NAMES = (
    "clock_period",
    "drc_count_report",
    "final_gds",
    "final_odb",
    "lvs_db",
    "lvs_log",
    "metrics",
    "signoff_drc_db",
)
LIMITATIONS = [
    "NOT_A03_OWNER_APPROVED_RUN",
    "NOT_A04_BASELINE_OR_REPLAY",
    "NOT_INDEPENDENTLY_REVIEWED",
    "NO_ACCEPTANCE_AUTHORITY",
]
ROOT_FIELDS = {
    "schema_version",
    "evidence_id",
    "status",
    "profile_id",
    "profile_sha256",
    "toolchain_provenance_id",
    "flow",
    "metrics",
    "checks",
    "artifacts",
    "limitations",
    "repository_content",
}


class AsicReferenceSignoffError(ValueError):
    """Raised when reference signoff diagnostics are incomplete or unsafe."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AsicReferenceSignoffError(
            f"cannot hash reference artifact: {path.name}"
        ) from exc
    return "sha256:" + digest.hexdigest()


def _content_id(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "evidence_id"}
    return _sha256_value(payload)


def _fields(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise AsicReferenceSignoffError(f"{label} fields are incomplete or unknown")
    return value


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AsicReferenceSignoffError(f"cannot load JSON: {path.name}") from exc


def _read_text(path: Path, label: str, maximum: int = 16 * 1024 * 1024) -> str:
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size <= 0:
            raise AsicReferenceSignoffError(f"{label} is empty")
        if resolved.stat().st_size > maximum:
            raise AsicReferenceSignoffError(f"{label} is too large")
        return resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AsicReferenceSignoffError(f"cannot read {label}") from exc


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AsicReferenceSignoffError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise AsicReferenceSignoffError(f"{label} must be finite")
    return number


def _count(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AsicReferenceSignoffError(f"{label} must be a non-negative integer")
    return value


def _artifact(name: str, path: Path) -> dict[str, Any]:
    try:
        resolved = path.resolve(strict=True)
        size = resolved.stat().st_size
    except OSError as exc:
        raise AsicReferenceSignoffError(f"reference artifact is missing: {name}") from exc
    if not resolved.is_file() or size <= 0:
        raise AsicReferenceSignoffError(f"reference artifact is empty: {name}")
    return {"name": name, "sha256": _sha256_file(resolved), "bytes": size}


def collect_reference_signoff(
    profile: Mapping[str, Any],
    toolchain: Mapping[str, Any],
    *,
    variant: str,
    metrics_json: Path,
    clock_period_report: Path,
    drc_count_report: Path,
    lvs_log: Path,
    final_gds: Path,
    signoff_drc_db: Path,
    lvs_db: Path,
    final_odb: Path,
) -> dict[str, Any]:
    try:
        provenance.validate_provenance(toolchain, profile)
    except provenance.AsicToolchainProvenanceError as exc:
        raise AsicReferenceSignoffError(str(exc)) from exc
    if not isinstance(variant, str) or not VARIANT_RE.fullmatch(variant):
        raise AsicReferenceSignoffError("reference flow variant is invalid")
    reference = profile.get("reference")
    if not isinstance(reference, Mapping):
        raise AsicReferenceSignoffError("profile reference is missing")

    raw_metrics = _load(metrics_json)
    if not isinstance(raw_metrics, Mapping):
        raise AsicReferenceSignoffError("reference metrics must be an object")
    metrics: dict[str, Any] = {}
    for name, source in METRIC_KEYS.items():
        if source not in raw_metrics:
            raise AsicReferenceSignoffError(f"reference metric is missing: {source}")
        value = raw_metrics[source]
        metrics[name] = (
            _count(value, name) if name.endswith("violation_count") else _number(value, name)
        )

    clock_text = _read_text(clock_period_report, "clock period report", 1024).strip()
    try:
        metrics["clock_period_ns"] = _number(float(clock_text), "clock period")
    except ValueError as exc:
        raise AsicReferenceSignoffError("clock period report is invalid") from exc
    if metrics["clock_period_ns"] <= 0:
        raise AsicReferenceSignoffError("clock period must be positive")

    drc_text = _read_text(drc_count_report, "DRC count report", 1024)
    drc_match = re.fullmatch(r"\s*([0-9]+)\s*", drc_text)
    if not drc_match:
        raise AsicReferenceSignoffError("DRC count report is invalid")
    drc_count = int(drc_match.group(1))
    lvs_text = _read_text(lvs_log, "LVS log")
    lvs_marker = "INFO : Congratulations! Netlists match."
    lvs_clean = lvs_text.count(lvs_marker) == 1 and not re.search(
        r"\b(?:mismatch|not[ -]?match|error)\b", lvs_text, re.IGNORECASE
    )
    timing_clean = (
        metrics["setup_wns_ns"] >= 0
        and metrics["setup_tns_ns"] == 0
        and metrics["setup_violation_count"] == 0
        and metrics["hold_tns_ns"] == 0
        and metrics["hold_violation_count"] == 0
    )

    paths = {
        "clock_period": clock_period_report,
        "drc_count_report": drc_count_report,
        "final_gds": final_gds,
        "final_odb": final_odb,
        "lvs_db": lvs_db,
        "lvs_log": lvs_log,
        "metrics": metrics_json,
        "signoff_drc_db": signoff_drc_db,
    }
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "evidence_id": "",
        "status": STATUS,
        "profile_id": profile.get("profile_id"),
        "profile_sha256": toolchain["profile_sha256"],
        "toolchain_provenance_id": toolchain["provenance_id"],
        "flow": {
            "design_id": reference.get("design_id"),
            "variant": variant,
            "target": "finish_drc_lvs",
            "diagnostic_overrides": [],
        },
        "metrics": metrics,
        "checks": {
            "signoff_drc_count": drc_count,
            "drc_clean": drc_count == 0,
            "lvs_clean": lvs_clean,
            "timing_clean": timing_clean,
            "physical_signoff_clean": drc_count == 0 and lvs_clean,
        },
        "artifacts": [_artifact(name, paths[name]) for name in ARTIFACT_NAMES],
        "limitations": LIMITATIONS,
        "repository_content": "HASHES_AND_SANITIZED_METRICS_ONLY",
    }
    result["evidence_id"] = _content_id(result)
    validate_reference_signoff(result, profile, toolchain)
    return result


def validate_reference_signoff(
    value: Any, profile: Mapping[str, Any], toolchain: Mapping[str, Any]
) -> None:
    try:
        provenance.validate_provenance(toolchain, profile)
    except provenance.AsicToolchainProvenanceError as exc:
        raise AsicReferenceSignoffError(str(exc)) from exc
    evidence = _fields(value, ROOT_FIELDS, "reference signoff evidence")
    if evidence["schema_version"] != SCHEMA_VERSION or evidence["status"] != STATUS:
        raise AsicReferenceSignoffError("reference signoff schema or status is invalid")
    if evidence["evidence_id"] != _content_id(evidence):
        raise AsicReferenceSignoffError("reference signoff content ID mismatch")
    if (
        evidence["profile_id"] != profile.get("profile_id")
        or evidence["profile_sha256"] != toolchain.get("profile_sha256")
        or evidence["toolchain_provenance_id"] != toolchain.get("provenance_id")
    ):
        raise AsicReferenceSignoffError("reference signoff provenance binding is invalid")
    flow = _fields(
        evidence["flow"],
        {"design_id", "variant", "target", "diagnostic_overrides"},
        "reference flow",
    )
    if (
        flow["design_id"] != profile["reference"]["design_id"]
        or not VARIANT_RE.fullmatch(str(flow["variant"]))
        or flow["target"] != "finish_drc_lvs"
        or flow["diagnostic_overrides"] != []
    ):
        raise AsicReferenceSignoffError("reference flow identity is invalid")
    metrics = _fields(
        evidence["metrics"], {*METRIC_KEYS, "clock_period_ns"}, "reference metrics"
    )
    for name in METRIC_KEYS:
        if name.endswith("violation_count"):
            _count(metrics[name], name)
        else:
            _number(metrics[name], name)
    if _number(metrics["clock_period_ns"], "clock period") <= 0:
        raise AsicReferenceSignoffError("clock period must be positive")
    if metrics["setup_tns_ns"] > 0 or metrics["hold_tns_ns"] > 0:
        raise AsicReferenceSignoffError("timing TNS must not be positive")
    if metrics["standard_cell_area_um2"] <= 0 or metrics["total_power_w"] < 0:
        raise AsicReferenceSignoffError("reference area or power is invalid")
    checks = _fields(
        evidence["checks"],
        {
            "signoff_drc_count",
            "drc_clean",
            "lvs_clean",
            "timing_clean",
            "physical_signoff_clean",
        },
        "reference checks",
    )
    drc_count = _count(checks["signoff_drc_count"], "signoff DRC count")
    for name in ("drc_clean", "lvs_clean", "timing_clean", "physical_signoff_clean"):
        if not isinstance(checks[name], bool):
            raise AsicReferenceSignoffError(f"{name} must be boolean")
    expected_timing = (
        metrics["setup_wns_ns"] >= 0
        and metrics["setup_tns_ns"] == 0
        and metrics["setup_violation_count"] == 0
        and metrics["hold_tns_ns"] == 0
        and metrics["hold_violation_count"] == 0
    )
    if (
        checks["drc_clean"] != (drc_count == 0)
        or checks["timing_clean"] != expected_timing
        or checks["physical_signoff_clean"]
        != (checks["drc_clean"] and checks["lvs_clean"])
    ):
        raise AsicReferenceSignoffError("reference check derivation is inconsistent")
    artifacts = evidence["artifacts"]
    if not isinstance(artifacts, list) or [item.get("name") for item in artifacts] != list(
        ARTIFACT_NAMES
    ):
        raise AsicReferenceSignoffError("reference artifacts are incomplete or out of order")
    for item in artifacts:
        item = _fields(item, {"name", "sha256", "bytes"}, "reference artifact")
        if not HASH_RE.fullmatch(str(item["sha256"])):
            raise AsicReferenceSignoffError("reference artifact hash is invalid")
        if isinstance(item["bytes"], bool) or not isinstance(item["bytes"], int) or item["bytes"] <= 0:
            raise AsicReferenceSignoffError("reference artifact size is invalid")
    if evidence["limitations"] != LIMITATIONS:
        raise AsicReferenceSignoffError("reference evidence limitations are invalid")
    if evidence["repository_content"] != "HASHES_AND_SANITIZED_METRICS_ONLY":
        raise AsicReferenceSignoffError("reference repository boundary is invalid")


def _write(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise AsicReferenceSignoffError(f"refusing to overwrite output: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect")
    collect.add_argument("--profile", type=Path, required=True)
    collect.add_argument("--toolchain-provenance", type=Path, required=True)
    collect.add_argument("--variant", required=True)
    for name in (
        "metrics_json",
        "clock_period_report",
        "drc_count_report",
        "lvs_log",
        "final_gds",
        "signoff_drc_db",
        "lvs_db",
        "final_odb",
    ):
        collect.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("evidence", type=Path)
    verify.add_argument("--profile", type=Path, required=True)
    verify.add_argument("--toolchain-provenance", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        profile = _load(args.profile)
        toolchain = _load(args.toolchain_provenance)
        if args.command == "collect":
            result = collect_reference_signoff(
                profile,
                toolchain,
                variant=args.variant,
                metrics_json=args.metrics_json,
                clock_period_report=args.clock_period_report,
                drc_count_report=args.drc_count_report,
                lvs_log=args.lvs_log,
                final_gds=args.final_gds,
                signoff_drc_db=args.signoff_drc_db,
                lvs_db=args.lvs_db,
                final_odb=args.final_odb,
            )
            _write(args.output, result)
        else:
            validate_reference_signoff(
                _load(args.evidence), profile, toolchain
            )
    except AsicReferenceSignoffError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
