#!/usr/bin/env python3
"""Decide formal/equivalence applicability and validate normalized proof evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
EVIDENCE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ASSESSMENT_RE = re.compile(r"^FORMAL-[A-Za-z0-9][A-Za-z0-9-]{2,63}$")
CHANGE_KINDS = {
    "combinational_refactor",
    "arithmetic",
    "width_signedness",
    "sequential_refactor",
    "pipeline",
    "state_encoding",
    "state_machine",
    "protocol",
    "reset",
    "cdc",
    "constraint_only",
    "vendor_ip_update",
}
EQUIVALENCE_COMB = {"combinational_refactor", "arithmetic", "width_signedness"}
EQUIVALENCE_SEQ = {"sequential_refactor", "pipeline", "state_encoding"}
PROPERTY_CHECKS = {"state_machine", "protocol", "reset", "cdc", "vendor_ip_update"}
PROOF_MODES = {
    "combinational_equivalence",
    "sequential_equivalence",
    "property_checking",
}
BROAD_ASSUMPTIONS = (
    r"assume\s*\(\s*(?:1'b)?0\s*\)",
    r"all\s+inputs?\s+(?:are\s+)?stable",
    r"disable\s+all",
    r"exclude\s+all",
)


class FormalPolicyError(ValueError):
    pass


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FormalPolicyError(f"{field} must be non-empty")
    return value


def _evidence(value: Any, field: str) -> str:
    if not isinstance(value, str) or not EVIDENCE_RE.fullmatch(value):
        raise FormalPolicyError(f"{field} must be a content-addressed evidence ID")
    return value


def _relative_rtl_paths(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise FormalPolicyError("rtl_files must be a non-empty list")
    paths: list[str] = []
    for raw in value:
        _string(raw, "rtl_files item")
        path = PurePosixPath(raw.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise FormalPolicyError("rtl_files must stay relative to the project root")
        if path.suffix.lower() not in {".v", ".sv", ".vh", ".svh"}:
            raise FormalPolicyError("rtl_files must contain only Verilog/SystemVerilog sources")
        paths.append(path.as_posix())
    if len(paths) != len(set(paths)):
        raise FormalPolicyError("rtl_files contains duplicates")
    return paths


def _required_modes(spec: Mapping[str, Any]) -> list[str]:
    kinds = set(spec["change_kinds"])
    modes: set[str] = set()
    if kinds & EQUIVALENCE_COMB:
        if spec["stateful"] or spec["latency_changed"]:
            modes.add("sequential_equivalence")
        else:
            modes.add("combinational_equivalence")
    if kinds & EQUIVALENCE_SEQ:
        modes.add("sequential_equivalence")
    if kinds & PROPERTY_CHECKS:
        modes.add("property_checking")
    if spec["contains_cdc"] or spec["clock_domains"] > 1:
        modes.update({"property_checking", "cdc_analysis"})
    return sorted(modes)


def validate_assessment(spec: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "assessment_id",
        "top",
        "rtl_files",
        "change_kinds",
        "stateful",
        "latency_changed",
        "latency_contract",
        "clock_domains",
        "reset_model",
        "contains_cdc",
        "contains_vendor_ip",
        "blackbox_contracts",
        "properties",
        "assumptions",
        "tool",
        "result",
    }
    missing = required - set(spec)
    unknown = set(spec) - required
    if missing or unknown:
        raise FormalPolicyError(
            f"assessment fields missing={sorted(missing)} unknown={sorted(unknown)}"
        )
    if spec["schema_version"] != SCHEMA_VERSION:
        raise FormalPolicyError("unsupported schema_version")
    if not isinstance(spec["assessment_id"], str) or not ASSESSMENT_RE.fullmatch(
        spec["assessment_id"]
    ):
        raise FormalPolicyError("assessment_id must match FORMAL-<id>")
    _string(spec["top"], "top")
    _relative_rtl_paths(spec["rtl_files"])
    kinds = spec["change_kinds"]
    if (
        not isinstance(kinds, list)
        or not kinds
        or len(kinds) != len(set(kinds))
        or not set(kinds) <= CHANGE_KINDS
    ):
        raise FormalPolicyError("change_kinds is empty, duplicated, or unsupported")
    for field in ("stateful", "latency_changed", "contains_cdc", "contains_vendor_ip"):
        if not isinstance(spec[field], bool):
            raise FormalPolicyError(f"{field} must be boolean")
    latency_contract = spec["latency_contract"]
    if spec["latency_changed"]:
        _string(latency_contract, "latency_contract")
    elif latency_contract is not None:
        raise FormalPolicyError("latency_contract must be null when latency is unchanged")
    if (
        isinstance(spec["clock_domains"], bool)
        or not isinstance(spec["clock_domains"], int)
        or spec["clock_domains"] < 1
    ):
        raise FormalPolicyError("clock_domains must be a positive integer")
    if spec["reset_model"] not in {"sync", "async", "mixed", "none"}:
        raise FormalPolicyError("reset_model is unsupported")

    blackboxes = spec["blackbox_contracts"]
    if not isinstance(blackboxes, list):
        raise FormalPolicyError("blackbox_contracts must be a list")
    for item in blackboxes:
        if not isinstance(item, Mapping) or set(item) != {"instance", "contract", "evidence_id"}:
            raise FormalPolicyError("blackbox contract requires instance/contract/evidence_id")
        _string(item["instance"], "blackbox instance")
        _string(item["contract"], "blackbox contract")
        _evidence(item["evidence_id"], "blackbox evidence_id")
    if spec["contains_vendor_ip"] and not blackboxes:
        raise FormalPolicyError("vendor IP requires explicit blackbox boundary contracts")

    properties = spec["properties"]
    if not isinstance(properties, list):
        raise FormalPolicyError("properties must be a list")
    property_ids: set[str] = set()
    property_kinds: dict[str, str] = {}
    for item in properties:
        if not isinstance(item, Mapping) or set(item) != {"id", "kind", "description"}:
            raise FormalPolicyError("property requires id/kind/description")
        property_id = _string(item["id"], "property id")
        if property_id in property_ids:
            raise FormalPolicyError("property IDs must be unique")
        if item["kind"] not in {"assert", "cover"}:
            raise FormalPolicyError("property kind must be assert or cover")
        _string(item["description"], "property description")
        property_ids.add(property_id)
        property_kinds[property_id] = item["kind"]

    assumptions = spec["assumptions"]
    if not isinstance(assumptions, list):
        raise FormalPolicyError("assumptions must be a list")
    for item in assumptions:
        if not isinstance(item, Mapping) or set(item) != {
            "id",
            "description",
            "justification",
            "evidence_id",
        }:
            raise FormalPolicyError(
                "assumption requires id/description/justification/evidence_id"
            )
        _string(item["id"], "assumption id")
        description = _string(item["description"], "assumption description")
        _string(item["justification"], "assumption justification")
        _evidence(item["evidence_id"], "assumption evidence_id")
        if any(re.search(pattern, description, re.I) for pattern in BROAD_ASSUMPTIONS):
            raise FormalPolicyError("vacuous or broad assumption is forbidden")

    tool = spec["tool"]
    if not isinstance(tool, Mapping) or set(tool) != {
        "engine",
        "available",
        "version",
        "probe_evidence_id",
    }:
        raise FormalPolicyError("tool requires engine/available/version/probe_evidence_id")
    _string(tool["engine"], "tool engine")
    _evidence(tool["probe_evidence_id"], "tool probe_evidence_id")
    if not isinstance(tool["available"], bool):
        raise FormalPolicyError("tool available must be boolean")
    if tool["available"]:
        _string(tool["version"], "tool version")
    elif tool["version"] is not None:
        raise FormalPolicyError("unavailable tool version must be null")

    modes = _required_modes(spec)
    formal_modes = sorted(set(modes) & PROOF_MODES)
    if formal_modes and "property_checking" in formal_modes:
        if "assert" not in property_kinds.values() or "cover" not in property_kinds.values():
            raise FormalPolicyError("property checking requires assert and cover properties")

    if set(kinds) == {"constraint_only"}:
        if spec["result"] is not None:
            raise FormalPolicyError("constraint-only assessment must not attach a formal result")
        return {
            **json.loads(json.dumps(spec)),
            "applicability": "NOT_APPLICABLE",
            "decision": "USE_TIMING_AND_CDC_GATES",
            "required_modes": [],
        }
    if "constraint_only" in kinds:
        raise FormalPolicyError("constraint_only cannot be mixed with RTL change kinds")
    if not formal_modes:
        raise FormalPolicyError("change classification produced no formal proof mode")
    if not tool["available"]:
        return {
            **json.loads(json.dumps(spec)),
            "applicability": "REQUIRED",
            "decision": "BLOCKED",
            "required_modes": modes,
            "reason": "required formal tool is unavailable",
        }

    result = spec["result"]
    if result is None:
        return {
            **json.loads(json.dumps(spec)),
            "applicability": "REQUIRED",
            "decision": "READY_TO_RUN",
            "required_modes": modes,
        }
    required_result = {
        "status",
        "evidence_id",
        "modes_completed",
        "properties_proven",
        "covers_reached",
        "vacuity_checked",
        "proof_kind",
        "depth",
    }
    if not isinstance(result, Mapping) or set(result) != required_result:
        raise FormalPolicyError("result fields are incomplete or unknown")
    if result["status"] not in {"PASS", "FAIL", "ERROR", "INCONCLUSIVE"}:
        raise FormalPolicyError("formal result status is unsupported")
    if result["status"] != "PASS":
        return {
            **json.loads(json.dumps(spec)),
            "applicability": "REQUIRED",
            "decision": "BLOCKED",
            "required_modes": modes,
            "reason": f"formal result is {result['status']}",
        }
    _evidence(result["evidence_id"], "formal result evidence_id")
    for field in ("modes_completed", "properties_proven", "covers_reached"):
        values = result[field]
        if not isinstance(values, list) or len(values) != len(set(values)):
            raise FormalPolicyError(f"{field} must be a unique string list")
        if not all(isinstance(value, str) and value for value in values):
            raise FormalPolicyError(f"{field} must contain strings")
    missing_modes = sorted(set(formal_modes) - set(result["modes_completed"]))
    assert_ids = {key for key, kind in property_kinds.items() if kind == "assert"}
    cover_ids = {key for key, kind in property_kinds.items() if kind == "cover"}
    missing_asserts = sorted(assert_ids - set(result["properties_proven"]))
    missing_covers = sorted(cover_ids - set(result["covers_reached"]))
    if missing_modes or missing_asserts or missing_covers:
        raise FormalPolicyError(
            "PASS result has missing proof obligations: "
            f"modes={missing_modes} asserts={missing_asserts} covers={missing_covers}"
        )
    if result["vacuity_checked"] is not True:
        raise FormalPolicyError("PASS result requires vacuity_checked=true")
    if result["proof_kind"] not in {"bounded", "unbounded"}:
        raise FormalPolicyError("proof_kind must be bounded or unbounded")
    depth = result["depth"]
    if result["proof_kind"] == "bounded":
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
            raise FormalPolicyError("bounded proof requires positive depth")
    elif depth is not None:
        raise FormalPolicyError("unbounded proof depth must be null")
    return {
        **json.loads(json.dumps(spec)),
        "applicability": "REQUIRED",
        "decision": "PASS",
        "required_modes": modes,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assessment", type=Path)
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.assessment.read_text(encoding="utf-8"))
        result = validate_assessment(value)
    except (OSError, json.JSONDecodeError, FormalPolicyError) as exc:
        print(json.dumps({"status": "ERROR", "decision": "BLOCKED", "reason": str(exc)}))
        return 2
    allowed = {"PASS", "READY_TO_RUN", "USE_TIMING_AND_CDC_GATES"}
    status = "PASS" if result["decision"] in allowed else "BLOCKED"
    print(json.dumps({"status": status, **result}, ensure_ascii=False, indent=2))
    return 0 if result["decision"] in allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
