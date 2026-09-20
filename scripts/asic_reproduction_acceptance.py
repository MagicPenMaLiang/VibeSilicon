#!/usr/bin/env python3
"""Build and verify the fixed A04 open-source ASIC reproduction acceptance."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from scripts import asic_backend_contract as backend
    from scripts import asic_input_evidence as input_contract
    from scripts import asic_physical_artifact as physical
    from scripts import asic_synth_sta_adapter as synth_sta
    from scripts import asic_toolchain_provenance as toolchain_provenance
except ImportError:  # pragma: no cover - standalone execution
    import asic_backend_contract as backend
    import asic_input_evidence as input_contract
    import asic_physical_artifact as physical
    import asic_synth_sta_adapter as synth_sta
    import asic_toolchain_provenance as toolchain_provenance


SCHEMA_VERSION = 1
STATUS = "A04_REPRODUCTION_ASSESSED"
PROFILE_ID = "orfs-sky130hd-gcd-v1"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
PROFILE = {
    "schema_version": 1,
    "profile_id": PROFILE_ID,
    "backend_id": "openroad-orfs-local",
    "reference": {
        "pdk_id": "sky130hd",
        "pdk_source_origin": "https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts",
        "pdk_source_revision": "d26bf27e1467d4ac903655694ac31e2ec3f85260",
        "pdk_upstream_origin": "https://github.com/google/skywater-pdk",
        "pdk_spdx_id": "Apache-2.0",
        "design_id": "orfs-sky130hd-gcd",
        "design_source_origin": "https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts",
        "design_license_rule": "OWNER_REVIEWED_COMPONENT_LICENSE",
        "top_module": "gcd",
        "source_visibility": "PUBLIC",
        "revision_rule": "FULL_40_HEX_COMMIT",
        "orfs_revision": "d26bf27e1467d4ac903655694ac31e2ec3f85260",
        "tool_source_revisions": {
            "openroad": "c3e680b01b8bc61eb1dfaf144594b371cc222efc",
            "yosys": "a5af9d690a43744bf6b2cc3dea2717c16b54621c",
        },
    },
    "reproduction": {
        "required_independent_runs": 2,
        "max_area_delta_percent": 1.0,
        "max_wns_delta_ns": 0.05,
        "require_tns_zero": True,
        "require_drc_zero": True,
        "require_lvs_pass": True,
    },
    "required_safety_cases": [
        "gds_only",
        "missing_constraint",
        "missing_corner",
        "missing_lvs_report",
        "pdk_revision_drift",
        "private_design_input",
    ],
    "retention": {
        "raw_artifacts_mode": "EXTERNAL_ONLY",
        "minimum_retention_days": 30,
        "repository_content": "HASHES_AND_SANITIZED_EVIDENCE_ONLY",
        "public_artifact_export": False,
        "model_context_export": False,
    },
}
DESCRIPTOR_FILE_FIELDS = {
    "policy",
    "backend_contract",
    "capabilities",
    "input_manifest",
    "input_evidence",
    "a02_evidence",
    "a02_approval",
    "physical_config",
    "physical_approval",
    "physical_evidence",
    "lvs_receipt",
    "final_manifest",
}
DESCRIPTOR_ROOT_FIELDS = {
    "pdk_root",
    "design_root",
    "a02_run_directory",
    "physical_run_directory",
}
REVIEW_FIELDS = {
    "schema_version",
    "review_id",
    "status",
    "profile_id",
    "reviewed_by",
    "reviewed_at",
    "design",
    "pdk",
    "toolchain",
    "retention",
}
ACCEPTANCE_FIELDS = {
    "schema_version",
    "acceptance_id",
    "profile_id",
    "profile_sha256",
    "review_id",
    "toolchain_provenance_id",
    "assessed_at",
    "status",
    "result_status",
    "runs",
    "checks",
    "metric_comparison",
    "safety_negatives",
    "security",
    "asic_metrics_mixed_with_fpga",
    "real_execution_performed_by_assessor",
    "next_gate",
    "closure_status",
}


class AsicReproductionError(ValueError):
    """Raised when A04 provenance, reproduction, or safety evidence fails closed."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _content_id(value: Mapping[str, Any], field: str) -> str:
    payload = {key: item for key, item in value.items() if key != field}
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _fields(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise AsicReproductionError(f"{label} fields are incomplete or unknown")
    return value


def _load(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AsicReproductionError(f"cannot load {label} JSON") from exc


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AsicReproductionError(f"{label} must be RFC3339 UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AsicReproductionError(f"{label} must be RFC3339 UTC") from exc
    parsed = parsed.astimezone(timezone.utc)
    if parsed.microsecond:
        raise AsicReproductionError(f"{label} must use whole seconds")
    return parsed


def validate_profile(value: Any) -> None:
    if value != PROFILE:
        raise AsicReproductionError("A04 profile does not match the reviewed fixed profile")


def validate_review(value: Any, profile: Mapping[str, Any], *, now: datetime) -> None:
    validate_profile(profile)
    review = _fields(value, REVIEW_FIELDS, "A04 review")
    if review["schema_version"] != SCHEMA_VERSION:
        raise AsicReproductionError("A04 review schema_version is invalid")
    if review["review_id"] != _content_id(review, "review_id"):
        raise AsicReproductionError("A04 review content ID mismatch")
    if review["status"] != "APPROVED" or review["profile_id"] != PROFILE_ID:
        raise AsicReproductionError("A04 review is not an approval for the fixed profile")
    try:
        input_contract._reviewer(review["reviewed_by"], "A04 reviewer")
    except input_contract.AsicInputError as exc:
        raise AsicReproductionError(str(exc)) from exc
    reviewed_at = _parse_time(review["reviewed_at"], "A04 reviewed_at")
    if reviewed_at > now:
        raise AsicReproductionError("A04 review is dated in the future")
    design = _fields(
        review["design"],
        {
            "source_origin",
            "source_revision",
            "spdx_id",
            "license_review_status",
            "license_sha256",
            "license_bytes",
            "source_manifest_sha256",
            "constraints_sha256",
        },
        "A04 design review",
    )
    pdk = _fields(
        review["pdk"],
        {
            "source_origin",
            "source_revision",
            "spdx_id",
            "license_review_status",
            "license_sha256",
            "license_bytes",
        },
        "A04 PDK review",
    )
    reference = profile["reference"]
    if (
        design["source_origin"] != reference["design_source_origin"]
        or design["source_revision"] != reference["orfs_revision"]
        or pdk["source_origin"] != reference["pdk_source_origin"]
        or pdk["source_revision"] != reference["pdk_source_revision"]
        or pdk["spdx_id"] != reference["pdk_spdx_id"]
    ):
        raise AsicReproductionError("A04 reviewed source or license does not match profile")
    for item, label in ((design, "design"), (pdk, "PDK")):
        if not REVISION_RE.fullmatch(str(item["source_revision"])):
            raise AsicReproductionError(f"A04 {label} revision is not a full commit")
        if item["license_review_status"] != "APPROVED":
            raise AsicReproductionError(f"A04 {label} license is not approved")
        try:
            input_contract._clean(item["spdx_id"], f"A04 {label} SPDX ID", pattern=input_contract.SPDX_RE)
        except input_contract.AsicInputError as exc:
            raise AsicReproductionError(str(exc)) from exc
        if not HASH_RE.fullmatch(str(item["license_sha256"])):
            raise AsicReproductionError(f"A04 {label} license hash is invalid")
        if (
            isinstance(item["license_bytes"], bool)
            or not isinstance(item["license_bytes"], int)
            or item["license_bytes"] <= 0
        ):
            raise AsicReproductionError(f"A04 {label} license size is invalid")
    for field in ("source_manifest_sha256", "constraints_sha256"):
        if not HASH_RE.fullmatch(str(design[field])):
            raise AsicReproductionError(f"A04 design {field} is invalid")
    toolchain = _fields(
        review["toolchain"],
        {"build_provenance_id", "diagnostic_overrides", "tools"},
        "A04 toolchain review",
    )
    if not HASH_RE.fullmatch(str(toolchain["build_provenance_id"])):
        raise AsicReproductionError("A04 toolchain build provenance ID is invalid")
    if toolchain["diagnostic_overrides"] != []:
        raise AsicReproductionError("A04 reviewed toolchain cannot contain diagnostic overrides")
    if not isinstance(toolchain["tools"], list) or len(toolchain["tools"]) != 3:
        raise AsicReproductionError("A04 toolchain review must contain three tools")
    expected_names = ["yosys", "openroad", "strmrun"]
    if [item.get("name") for item in toolchain["tools"]] != expected_names:
        raise AsicReproductionError("A04 toolchain review order or names are invalid")
    source_revisions = reference["tool_source_revisions"]
    for item in toolchain["tools"]:
        item = _fields(
            item,
            {"name", "version", "binary_sha256", "source_revision"},
            "A04 reviewed tool",
        )
        version = item["version"]
        if (
            not isinstance(version, str)
            or not version
            or len(version) > 256
            or "\n" in version
            or "\r" in version
            or not all(character.isprintable() for character in version)
        ):
            raise AsicReproductionError(f'A04 {item["name"]} version is invalid')
        if not HASH_RE.fullmatch(str(item["binary_sha256"])):
            raise AsicReproductionError("A04 reviewed tool binary hash is invalid")
        expected_revision = source_revisions.get(item["name"])
        if expected_revision is None:
            if item["source_revision"] is not None:
                raise AsicReproductionError("A04 package tool source revision must be null")
        elif item["source_revision"] != expected_revision:
            raise AsicReproductionError("A04 reviewed tool source revision does not match profile")
    retention = _fields(
        review["retention"],
        {
            "raw_artifacts_mode",
            "retention_days",
            "repository_content",
            "public_artifact_export",
            "commercial_pdk_present",
            "customer_rtl_present",
            "model_context_export",
        },
        "A04 retention review",
    )
    expected = profile["retention"]
    if (
        retention["raw_artifacts_mode"] != expected["raw_artifacts_mode"]
        or retention["repository_content"] != expected["repository_content"]
        or retention["public_artifact_export"] is not expected["public_artifact_export"]
        or retention["model_context_export"] is not expected["model_context_export"]
        or retention["commercial_pdk_present"] is not False
        or retention["customer_rtl_present"] is not False
        or isinstance(retention["retention_days"], bool)
        or not isinstance(retention["retention_days"], int)
        or retention["retention_days"] < expected["minimum_retention_days"]
    ):
        raise AsicReproductionError("A04 retention and data-boundary review is insufficient")


def _profile_input(
    input_evidence: Mapping[str, Any], review: Mapping[str, Any], profile: Mapping[str, Any]
) -> None:
    reference = profile["reference"]
    pdk = input_evidence["pdk"]
    design = input_evidence["design"]
    if (
        pdk["pdk_id"] != reference["pdk_id"]
        or pdk["source_origin"] != reference["pdk_source_origin"]
        or pdk["source_revision"] != reference["pdk_source_revision"]
        or pdk["license"]["spdx_id"] != reference["pdk_spdx_id"]
        or design["design_id"] != reference["design_id"]
        or design["top_module"] != reference["top_module"]
        or design["source_visibility"] != reference["source_visibility"]
    ):
        raise AsicReproductionError("A04 input is not the fixed public design/PDK profile")
    reviewed_design = review["design"]
    reviewed_pdk = review["pdk"]
    if (
        pdk["source_revision"] != reviewed_pdk["source_revision"]
        or pdk["license"]["sha256"] != reviewed_pdk["license_sha256"]
        or pdk["license"]["bytes"] != reviewed_pdk["license_bytes"]
        or design["source_manifest_sha256"] != reviewed_design["source_manifest_sha256"]
        or design["constraints_sha256"] != reviewed_design["constraints_sha256"]
    ):
        raise AsicReproductionError("A04 input drifts from the approved source review")


def _profile_toolchain(
    capabilities: Mapping[str, Any], review: Mapping[str, Any]
) -> None:
    reviewed = {item["name"]: item for item in review["toolchain"]["tools"]}
    actual = {item["name"]: item for item in capabilities["tools"]}
    if set(actual) != set(reviewed):
        raise AsicReproductionError("A04 capability tools drift from the reviewed toolchain")
    for name, expected in reviewed.items():
        observed = actual[name]
        if (
            observed["status"] != "PASS"
            or observed["version"] != expected["version"]
            or observed["binary_sha256"] != expected["binary_sha256"]
        ):
            raise AsicReproductionError(
                f"A04 {name} capability does not match reviewed build provenance"
            )


def validate_chain(
    chain: Mapping[str, Any],
    profile: Mapping[str, Any],
    review: Mapping[str, Any],
    *,
    repository_root: Path,
    now: datetime,
) -> dict[str, Any]:
    expected = {
        "run_label",
        "policy",
        "contract",
        "capabilities",
        "input_manifest",
        "input_evidence",
        "a02_evidence",
        "a02_approval",
        "physical_config",
        "physical_approval",
        "physical_evidence",
        "lvs_receipt",
        "final_manifest",
        "pdk_root",
        "design_root",
        "a02_run_directory",
        "physical_run_directory",
    }
    chain = _fields(chain, expected, "A04 run chain")
    if chain["run_label"] not in {"baseline", "replay"}:
        raise AsicReproductionError("A04 run_label is invalid")
    policy = chain["policy"]
    contract = chain["contract"]
    capabilities = chain["capabilities"]
    input_evidence = chain["input_evidence"]
    a02_evidence = chain["a02_evidence"]
    physical_evidence = chain["physical_evidence"]
    lvs_receipt = chain["lvs_receipt"]
    backend.validate_policy(policy)
    backend.validate_contract(contract, policy)
    backend.validate_capabilities(capabilities, policy)
    _profile_toolchain(capabilities, review)
    input_contract.validate_evidence(input_evidence, policy, contract)
    synth_sta.validate_evidence(
        a02_evidence,
        policy,
        contract,
        capabilities,
        input_evidence,
        chain["a02_approval"],
    )
    _profile_input(input_evidence, review, profile)
    try:
        rebuilt_input = input_contract.build_evidence(
            chain["input_manifest"],
            policy,
            contract,
            repository_root=repository_root,
            pdk_root=chain["pdk_root"],
            design_root=chain["design_root"],
        )
        physical._verify_a02_artifacts(chain["a02_run_directory"], a02_evidence)
    except (input_contract.AsicInputError, physical.AsicPhysicalError) as exc:
        raise AsicReproductionError(str(exc)) from exc
    if rebuilt_input != input_evidence:
        raise AsicReproductionError("A04 external inputs drift from A01 evidence")
    try:
        rebuilt_final = physical.finalize_manifest(
            physical_evidence,
            lvs_receipt,
            policy,
            contract,
            capabilities,
            input_evidence,
            a02_evidence,
            chain["a02_approval"],
            chain["physical_approval"],
            chain["physical_config"],
            run_directory=chain["physical_run_directory"],
            now=now,
        )
    except physical.AsicPhysicalError as exc:
        raise AsicReproductionError(str(exc)) from exc
    if rebuilt_final != chain["final_manifest"]:
        raise AsicReproductionError("A04 final manifest does not rebuild from raw evidence")
    return {
        "run_label": chain["run_label"],
        "input_evidence_id": input_evidence["evidence_id"],
        "a02_evidence_id": a02_evidence["evidence_id"],
        "physical_evidence_id": physical_evidence["evidence_id"],
        "manifest_id": rebuilt_final["manifest_id"],
        "lvs_receipt_id": lvs_receipt["receipt_id"],
        "executed_at": physical_evidence["executed_at"],
        "lvs_checked_at": lvs_receipt["checked_at"],
        "physical_config_sha256": physical_evidence["physical_config_sha256"],
        "tools": [dict(item) for item in physical_evidence["tools"]],
        "result_status": rebuilt_final["result_status"],
        "metrics": dict(rebuilt_final["metrics"]),
    }


def _expect_rejected(case_id: str, validator: str, action: Any) -> dict[str, str]:
    try:
        action()
    except (AsicReproductionError, input_contract.AsicInputError, physical.AsicPhysicalError) as exc:
        return {
            "case_id": case_id,
            "expected": "REJECTED",
            "observed": "REJECTED",
            "validator": validator,
            "error_type": type(exc).__name__,
        }
    raise AsicReproductionError(f"A04 safety case did not reject: {case_id}")


def safety_negative_results(
    chain: Mapping[str, Any], profile: Mapping[str, Any], review: Mapping[str, Any]
) -> list[dict[str, str]]:
    input_evidence = chain["input_evidence"]
    final_manifest = chain["final_manifest"]

    def missing_corner() -> None:
        value = copy.deepcopy(input_evidence)
        del value["pdk"]["corner"]
        value["evidence_id"] = input_contract._content_id(value, "evidence_id")
        input_contract.validate_evidence(value, chain["policy"], chain["contract"])

    def missing_constraint() -> None:
        value = copy.deepcopy(input_evidence)
        value["design"]["constraints_bytes"] = 0
        value["evidence_id"] = input_contract._content_id(value, "evidence_id")
        input_contract.validate_evidence(value, chain["policy"], chain["contract"])

    def pdk_revision_drift() -> None:
        value = copy.deepcopy(input_evidence)
        replacement = "1" * 40 if value["pdk"]["source_revision"] != "1" * 40 else "2" * 40
        value["pdk"]["source_revision"] = replacement
        value["evidence_id"] = input_contract._content_id(value, "evidence_id")
        input_contract.validate_evidence(value, chain["policy"], chain["contract"])
        _profile_input(value, review, profile)

    def private_input() -> None:
        value = copy.deepcopy(input_evidence)
        value["design"]["source_visibility"] = "LOCAL_PRIVATE"
        value["evidence_id"] = input_contract._content_id(value, "evidence_id")
        input_contract.validate_evidence(value, chain["policy"], chain["contract"])
        _profile_input(value, review, profile)

    def invalid_final(*, gds_only: bool) -> None:
        value = copy.deepcopy(final_manifest)
        artifacts = value["artifacts"]
        value["artifacts"] = (
            [item for item in artifacts if item["role"] == "gds"]
            if gds_only
            else [item for item in artifacts if item["role"] != "lvs_report"]
        )
        value["manifest_id"] = physical._content_id(value, "manifest_id")
        physical.validate_final_manifest(
            value,
            chain["physical_evidence"],
            chain["lvs_receipt"],
            chain["policy"],
            input_evidence,
            chain["a02_evidence"],
        )

    actions = {
        "gds_only": ("A03 final manifest", lambda: invalid_final(gds_only=True)),
        "missing_constraint": ("A01 input evidence", missing_constraint),
        "missing_corner": ("A01 input evidence", missing_corner),
        "missing_lvs_report": ("A03 final manifest", lambda: invalid_final(gds_only=False)),
        "pdk_revision_drift": ("A04 fixed profile", pdk_revision_drift),
        "private_design_input": ("A04 fixed profile", private_input),
    }
    return [_expect_rejected(case_id, *actions[case_id]) for case_id in profile["required_safety_cases"]]


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AsicReproductionError(f"A04 {label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise AsicReproductionError(f"A04 {label} must be finite")
    return number


def build_acceptance(
    profile: Mapping[str, Any],
    baseline_chain: Mapping[str, Any],
    replay_chain: Mapping[str, Any],
    review: Mapping[str, Any],
    provenance: Mapping[str, Any],
    *,
    repository_root: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    validate_profile(profile)
    current = datetime.now(timezone.utc) if now is None else now
    if current.tzinfo is None:
        raise AsicReproductionError("A04 assessment time must be timezone-aware")
    current = current.astimezone(timezone.utc).replace(microsecond=0)
    validate_review(review, profile, now=current)
    try:
        toolchain_provenance.validate_provenance(provenance, profile)
    except toolchain_provenance.AsicToolchainProvenanceError as exc:
        raise AsicReproductionError(str(exc)) from exc
    if review["toolchain"]["build_provenance_id"] != provenance["provenance_id"]:
        raise AsicReproductionError("A04 review does not bind the verified toolchain provenance")
    if review["toolchain"]["tools"] != provenance["tools"]:
        raise AsicReproductionError(
            "A04 reviewed tools drift from verified toolchain build provenance"
        )
    baseline = validate_chain(baseline_chain, profile, review, repository_root=repository_root, now=current)
    replay = validate_chain(replay_chain, profile, review, repository_root=repository_root, now=current)
    if baseline["run_label"] != "baseline" or replay["run_label"] != "replay":
        raise AsicReproductionError("A04 baseline and replay labels are not ordered")
    if baseline["input_evidence_id"] != replay["input_evidence_id"]:
        raise AsicReproductionError("A04 runs do not use the same reviewed input evidence")
    if (
        baseline["physical_config_sha256"] != replay["physical_config_sha256"]
        or baseline["tools"] != replay["tools"]
    ):
        raise AsicReproductionError("A04 tool or physical configuration changed between runs")
    reviewed_at = _parse_time(review["reviewed_at"], "A04 reviewed_at")
    latest_check = max(
        _parse_time(baseline["lvs_checked_at"], "baseline LVS checked_at"),
        _parse_time(replay["lvs_checked_at"], "replay LVS checked_at"),
    )
    if reviewed_at < latest_check:
        raise AsicReproductionError("A04 review must occur after both LVS checks")
    run_reviewers = {
        baseline_chain["a02_approval"]["approved_by"],
        baseline_chain["physical_approval"]["approved_by"],
        baseline_chain["lvs_receipt"]["reviewed_by"],
        replay_chain["a02_approval"]["approved_by"],
        replay_chain["physical_approval"]["approved_by"],
        replay_chain["lvs_receipt"]["reviewed_by"],
    }
    if review["reviewed_by"] in run_reviewers:
        raise AsicReproductionError("A04 final reviewer must be independent of run reviewers")
    independent = (
        baseline["physical_evidence_id"] != replay["physical_evidence_id"]
        and baseline["manifest_id"] != replay["manifest_id"]
        and baseline_chain["physical_run_directory"].resolve()
        != replay_chain["physical_run_directory"].resolve()
        and baseline["executed_at"] != replay["executed_at"]
    )
    base_metrics = baseline["metrics"]
    replay_metrics = replay["metrics"]
    base_area = _number(base_metrics["standard_cell_area_um2"], "baseline area")
    replay_area = _number(replay_metrics["standard_cell_area_um2"], "replay area")
    area_delta = (
        0.0
        if max(base_area, replay_area) == 0
        else abs(base_area - replay_area) / max(base_area, replay_area) * 100.0
    )
    wns_delta = abs(
        _number(base_metrics["wns_ns"], "baseline WNS") - _number(replay_metrics["wns_ns"], "replay WNS")
    )
    limits = profile["reproduction"]
    metrics_reproduce = (
        area_delta <= limits["max_area_delta_percent"] and wns_delta <= limits["max_wns_delta_ns"]
    )
    two_pass = baseline["result_status"] == replay["result_status"] == "PASS"
    safety = safety_negative_results(baseline_chain, profile, review)
    checks = {
        "fixed_public_profile": "PASS",
        "source_chain_integrity": "PASS",
        "independent_runs": "PASS" if independent else "FAIL",
        "two_complete_smokes": "PASS" if two_pass else "FAIL",
        "metric_reproduction": "PASS" if metrics_reproduce else "FAIL",
        "safety_negatives": "PASS",
        "license_and_retention": "PASS",
    }
    passed = all(value == "PASS" for value in checks.values())
    runs = [baseline, replay]
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "acceptance_id": "",
        "profile_id": PROFILE_ID,
        "profile_sha256": _sha256(profile),
        "review_id": review["review_id"],
        "toolchain_provenance_id": provenance["provenance_id"],
        "assessed_at": current.isoformat().replace("+00:00", "Z"),
        "status": STATUS,
        "result_status": "PASS" if passed else "BLOCKED",
        "runs": runs,
        "checks": checks,
        "metric_comparison": {
            "area_delta_percent": area_delta,
            "max_area_delta_percent": limits["max_area_delta_percent"],
            "wns_delta_ns": wns_delta,
            "max_wns_delta_ns": limits["max_wns_delta_ns"],
        },
        "safety_negatives": safety,
        "security": {
            "raw_artifacts_mode": "EXTERNAL_ONLY",
            "repository_content": "HASHES_AND_SANITIZED_EVIDENCE_ONLY",
            "commercial_pdk_present": False,
            "customer_rtl_present": False,
            "public_artifact_export": False,
            "model_context_export": False,
        },
        "asic_metrics_mixed_with_fpga": False,
        "real_execution_performed_by_assessor": False,
        "next_gate": "P4_ASIC_REFERENCE_ACCEPTED" if passed else "A04_REMEDIATE_AND_RERUN",
        "closure_status": "A04_SCOPED_ACCEPTANCE_COMPLETE" if passed else "A04_ENGINEERING_COMPLETE",
    }
    result["acceptance_id"] = _content_id(result, "acceptance_id")
    validate_acceptance(result, profile, review, provenance)
    return result


def validate_acceptance(
    value: Any,
    profile: Mapping[str, Any],
    review: Mapping[str, Any],
    provenance: Mapping[str, Any],
) -> None:
    validate_profile(profile)
    result = _fields(value, ACCEPTANCE_FIELDS, "A04 acceptance")
    if result["schema_version"] != SCHEMA_VERSION:
        raise AsicReproductionError("A04 acceptance schema_version is invalid")
    if result["acceptance_id"] != _content_id(result, "acceptance_id"):
        raise AsicReproductionError("A04 acceptance content ID mismatch")
    try:
        toolchain_provenance.validate_provenance(provenance, profile)
    except toolchain_provenance.AsicToolchainProvenanceError as exc:
        raise AsicReproductionError(str(exc)) from exc
    fixed = {
        "profile_id": PROFILE_ID,
        "profile_sha256": _sha256(profile),
        "review_id": review["review_id"],
        "toolchain_provenance_id": provenance["provenance_id"],
        "status": STATUS,
        "security": {
            "raw_artifacts_mode": "EXTERNAL_ONLY",
            "repository_content": "HASHES_AND_SANITIZED_EVIDENCE_ONLY",
            "commercial_pdk_present": False,
            "customer_rtl_present": False,
            "public_artifact_export": False,
            "model_context_export": False,
        },
        "asic_metrics_mixed_with_fpga": False,
        "real_execution_performed_by_assessor": False,
    }
    if any(result[key] != item for key, item in fixed.items()):
        raise AsicReproductionError("A04 acceptance violates reviewed semantics")
    assessed_at = _parse_time(result["assessed_at"], "A04 assessed_at")
    validate_review(review, profile, now=assessed_at)
    if (
        review["toolchain"]["build_provenance_id"] != provenance["provenance_id"]
        or review["toolchain"]["tools"] != provenance["tools"]
    ):
        raise AsicReproductionError("A04 review drifts from verified toolchain provenance")
    checks = _fields(
        result["checks"],
        {
            "fixed_public_profile",
            "source_chain_integrity",
            "independent_runs",
            "two_complete_smokes",
            "metric_reproduction",
            "safety_negatives",
            "license_and_retention",
        },
        "A04 checks",
    )
    if not all(item in {"PASS", "FAIL"} for item in checks.values()):
        raise AsicReproductionError("A04 check status is invalid")
    passed = all(item == "PASS" for item in checks.values())
    expected = {
        "result_status": "PASS" if passed else "BLOCKED",
        "next_gate": "P4_ASIC_REFERENCE_ACCEPTED" if passed else "A04_REMEDIATE_AND_RERUN",
        "closure_status": "A04_SCOPED_ACCEPTANCE_COMPLETE" if passed else "A04_ENGINEERING_COMPLETE",
    }
    if any(result[key] != item for key, item in expected.items()):
        raise AsicReproductionError("A04 result status or next gate is inconsistent")
    if not isinstance(result["runs"], list) or len(result["runs"]) != 2:
        raise AsicReproductionError("A04 acceptance must contain exactly two runs")
    if [item.get("run_label") for item in result["runs"]] != ["baseline", "replay"]:
        raise AsicReproductionError("A04 run summaries are not ordered")
    run_fields = {
        "run_label",
        "input_evidence_id",
        "a02_evidence_id",
        "physical_evidence_id",
        "manifest_id",
        "lvs_receipt_id",
        "executed_at",
        "lvs_checked_at",
        "physical_config_sha256",
        "tools",
        "result_status",
        "metrics",
    }
    for index, run in enumerate(result["runs"]):
        run = _fields(run, run_fields, f"A04 run {index}")
        for field in (
            "input_evidence_id",
            "a02_evidence_id",
            "physical_evidence_id",
            "manifest_id",
            "lvs_receipt_id",
            "physical_config_sha256",
        ):
            if not HASH_RE.fullmatch(str(run[field])):
                raise AsicReproductionError(f"A04 run {field} is invalid")
        executed_at = _parse_time(run["executed_at"], "A04 run executed_at")
        lvs_checked_at = _parse_time(run["lvs_checked_at"], "A04 run LVS checked_at")
        if executed_at > lvs_checked_at or lvs_checked_at > assessed_at:
            raise AsicReproductionError("A04 run time ordering is invalid")
        if not isinstance(run["tools"], list) or len(run["tools"]) != 2:
            raise AsicReproductionError("A04 tool identity is incomplete")
        for tool, name in zip(run["tools"], ("openroad", "strmrun")):
            tool = _fields(
                tool,
                {"name", "version", "binary_sha256"},
                "A04 tool",
            )
            if (
                tool["name"] != name
                or not isinstance(tool["version"], str)
                or not tool["version"]
                or not HASH_RE.fullmatch(str(tool["binary_sha256"]))
            ):
                raise AsicReproductionError("A04 tool identity is invalid")
        if run["result_status"] not in {"PASS", "BLOCKED"}:
            raise AsicReproductionError("A04 run result status is invalid")
        metrics = _fields(run["metrics"], physical.RUN_METRIC_FIELDS, "A04 run metrics")
        area = _number(metrics["standard_cell_area_um2"], "run area")
        wns = _number(metrics["wns_ns"], "run WNS")
        tns = _number(metrics["tns_ns"], "run TNS")
        if area < 0 or tns > 0:
            raise AsicReproductionError("A04 run metrics are outside ASIC bounds")
        if (
            not isinstance(metrics["drc_count"], int)
            or isinstance(metrics["drc_count"], bool)
            or metrics["drc_count"] < 0
            or metrics["timing_met"] is not (wns >= 0 and tns == 0)
            or metrics["drc_clean"] is not (metrics["drc_count"] == 0)
        ):
            raise AsicReproductionError("A04 run metric flags are inconsistent")
    comparison = _fields(
        result["metric_comparison"],
        {
            "area_delta_percent",
            "max_area_delta_percent",
            "wns_delta_ns",
            "max_wns_delta_ns",
        },
        "A04 metric comparison",
    )
    for key, item in comparison.items():
        if _number(item, key) < 0:
            raise AsicReproductionError("A04 metric comparison cannot be negative")
    if (
        comparison["max_area_delta_percent"] != profile["reproduction"]["max_area_delta_percent"]
        or comparison["max_wns_delta_ns"] != profile["reproduction"]["max_wns_delta_ns"]
    ):
        raise AsicReproductionError("A04 metric limits drift from profile")
    baseline, replay = result["runs"]
    if (
        baseline["input_evidence_id"] != replay["input_evidence_id"]
        or baseline["physical_config_sha256"]
        != replay["physical_config_sha256"]
        or baseline["tools"] != replay["tools"]
    ):
        raise AsicReproductionError(
            "A04 stored runs do not share input, tool, and physical config"
        )
    base_area = _number(baseline["metrics"]["standard_cell_area_um2"], "baseline area")
    replay_area = _number(replay["metrics"]["standard_cell_area_um2"], "replay area")
    expected_area_delta = (
        0.0
        if max(base_area, replay_area) == 0
        else abs(base_area - replay_area) / max(base_area, replay_area) * 100.0
    )
    expected_wns_delta = abs(
        _number(baseline["metrics"]["wns_ns"], "baseline WNS")
        - _number(replay["metrics"]["wns_ns"], "replay WNS")
    )
    if (
        comparison["area_delta_percent"] != expected_area_delta
        or comparison["wns_delta_ns"] != expected_wns_delta
    ):
        raise AsicReproductionError("A04 metric comparison does not match run evidence")
    independent = (
        baseline["physical_evidence_id"] != replay["physical_evidence_id"]
        and baseline["manifest_id"] != replay["manifest_id"]
        and baseline["executed_at"] != replay["executed_at"]
    )
    two_pass = baseline["result_status"] == replay["result_status"] == "PASS"
    metrics_reproduce = (
        expected_area_delta <= comparison["max_area_delta_percent"]
        and expected_wns_delta <= comparison["max_wns_delta_ns"]
    )
    expected_checks = {
        "fixed_public_profile": "PASS",
        "source_chain_integrity": "PASS",
        "independent_runs": "PASS" if independent else "FAIL",
        "two_complete_smokes": "PASS" if two_pass else "FAIL",
        "metric_reproduction": "PASS" if metrics_reproduce else "FAIL",
        "safety_negatives": "PASS",
        "license_and_retention": "PASS",
    }
    if checks != expected_checks:
        raise AsicReproductionError("A04 checks do not match run evidence")
    safety = result["safety_negatives"]
    if (
        not isinstance(safety, list)
        or [item.get("case_id") for item in safety] != profile["required_safety_cases"]
    ):
        raise AsicReproductionError("A04 safety case set is incomplete or unordered")
    safety_fields = {"case_id", "expected", "observed", "validator", "error_type"}
    for item in safety:
        item = _fields(item, safety_fields, "A04 safety result")
        if (
            item["expected"] != "REJECTED"
            or item["observed"] != "REJECTED"
            or not isinstance(item["validator"], str)
            or not item["validator"]
            or not isinstance(item["error_type"], str)
            or not item["error_type"]
        ):
            raise AsicReproductionError("A04 safety negative was not rejected")


def _external_descriptor(path: Path, root: Path) -> Path:
    if not path.is_absolute():
        raise AsicReproductionError("A04 run descriptor must be an absolute external path")
    try:
        resolved = path.resolve(strict=True)
        repository = root.resolve(strict=True)
    except OSError as exc:
        raise AsicReproductionError("A04 run descriptor path is unavailable") from exc
    if input_contract._within(resolved, repository) or resolved.is_symlink():
        raise AsicReproductionError("A04 run descriptor must remain outside the repository")
    if not resolved.is_file():
        raise AsicReproductionError("A04 run descriptor must be a regular file")
    return resolved


def load_chain_descriptor(descriptor_path: Path, repository_root: Path) -> dict[str, Any]:
    descriptor_path = _external_descriptor(descriptor_path, repository_root)
    descriptor = _fields(
        _load(descriptor_path, "A04 run descriptor"),
        {"schema_version", "run_label", "repository_files", "external_roots"},
        "A04 run descriptor",
    )
    if descriptor["schema_version"] != SCHEMA_VERSION:
        raise AsicReproductionError("A04 run descriptor schema_version is invalid")
    files = _fields(descriptor["repository_files"], DESCRIPTOR_FILE_FIELDS, "A04 repository files")
    roots = _fields(descriptor["external_roots"], DESCRIPTOR_ROOT_FIELDS, "A04 external roots")
    chain: dict[str, Any] = {"run_label": descriptor["run_label"]}
    for key, value in files.items():
        if not isinstance(value, str) or not value or Path(value).is_absolute():
            raise AsicReproductionError("A04 repository evidence paths must be relative")
        try:
            path = input_contract._repo_path(repository_root, Path(value), must_exist=True)
        except input_contract.AsicInputError as exc:
            raise AsicReproductionError(str(exc)) from exc
        chain_key = "contract" if key == "backend_contract" else key
        chain[chain_key] = _load(path, f"A04 {key}")
    resolved_roots = []
    for key, value in roots.items():
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise AsicReproductionError("A04 external roots must be absolute")
        try:
            resolved = input_contract._root(Path(value), f"A04 {key}")
        except input_contract.AsicInputError as exc:
            raise AsicReproductionError(str(exc)) from exc
        chain[key] = resolved
        resolved_roots.append((resolved, key))
    try:
        synth_sta._disjoint_roots((repository_root, "repository"), *resolved_roots)
    except synth_sta.AsicSynthStaError as exc:
        raise AsicReproductionError(str(exc)) from exc
    return chain


def _repo_path(root: Path, path: Path, *, must_exist: bool) -> Path:
    try:
        return input_contract._repo_path(root, path, must_exist=must_exist)
    except input_contract.AsicInputError as exc:
        raise AsicReproductionError(str(exc)) from exc


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise AsicReproductionError(f"refusing to overwrite A04 output: {path}") from exc


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("input", type=Path, help="profile for build; acceptance for verify")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--profile", type=Path, default=Path("config/asic_reproduction_profile.json"))
    parser.add_argument("--baseline-descriptor", type=Path, required=True)
    parser.add_argument("--replay-descriptor", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--toolchain-provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        root = args.root.resolve(strict=True)
        profile_path = args.input if args.command == "build" else args.profile
        profile = _load(_repo_path(root, profile_path, must_exist=True), "A04 profile")
        review = _load(_repo_path(root, args.review, must_exist=True), "A04 review")
        provenance_path = args.toolchain_provenance
        if provenance_path.is_absolute():
            try:
                provenance_path = provenance_path.resolve(strict=True)
            except OSError as exc:
                raise AsicReproductionError("A04 toolchain provenance is unavailable") from exc
        else:
            provenance_path = _repo_path(root, provenance_path, must_exist=True)
        provenance = _load(provenance_path, "A04 toolchain provenance")
        baseline = load_chain_descriptor(args.baseline_descriptor, root)
        replay = load_chain_descriptor(args.replay_descriptor, root)
        rebuilt = build_acceptance(
            profile,
            baseline,
            replay,
            review,
            provenance,
            repository_root=root,
        )
        if args.command == "build":
            if args.output is None:
                raise AsicReproductionError("A04 build requires --output")
            _write_exclusive(_repo_path(root, args.output, must_exist=False), rebuilt)
        else:
            if args.output is not None:
                raise AsicReproductionError("A04 verify does not accept --output")
            stored = _load(_repo_path(root, args.input, must_exist=True), "A04 acceptance")
            if stored != rebuilt:
                raise AsicReproductionError("A04 stored acceptance does not rebuild")
        print(json.dumps({"status": rebuilt["result_status"], "identity": rebuilt["acceptance_id"]}))
        return 0
    except (
        AsicReproductionError,
        backend.AsicContractError,
        input_contract.AsicInputError,
        synth_sta.AsicSynthStaError,
        physical.AsicPhysicalError,
    ) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
