"""Build and verify fail-closed product contracts for generic FPGA/ASIC IP.

This assessor does not execute EDA, inspect raw customer inputs, approve fixed-point
choices, or authorize a product release. It only validates sanitized declarations,
fixed capability priorities, evidence identities, and the next human review gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_PROFILE = Path("config/ip_productization_profile.json")
CAPABILITY_IDS = ("C1", "C2", "C3", "C4", "C5", "C6")
TOP_FIELDS = {
    "schema_version",
    "profile_id",
    "ip",
    "requested_state",
    "capabilities",
    "security",
}
OUTPUT_FIELDS = TOP_FIELDS | {"contract_id", "profile_sha256", "assessment"}
IP_FIELDS = {
    "ip_id",
    "release_candidate",
    "delivery_target",
    "owner",
    "author",
    "confidentiality",
}
CAPABILITY_FIELDS = {
    "id",
    "name",
    "priority_stars",
    "status",
    "owner_approved",
    "reviewer",
    "evidence_ids",
    "acceptance_summary",
}
SECURITY_FIELDS = {
    "raw_customer_spec_present",
    "raw_customer_rtl_present",
    "external_model_export",
    "repository_content",
}
ASSESSMENT_FIELDS = {
    "status",
    "next_gate",
    "required_capabilities",
    "passed_capabilities",
    "blocking_capabilities",
    "non_blocking_capabilities",
    "priority_policy",
    "human_release_required",
}
HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{2,63}")
PLACEHOLDER_RE = re.compile(r"(?:REPLACE_ME|TBD|TODO|PLACEHOLDER)", re.IGNORECASE)
LOCATION_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\.\.[\\/]|file://|https?://)", re.IGNORECASE)


class IpProductizationContractError(ValueError):
    """Raised when a IP productization contract is incomplete or inconsistent."""


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _content_id(value: Mapping[str, Any], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _file_id(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - value.keys())
    extra = sorted(value.keys() - expected)
    if missing or extra:
        raise IpProductizationContractError(
            f"{label} fields do not match contract; missing={missing}, extra={extra}"
        )


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IpProductizationContractError(f"{label} must be an object")
    return value


def _non_placeholder(value: Any, label: str, *, minimum: int = 2) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise IpProductizationContractError(f"{label} must be a non-empty string")
    if PLACEHOLDER_RE.search(value):
        raise IpProductizationContractError(f"{label} contains a placeholder")
    if LOCATION_RE.search(value):
        raise IpProductizationContractError(f"{label} must not contain a path or URL")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IpProductizationContractError(f"JSON root must be an object: {path}")
    return value


def validate_profile(profile: Mapping[str, Any]) -> None:
    fields = {
        "schema_version",
        "profile_id",
        "capabilities",
        "release_gates",
        "one_star_policy",
        "security",
    }
    _exact_fields(profile, fields, "profile")
    if profile["schema_version"] != SCHEMA_VERSION:
        raise IpProductizationContractError("unsupported profile schema_version")
    profile_id = _non_placeholder(profile["profile_id"], "profile_id", minimum=3)
    if not IDENTIFIER_RE.fullmatch(profile_id):
        raise IpProductizationContractError("profile_id is not a safe identifier")

    capabilities = profile["capabilities"]
    if not isinstance(capabilities, list) or len(capabilities) != len(CAPABILITY_IDS):
        raise IpProductizationContractError("profile must define exactly C1-C6")
    observed_ids: list[str] = []
    for item in capabilities:
        capability = _mapping(item, "profile capability")
        _exact_fields(capability, {"id", "name", "priority_stars"}, "profile capability")
        observed_ids.append(capability["id"])
        _non_placeholder(capability["name"], f"{capability['id']} profile name", minimum=3)
        if capability["priority_stars"] not in {3, 5}:
            raise IpProductizationContractError("core C1-C6 priority must be three or five stars")
    if tuple(observed_ids) != CAPABILITY_IDS:
        raise IpProductizationContractError("profile capabilities must be ordered C1-C6")

    gates = _mapping(profile["release_gates"], "release_gates")
    _exact_fields(gates, {"FPGA", "ASIC"}, "release_gates")
    if gates["FPGA"] != ["C1", "C2", "C3", "C5"]:
        raise IpProductizationContractError("FPGA release gates must be C1/C2/C3/C5")
    if gates["ASIC"] != ["C1", "C2", "C3", "C4", "C5"]:
        raise IpProductizationContractError("ASIC release gates must add C4")

    one_star = _mapping(profile["one_star_policy"], "one_star_policy")
    _exact_fields(one_star, {"scope", "core_capability_allowed", "release_gate"}, "one_star_policy")
    if one_star != {
        "scope": "DEFERRED_OPTIONAL_CAPABILITY_ONLY",
        "core_capability_allowed": False,
        "release_gate": False,
    }:
        raise IpProductizationContractError("one-star work must remain deferred and non-gating")

    security = _mapping(profile["security"], "profile security")
    expected_security = {
        "repository_content": "HASHES_AND_SANITIZED_SUMMARIES_ONLY",
        "allow_customer_spec": False,
        "allow_customer_rtl": False,
        "allow_external_model_export": False,
    }
    if security != expected_security:
        raise IpProductizationContractError("profile security boundary has changed")


def _profile_capabilities(profile: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {item["id"]: item for item in profile["capabilities"]}


def validate_declaration(declaration: Mapping[str, Any], profile: Mapping[str, Any]) -> None:
    validate_profile(profile)
    _exact_fields(declaration, TOP_FIELDS, "IP productization declaration")
    if declaration["schema_version"] != SCHEMA_VERSION:
        raise IpProductizationContractError("unsupported declaration schema_version")
    if declaration["profile_id"] != profile["profile_id"]:
        raise IpProductizationContractError("declaration profile_id does not match profile")

    ip = _mapping(declaration["ip"], "ip")
    _exact_fields(ip, IP_FIELDS, "ip")
    for field in ("ip_id", "release_candidate"):
        value = _non_placeholder(ip[field], f"ip.{field}", minimum=3)
        if not IDENTIFIER_RE.fullmatch(value):
            raise IpProductizationContractError(f"ip.{field} is not a safe identifier")
    owner = _non_placeholder(ip["owner"], "ip.owner")
    author = _non_placeholder(ip["author"], "ip.author")
    if owner == author:
        raise IpProductizationContractError("ip owner must be independent from declaration author")
    if ip["delivery_target"] not in {"FPGA", "ASIC"}:
        raise IpProductizationContractError("delivery_target must be FPGA or ASIC")
    if ip["confidentiality"] not in {"PUBLIC", "INTERNAL", "CONFIDENTIAL_HASH_ONLY"}:
        raise IpProductizationContractError("unsupported confidentiality")
    if declaration["requested_state"] not in {"DRAFT", "READY_FOR_OWNER_REVIEW"}:
        raise IpProductizationContractError("unsupported requested_state")

    items = declaration["capabilities"]
    if not isinstance(items, list) or len(items) != len(CAPABILITY_IDS):
        raise IpProductizationContractError("declaration must contain exactly C1-C6")
    profile_items = _profile_capabilities(profile)
    observed_ids: list[str] = []
    for raw_item in items:
        item = _mapping(raw_item, "capability")
        _exact_fields(item, CAPABILITY_FIELDS, "capability")
        capability_id = item["id"]
        if capability_id not in profile_items:
            raise IpProductizationContractError(f"unknown capability: {capability_id}")
        observed_ids.append(capability_id)
        expected = profile_items[capability_id]
        if item["name"] != expected["name"] or item["priority_stars"] != expected["priority_stars"]:
            raise IpProductizationContractError(f"{capability_id} name or priority differs from profile")
        if item["status"] not in {"PASS", "BLOCKED", "NOT_APPLICABLE"}:
            raise IpProductizationContractError(f"{capability_id} has unsupported status")
        if not isinstance(item["owner_approved"], bool):
            raise IpProductizationContractError(f"{capability_id} owner_approved must be boolean")
        reviewer = _non_placeholder(item["reviewer"], f"{capability_id}.reviewer")
        summary = _non_placeholder(
            item["acceptance_summary"], f"{capability_id}.acceptance_summary", minimum=8
        )
        if reviewer in {author, owner}:
            raise IpProductizationContractError(
                f"{capability_id} reviewer must be independent from author and owner"
            )
        evidence_ids = item["evidence_ids"]
        if not isinstance(evidence_ids, list) or any(
            not isinstance(value, str) or not HASH_RE.fullmatch(value) for value in evidence_ids
        ):
            raise IpProductizationContractError(f"{capability_id} evidence_ids must be content identities")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise IpProductizationContractError(f"{capability_id} evidence_ids contain duplicates")
        if item["status"] == "PASS":
            if not item["owner_approved"] or not evidence_ids:
                raise IpProductizationContractError(
                    f"{capability_id} PASS requires owner approval and evidence"
                )
        elif item["owner_approved"]:
            raise IpProductizationContractError(f"{capability_id} cannot be approved when status is not PASS")
        if item["status"] == "NOT_APPLICABLE":
            if capability_id != "C4" or ip["delivery_target"] != "FPGA":
                raise IpProductizationContractError("only C4 may be not applicable for FPGA delivery")
            if evidence_ids:
                raise IpProductizationContractError("not-applicable C4 must not claim evidence")
        if summary.strip() == "FPGA delivery candidate; ASIC gate not requested" and (
            capability_id != "C4" or item["status"] != "NOT_APPLICABLE"
        ):
            raise IpProductizationContractError("ASIC deferral summary is only valid for C4")
    if tuple(observed_ids) != CAPABILITY_IDS:
        raise IpProductizationContractError("capabilities must be unique and ordered C1-C6")

    security = _mapping(declaration["security"], "security")
    _exact_fields(security, SECURITY_FIELDS, "security")
    expected_security = {
        "raw_customer_spec_present": False,
        "raw_customer_rtl_present": False,
        "external_model_export": False,
        "repository_content": "HASHES_AND_SANITIZED_SUMMARIES_ONLY",
    }
    if security != expected_security:
        raise IpProductizationContractError("customer data or external model export is forbidden")


def build_contract(
    declaration: Mapping[str, Any],
    profile: Mapping[str, Any],
    profile_sha256: str,
) -> dict[str, Any]:
    validate_declaration(declaration, profile)
    capability_by_id = {item["id"]: item for item in declaration["capabilities"]}
    target = declaration["ip"]["delivery_target"]
    required = list(profile["release_gates"][target])
    passed = [item["id"] for item in declaration["capabilities"] if item["status"] == "PASS"]
    blocking = [capability_id for capability_id in required if capability_id not in passed]
    non_blocking = [capability_id for capability_id in CAPABILITY_IDS if capability_id not in required]
    ready = declaration["requested_state"] == "READY_FOR_OWNER_REVIEW" and not blocking
    if target == "ASIC" and capability_by_id["C4"]["status"] != "PASS":
        ready = False

    result = dict(declaration)
    result["profile_sha256"] = profile_sha256
    result["assessment"] = {
        "status": "READY_FOR_OWNER_REVIEW" if ready else "BLOCKED",
        "next_gate": (
            "REQUEST_INDEPENDENT_OWNER_RELEASE_REVIEW" if ready else "COMPLETE_REQUIRED_CAPABILITY_EVIDENCE"
        ),
        "required_capabilities": required,
        "passed_capabilities": passed,
        "blocking_capabilities": blocking,
        "non_blocking_capabilities": non_blocking,
        "priority_policy": "FIVE_STAR_PRODUCT_GATES_THREE_STAR_TRACKED_ONE_STAR_DEFERRED",
        "human_release_required": True,
    }
    result["contract_id"] = _content_id(result, "contract_id")
    validate_contract(result, profile, profile_sha256, rebuild=False)
    return result


def validate_contract(
    contract: Mapping[str, Any],
    profile: Mapping[str, Any],
    profile_sha256: str,
    *,
    rebuild: bool = True,
) -> None:
    _exact_fields(contract, OUTPUT_FIELDS, "IP productization contract")
    if not isinstance(contract["contract_id"], str) or not HASH_RE.fullmatch(contract["contract_id"]):
        raise IpProductizationContractError("contract_id must be a sha256 content identity")
    if contract["contract_id"] != _content_id(contract, "contract_id"):
        raise IpProductizationContractError("contract_id does not match canonical content")
    if contract["profile_sha256"] != profile_sha256:
        raise IpProductizationContractError("profile_sha256 does not match the selected profile")
    assessment = _mapping(contract["assessment"], "assessment")
    _exact_fields(assessment, ASSESSMENT_FIELDS, "assessment")
    if assessment["human_release_required"] is not True:
        raise IpProductizationContractError("human release review cannot be disabled")
    if rebuild:
        declaration = {field: contract[field] for field in TOP_FIELDS}
        expected = build_contract(declaration, profile, profile_sha256)
        if contract != expected:
            raise IpProductizationContractError("stored assessment differs from rebuilt assessment")


def _write_new(path: Path, value: Mapping[str, Any], root: Path) -> None:
    root = root.resolve(strict=True)
    output = path.resolve(strict=False)
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise IpProductizationContractError("output must remain inside the repository") from exc
    if output.exists():
        raise IpProductizationContractError(f"refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    build = subparsers.add_parser("build", help="build a sanitized product contract assessment")
    build.add_argument("declaration", type=Path)
    build.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    build.add_argument("--root", type=Path, default=Path("."))
    build.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify", help="rebuild and verify a stored contract")
    verify.add_argument("contract", type=Path)
    verify.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    args = parser.parse_args(argv)

    try:
        profile_path = args.profile.resolve(strict=True)
        profile = _load_json(profile_path)
        profile_sha256 = _file_id(profile_path)
        if args.action == "build":
            result = build_contract(_load_json(args.declaration), profile, profile_sha256)
            _write_new(args.output, result, args.root)
            print(
                json.dumps({"status": result["assessment"]["status"], "contract_id": result["contract_id"]})
            )
        else:
            contract = _load_json(args.contract)
            validate_contract(contract, profile, profile_sha256)
            print(
                json.dumps(
                    {"status": contract["assessment"]["status"], "contract_id": contract["contract_id"]}
                )
            )
    except (OSError, json.JSONDecodeError, IpProductizationContractError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
