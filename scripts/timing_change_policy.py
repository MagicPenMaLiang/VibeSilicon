#!/usr/bin/env python3
"""Validate evidence-bound timing-closure proposals before any RTL/XDC edit."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
EVIDENCE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PROPOSAL_RE = re.compile(r"^TIMING-[A-Za-z0-9][A-Za-z0-9-]{2,63}$")
SENSITIVE_CONSTRAINTS = {"false_path", "clock_groups", "multicycle"}
BROAD_SELECTORS = (
    r"get_(?:cells|pins|ports|clocks)\s+\*",
    r"\[(?:all_registers|all_clocks)\]",
)


class TimingPolicyError(ValueError):
    pass


def _nonempty_strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise TimingPolicyError(f"{field} must be a non-empty string list")
    if len(value) != len(set(value)):
        raise TimingPolicyError(f"{field} contains duplicates")
    return list(value)


def _evidence(value: Any, field: str) -> str:
    if not isinstance(value, str) or not EVIDENCE_RE.fullmatch(value):
        raise TimingPolicyError(f"{field} must be a content-addressed evidence ID")
    return value


def validate_proposal(proposal: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "proposal_id",
        "analysis_evidence_id",
        "hypothesis",
        "changes",
        "constraints",
        "invariants",
        "required_gates",
        "max_iterations",
        "approval_status",
    }
    missing = required - set(proposal)
    unknown = set(proposal) - required
    if missing or unknown:
        raise TimingPolicyError(
            f"proposal fields missing={sorted(missing)} unknown={sorted(unknown)}"
        )
    if proposal["schema_version"] != SCHEMA_VERSION:
        raise TimingPolicyError("unsupported schema_version")
    if not isinstance(proposal["proposal_id"], str) or not PROPOSAL_RE.fullmatch(
        proposal["proposal_id"]
    ):
        raise TimingPolicyError("proposal_id must match TIMING-<id>")
    _evidence(proposal["analysis_evidence_id"], "analysis_evidence_id")
    if not isinstance(proposal["hypothesis"], str) or not proposal["hypothesis"].strip():
        raise TimingPolicyError("hypothesis must be non-empty")
    changes = proposal["changes"]
    if not isinstance(changes, list) or not changes:
        raise TimingPolicyError("changes must be a non-empty list")
    for change in changes:
        if not isinstance(change, Mapping) or set(change) != {"path", "kind", "description"}:
            raise TimingPolicyError("each change requires path/kind/description")
        if change["kind"] not in {"rtl", "xdc", "strategy"}:
            raise TimingPolicyError("change kind must be rtl/xdc/strategy")
        if not all(isinstance(change[key], str) and change[key].strip() for key in ("path", "description")):
            raise TimingPolicyError("change path and description must be non-empty")
        normalized = PurePosixPath(change["path"].replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise TimingPolicyError("change path must stay relative to the project root")
        if change["kind"] == "rtl" and normalized.suffix.lower() not in {".v", ".sv", ".vh", ".svh"}:
            raise TimingPolicyError("rtl change path must name an RTL source")
        if change["kind"] == "xdc" and normalized.suffix.lower() != ".xdc":
            raise TimingPolicyError("xdc change path must name an .xdc file")
    constraints = proposal["constraints"]
    if not isinstance(constraints, list):
        raise TimingPolicyError("constraints must be a list")
    for constraint in constraints:
        if not isinstance(constraint, Mapping):
            raise TimingPolicyError("constraint entries must be objects")
        required_constraint = {"type", "command", "from", "to", "proof_evidence_id"}
        allowed_constraint = required_constraint | {"setup_cycles", "hold_cycles"}
        if set(constraint) - allowed_constraint or required_constraint - set(constraint):
            raise TimingPolicyError("constraint requires type/command/from/to/proof_evidence_id")
        if constraint["type"] not in SENSITIVE_CONSTRAINTS:
            raise TimingPolicyError("only sensitive constraint types belong in constraints")
        command = constraint["command"]
        if not isinstance(command, str) or not command.strip():
            raise TimingPolicyError("constraint command must be non-empty")
        if any(re.search(pattern, command, re.I) for pattern in BROAD_SELECTORS):
            raise TimingPolicyError("broad wildcard/all-register constraint is forbidden")
        for endpoint in ("from", "to"):
            if not isinstance(constraint[endpoint], str) or not constraint[endpoint].strip():
                raise TimingPolicyError(f"constraint {endpoint} must be explicit")
        _evidence(constraint["proof_evidence_id"], "constraint proof_evidence_id")
        if constraint["type"] == "multicycle":
            setup = constraint.get("setup_cycles")
            hold = constraint.get("hold_cycles")
            if (
                isinstance(setup, bool)
                or not isinstance(setup, int)
                or setup < 2
                or isinstance(hold, bool)
                or not isinstance(hold, int)
                or hold != setup - 1
            ):
                raise TimingPolicyError("multicycle requires setup N and paired hold N-1")
        elif "setup_cycles" in constraint or "hold_cycles" in constraint:
            raise TimingPolicyError("setup_cycles/hold_cycles are only valid for multicycle")
    _nonempty_strings(proposal["invariants"], "invariants")
    _nonempty_strings(proposal["required_gates"], "required_gates")
    if (
        isinstance(proposal["max_iterations"], bool)
        or not isinstance(proposal["max_iterations"], int)
        or not 1 <= proposal["max_iterations"] <= 3
    ):
        raise TimingPolicyError("max_iterations must be between 1 and 3")
    if proposal["approval_status"] not in {"PENDING", "APPROVED"}:
        raise TimingPolicyError("approval_status must be PENDING or APPROVED")
    result = json.loads(json.dumps(proposal))
    result["decision"] = (
        "APPROVED_FOR_EXECUTION"
        if proposal["approval_status"] == "APPROVED"
        else "READY_FOR_APPROVAL"
    )
    result["risk_class"] = "R2"
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", type=Path)
    args = parser.parse_args(argv)
    try:
        proposal = json.loads(args.proposal.read_text(encoding="utf-8"))
        result = validate_proposal(proposal)
    except (OSError, json.JSONDecodeError, TimingPolicyError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "PASS", **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
