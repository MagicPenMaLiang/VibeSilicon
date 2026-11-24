"""Validate the versioned RTL rule catalog and the currently active gate policy."""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "config/rtl_quality_rules.json"
POLICY = ROOT / "config/rtl_quality_policy.json"
PROFILES = {"fpga", "asic", "handwritten", "generated"}
FAMILIES = {
    "RTL-GEN", "RTL-NAM", "RTL-TYP", "RTL-CMB", "RTL-SEQ", "RTL-FSM",
    "RTL-RST", "RTL-CDC", "RTL-IFC", "RTL-CLK", "RTL-MEM", "RTL-XPR",
    "RTL-VER", "RTL-DBG", "RTL-MNT",
}
LEGACY_THRESHOLDS = {
    "lint_errors": 0,
    "async_reg_missing": 0,
    "bram_pct_csyn_warn": 60,
    "bram_pct_csyn_fail": 80,
    "wns_ns_warn": 0.5,
    "wns_ns_fail": 0.0,
    "cdc_critical": 0,
}
# Standard 1.1 (2026-11-14) added the G2 domain-approval requirement; both
# reviewed files were re-hashed because the version they declare moved with it.
# Revision record: docs/rtl_quality_revision_log.md
# Reviewed tool acceptance. The byte pin alone would still let a policy edit
# through after a hash update; these are the values the reviewer actually
# accepted, so they are stated in code as well. Same pattern as LEGACY_THRESHOLDS.
TOOL_VERSIONS = {
    "python": {"accepted_major": [3], "minimum_minor": 10},
    "verilator": {"accepted_major": [5]},
    "iverilog": {"accepted_major": [11, 12]},
}
REVIEWED_CATALOG_SHA256 = "9c7213df21a30f3485df82251f1f60e88cae1e67c7d4b973c2a39d183cfc90b1"
REVIEWED_POLICY_SHA256 = "301646222aa945d6e33a50aa874798a662ddb505c01d674fd666daa59f7abffc"
# The catalog says which rules exist; READABILITY decides what they accept.
# Pinning only the catalog would let the checker's semantics drift while every
# reviewed file stayed byte-identical -- a rule could be widened, or tightened,
# with every existing guard still green. This hash makes any edit to the
# checker, a comment included, require a reviewed update. Set it only from a
# tree whose change has been independently reviewed.
READABILITY = Path(__file__).with_name("rtl_readability.py")
REVIEWED_READABILITY_SHA256 = "e4825f9a73e1a6732bcd2d34b9813fd5ac0b95a1802a7958b7eea99cee9fc5ba"
SUPPLEMENTAL_AUTOMATED_RULES = {"RTL-GEN-001", "RTL-XPR-001", "RTL-MNT-001"}
# The accepted standard version. 1.1 adds the G2 domain-approval requirement;
# evidence produced under 1.0 cannot be read as evidence produced under 1.1.
STANDARD_VERSION = "1.1"
# Every check name a gate may require. A closed vocabulary is what makes
# gate_requirements load-bearing: a misspelt optional-looking string would
# otherwise silently switch a required human artifact off.
GATE_CHECKS = {
    "g0": {"catalog", "policy", "module_contract", "waiver_review"},
    "g1": {"rtl_readability", "verilator_lint", "async_reg"},
    "g2": {"project_elaboration", "protocol_regression", "cdc_review", "domain_approval"},
}
# Checks standard 1.1 cannot be met without. Dropping one of these is not a
# policy setting; it is a downgrade, and it has to change the constant above --
# a code edit -- rather than one line of a JSON file.
REQUIRED_GATE_CHECKS = {"g2": {"domain_approval"}}


class RtlQualityConfigError(ValueError):
    """The reviewed configuration is absent, malformed or internally inconsistent."""


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RtlQualityConfigError(f"cannot read RTL quality configuration: {path.name}") from exc
    if not isinstance(value, dict):
        raise RtlQualityConfigError(f"{path.name} must be a JSON object")
    return value


def _require_reviewed_bytes(path: Path, expected_sha256: str) -> None:
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise RtlQualityConfigError(f"cannot hash RTL quality configuration: {path.name}") from exc
    if actual != expected_sha256:
        raise RtlQualityConfigError(f"RTL quality configuration changed without reviewed version: {path.name}")


def load_catalog(path: Path = CATALOG) -> dict:
    _require_reviewed_bytes(path, REVIEWED_CATALOG_SHA256)
    _require_reviewed_bytes(READABILITY, REVIEWED_READABILITY_SHA256)
    data = _read(path)
    if set(data) != {"schema_version", "standard_version", "catalog_id", "profiles", "rules"}:
        raise RtlQualityConfigError("unexpected RTL catalog fields")
    if data["schema_version"] != 1 or data["standard_version"] != STANDARD_VERSION:
        raise RtlQualityConfigError("unsupported RTL catalog version")
    if data["catalog_id"] != "vibesilicon-rtl-coding-standard-v1":
        raise RtlQualityConfigError("unreviewed RTL catalog ID")
    if not isinstance(data["profiles"], list) or set(data["profiles"]) != PROFILES:
        raise RtlQualityConfigError("RTL catalog profiles must be complete and unique")
    if len(data["profiles"]) != len(PROFILES):
        raise RtlQualityConfigError("duplicate RTL catalog profile")
    rules = data["rules"]
    if not isinstance(rules, list) or len(rules) < 10:
        raise RtlQualityConfigError("RTL catalog must contain the legacy rules")
    found: dict[str, dict] = {}
    required_fields = {"id", "family", "level", "severity", "verification", "profiles", "evidence", "summary"}
    for item in rules:
        if not isinstance(item, dict) or set(item) != required_fields:
            raise RtlQualityConfigError("invalid RTL rule shape")
        rule_id = item["id"]
        if not isinstance(rule_id, str) or not re.fullmatch(r"RTL-(R\d{3}|[A-Z]{3,4}-\d{3})", rule_id):
            raise RtlQualityConfigError("invalid RTL rule ID")
        if rule_id in found:
            raise RtlQualityConfigError(f"duplicate RTL rule ID: {rule_id}")
        if item["family"] not in FAMILIES:
            raise RtlQualityConfigError(f"invalid RTL family: {rule_id}")
        if item["level"] not in {"MUST", "SHOULD"}:
            raise RtlQualityConfigError(f"invalid RTL level: {rule_id}")
        if item["severity"] not in {"ERROR", "WARNING"}:
            raise RtlQualityConfigError(f"invalid RTL severity: {rule_id}")
        if item["verification"] not in {"automated", "manual", "planned"}:
            raise RtlQualityConfigError(f"invalid RTL verification status: {rule_id}")
        if item["level"] == "MUST" and item["verification"] == "planned":
            raise RtlQualityConfigError(f"MUST rule lacks an automated or manual owner: {rule_id}")
        profiles = item["profiles"]
        if not isinstance(profiles, list) or not profiles or len(profiles) != len(set(profiles)) or not set(profiles) <= PROFILES:
            raise RtlQualityConfigError(f"invalid RTL profiles: {rule_id}")
        if not all(isinstance(item[field], str) and item[field].strip() for field in ("evidence", "summary")):
            raise RtlQualityConfigError(f"missing RTL evidence or summary: {rule_id}")
        found[rule_id] = item
    from scripts.quality_gate.rtl_readability import RULES

    for rule_id, (severity, _) in RULES.items():
        if rule_id not in found or found[rule_id]["severity"] != severity or found[rule_id]["verification"] != "automated":
            raise RtlQualityConfigError(f"legacy RTL rule drift: {rule_id}")
    if {rule_id for rule_id, rule in found.items() if rule["verification"] == "automated"} != set(RULES) | SUPPLEMENTAL_AUTOMATED_RULES:
        raise RtlQualityConfigError("new RTL rule marked automated without a checker")
    return data


def load_policy(path: Path = POLICY, *, catalog: dict | None = None) -> dict:
    _require_reviewed_bytes(path, REVIEWED_POLICY_SHA256)
    data = _read(path)
    required = {"schema_version", "policy_id", "standard_version", "activation", "legacy_gate_thresholds", "readability_thresholds", "profile_rules", "tool_versions", "gate_requirements"}
    if set(data) != required:
        raise RtlQualityConfigError("unexpected RTL policy fields")
    if (data["schema_version"], data["policy_id"], data["standard_version"]) != (1, "vibesilicon-rtl-quality-v1", STANDARD_VERSION):
        raise RtlQualityConfigError("unsupported or unreviewed RTL quality policy")
    if data["activation"] != "round1_legacy_gate_only":
        raise RtlQualityConfigError("RTL project gate activation requires a reviewed policy revision")
    if data["legacy_gate_thresholds"] != LEGACY_THRESHOLDS:
        raise RtlQualityConfigError("legacy gate thresholds changed without policy version review")
    read = data["readability_thresholds"]
    if not isinstance(read, dict) or set(read) != {"module_lines_warn", "process_lines_warn", "nesting_depth_warn"}:
        raise RtlQualityConfigError("invalid readability thresholds")
    if any(type(value) is not int or value < 1 for value in read.values()):
        raise RtlQualityConfigError("readability thresholds must be positive integers")
    catalog = catalog or load_catalog()
    ids = {rule["id"] for rule in catalog["rules"]}
    profile_rules = data["profile_rules"]
    if not isinstance(profile_rules, dict) or set(profile_rules) != PROFILES:
        raise RtlQualityConfigError("incomplete profile policy")
    for profile, rules in profile_rules.items():
        if not isinstance(rules, dict) or set(rules) != {"required"} or not isinstance(rules["required"], list):
            raise RtlQualityConfigError(f"invalid profile policy: {profile}")
        if len(rules["required"]) != len(set(rules["required"])):
            raise RtlQualityConfigError(f"duplicate profile rule: {profile}")
        if not set(rules["required"]) <= ids:
            raise RtlQualityConfigError(f"unknown profile rule: {profile}")
        by_id = {rule["id"]: rule for rule in catalog["rules"]}
        if any(profile not in by_id[rule_id]["profiles"] for rule_id in rules["required"]):
            raise RtlQualityConfigError(f"inapplicable profile rule: {profile}")
    tools = data["tool_versions"]
    if not isinstance(tools, dict) or set(tools) != {"python", "verilator", "iverilog"}:
        raise RtlQualityConfigError("incomplete tool version policy")
    for name, version in tools.items():
        if not isinstance(version, dict) or not set(version) <= {"accepted_major", "minimum_minor"} or "accepted_major" not in version:
            raise RtlQualityConfigError(f"invalid tool version policy: {name}")
        major = version["accepted_major"]
        if not isinstance(major, list) or not major or len(major) != len(set(major)) or any(type(number) is not int or number < 1 for number in major):
            raise RtlQualityConfigError(f"invalid tool major versions: {name}")
        if "minimum_minor" in version and (type(version["minimum_minor"]) is not int or version["minimum_minor"] < 0):
            raise RtlQualityConfigError(f"invalid tool minor version: {name}")
    if data["tool_versions"] != TOOL_VERSIONS:
        raise RtlQualityConfigError("tool version policy changed without policy version review")
    gates = data["gate_requirements"]
    if not isinstance(gates, dict) or set(gates) != {"g0", "g1", "g2"}:
        raise RtlQualityConfigError("incomplete gate policy")
    for name, checks in gates.items():
        if not isinstance(checks, list) or not checks or any(not isinstance(check, str) or not check for check in checks) or len(checks) != len(set(checks)):
            raise RtlQualityConfigError(f"invalid required checks: {name}")
        if not set(checks) <= GATE_CHECKS[name]:
            raise RtlQualityConfigError(f"unknown required check: {name}")
        if not REQUIRED_GATE_CHECKS.get(name, set()) <= set(checks):
            raise RtlQualityConfigError(f"required check missing: {name}")
    return data
