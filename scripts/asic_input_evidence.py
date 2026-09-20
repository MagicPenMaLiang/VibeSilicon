#!/usr/bin/env python3
"""Build and verify sanitized P4.6 A01 ASIC input evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

try:
    from scripts import asic_backend_contract as backend
except ImportError:  # pragma: no cover - standalone script execution
    import asic_backend_contract as backend


SCHEMA_VERSION = 1
STATUS = "A01_INPUTS_VERIFIED_UNEXECUTED"
CLOSURE_STATUS = "A01_ENGINEERING_COMPLETE"
NEXT_GATE = "A02_SYNTHESIS_STA_ADAPTER"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
TOP_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
SPDX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]{1,63}$")
REVIEWER_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._@ -]{1,126}[A-Za-z0-9._@-]$"
)
BLOCKED_WORDS = ("example", "fixture", "placeholder", "replace_me", "todo")
VIEW_ROLES = (
    "tech_lef",
    "cell_lef",
    "gds",
    "spice",
    "sdc",
    "synthesis_rules",
    "tracks",
    "klayout_tech",
    "rcx_rules",
    "physical_rules",
    "lvs_rules",
    "drc_rules",
)
MANIFEST_FIELDS = {"schema_version", "pdk", "design", "security"}
PDK_FIELDS = {
    "pdk_id",
    "source_origin",
    "source_revision",
    "storage_id",
    "license",
    "corner",
    "views",
}
LICENSE_FIELDS = {"spdx_id", "review_status", "reviewed_by", "reviewed_at", "path"}
CORNER_FIELDS = {
    "name",
    "process",
    "voltage_v",
    "temperature_c",
    "liberty_path",
    "rc_tech_path",
}
VIEW_FIELDS = {"role", "path"}
DESIGN_FIELDS = {
    "design_id",
    "top_module",
    "rtl_languages",
    "source_visibility",
    "sources",
    "constraints_path",
}
SECURITY_FIELDS = {
    "paths_are_relative",
    "copy_into_repository",
    "network_access",
    "model_context_export",
}
EVIDENCE_FIELDS = {
    "schema_version",
    "evidence_id",
    "policy_id",
    "backend_id",
    "backend_contract_id",
    "status",
    "pdk",
    "design",
    "security",
    "execution_authorized",
    "asic_metrics_mixed_with_fpga",
    "next_gate",
    "closure_status",
}


class AsicInputError(ValueError):
    """Raised when ASIC input metadata or artifacts are unsafe or incomplete."""


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


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AsicInputError(f"cannot load ASIC input JSON: {path}") from exc


def _fields(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise AsicInputError(f"{label} fields are invalid")
    return value


def _clean(value: Any, label: str, *, pattern: re.Pattern[str] = ID_RE) -> str:
    if not isinstance(value, str):
        raise AsicInputError(f"{label} is invalid")
    lowered = value.lower()
    if any(word in lowered for word in BLOCKED_WORDS):
        raise AsicInputError(f"{label} contains placeholder text")
    if not pattern.fullmatch(value):
        raise AsicInputError(f"{label} is invalid")
    return value


def _reviewer(value: Any, label: str) -> str:
    return _clean(value, label, pattern=REVIEWER_RE)


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AsicInputError(f"{label} must be an RFC3339 UTC timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AsicInputError(f"{label} must be an RFC3339 UTC timestamp") from exc
    return value


def _https_origin(value: Any) -> str:
    if not isinstance(value, str):
        raise AsicInputError("PDK source_origin must be HTTPS")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise AsicInputError("PDK source_origin must be credential-free HTTPS")
    if any(word in value.lower() for word in BLOCKED_WORDS):
        raise AsicInputError("PDK source_origin contains placeholder text")
    return value


def _is_reparse(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & 0x400)


def _root(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise AsicInputError(f"{label} must be an explicit absolute path")
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or _is_reparse(path):
        raise AsicInputError(f"{label} must be a regular directory, not a link")
    return resolved


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _require_disjoint(left: Path, right: Path, label: str) -> None:
    if _within(left, right) or _within(right, left):
        raise AsicInputError(f"{label} roots must be disjoint")


def _artifact(root: Path, raw: Any, label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        raise AsicInputError(f"{label} path must be non-empty and relative")
    relative = Path(raw)
    if ".." in relative.parts:
        raise AsicInputError(f"{label} path traversal is forbidden")
    candidate = root / relative
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() and _is_reparse(current):
            raise AsicInputError(f"{label} must not traverse links or reparse points")
    resolved = candidate.resolve(strict=True)
    if not _within(resolved, root) or not resolved.is_file() or _is_reparse(candidate):
        raise AsicInputError(f"{label} must resolve to a regular file under its root")
    digest = hashlib.sha256()
    size = 0
    try:
        with resolved.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
    except OSError as exc:
        raise AsicInputError(f"cannot hash {label}") from exc
    if size == 0:
        raise AsicInputError(f"{label} must not be empty")
    return resolved, {"sha256": "sha256:" + digest.hexdigest(), "bytes": size}


def _validate_manifest(value: Any, policy: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = _fields(value, MANIFEST_FIELDS, "ASIC input manifest")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise AsicInputError("ASIC input manifest schema_version is invalid")
    pdk = _fields(manifest["pdk"], PDK_FIELDS, "PDK")
    _clean(pdk["pdk_id"], "PDK pdk_id")
    _https_origin(pdk["source_origin"])
    _clean(pdk["source_revision"], "PDK source_revision", pattern=REVISION_RE)
    _clean(pdk["storage_id"], "PDK storage_id")
    license_value = _fields(pdk["license"], LICENSE_FIELDS, "PDK license")
    _clean(license_value["spdx_id"], "PDK SPDX ID", pattern=SPDX_RE)
    if license_value["review_status"] != "APPROVED":
        raise AsicInputError("PDK license must be reviewed and APPROVED")
    _reviewer(license_value["reviewed_by"], "PDK license reviewer")
    _timestamp(license_value["reviewed_at"], "PDK license reviewed_at")
    corner = _fields(pdk["corner"], CORNER_FIELDS, "PDK corner")
    _clean(corner["name"], "PDK corner name")
    _clean(corner["process"], "PDK corner process")
    if isinstance(corner["voltage_v"], bool) or not isinstance(
        corner["voltage_v"], (int, float)
    ):
        raise AsicInputError("PDK corner voltage_v must be numeric")
    if not 0.1 <= float(corner["voltage_v"]) <= 5.0:
        raise AsicInputError("PDK corner voltage_v is outside the reviewed range")
    if isinstance(corner["temperature_c"], bool) or not isinstance(
        corner["temperature_c"], (int, float)
    ):
        raise AsicInputError("PDK corner temperature_c must be numeric")
    if not -100.0 <= float(corner["temperature_c"]) <= 250.0:
        raise AsicInputError("PDK corner temperature_c is outside the reviewed range")
    if not isinstance(pdk["views"], list):
        raise AsicInputError("PDK views must be an array")
    roles = []
    for item in pdk["views"]:
        view = _fields(item, VIEW_FIELDS, "PDK view")
        if view["role"] not in VIEW_ROLES:
            raise AsicInputError("PDK view role is not allowlisted")
        roles.append(view["role"])
    if sorted(roles) != sorted(policy["pdk_contract"]["required_view_roles"]):
        raise AsicInputError("PDK views must contain each required role exactly once")
    design = _fields(manifest["design"], DESIGN_FIELDS, "ASIC design")
    _clean(design["design_id"], "ASIC design_id")
    _clean(design["top_module"], "ASIC top_module", pattern=TOP_RE)
    if (
        not isinstance(design["rtl_languages"], list)
        or not design["rtl_languages"]
        or len(set(design["rtl_languages"])) != len(design["rtl_languages"])
        or not set(design["rtl_languages"]).issubset({"verilog", "systemverilog"})
    ):
        raise AsicInputError("ASIC rtl_languages are invalid")
    if design["source_visibility"] not in {"PUBLIC", "LOCAL_PRIVATE"}:
        raise AsicInputError("ASIC source_visibility is invalid")
    if (
        not isinstance(design["sources"], list)
        or not design["sources"]
        or not all(isinstance(item, str) for item in design["sources"])
    ):
        raise AsicInputError("ASIC sources must be a non-empty array")
    if len(set(design["sources"])) != len(design["sources"]):
        raise AsicInputError("ASIC sources must not contain duplicates")
    security = _fields(manifest["security"], SECURITY_FIELDS, "ASIC input security")
    expected_security = {
        "paths_are_relative": True,
        "copy_into_repository": False,
        "network_access": False,
        "model_context_export": False,
    }
    if security != expected_security:
        raise AsicInputError("ASIC input security must match the reviewed boundary")
    return manifest


def build_evidence(
    manifest_value: Any,
    policy: Mapping[str, Any],
    contract: Mapping[str, Any],
    *,
    repository_root: Path,
    pdk_root: Path,
    design_root: Path,
) -> dict[str, Any]:
    backend.validate_policy(policy)
    backend.validate_contract(contract, policy)
    manifest = _validate_manifest(manifest_value, policy)
    repository_root = _root(repository_root, "repository")
    pdk_root = _root(pdk_root, "PDK")
    design_root = _root(design_root, "design")
    _require_disjoint(repository_root, pdk_root, "repository and PDK")
    _require_disjoint(repository_root, design_root, "repository and design")
    _require_disjoint(pdk_root, design_root, "PDK and design")

    pdk = manifest["pdk"]
    license_path, license_digest = _artifact(
        pdk_root, pdk["license"]["path"], "PDK license"
    )
    corner = pdk["corner"]
    liberty_path, liberty_digest = _artifact(
        pdk_root, corner["liberty_path"], "corner Liberty"
    )
    rc_path, rc_digest = _artifact(pdk_root, corner["rc_tech_path"], "corner RC tech")
    used_pdk_paths = {license_path, liberty_path, rc_path}
    views = []
    for item in pdk["views"]:
        path, digest = _artifact(pdk_root, item["path"], f"PDK {item['role']} view")
        if path in used_pdk_paths:
            raise AsicInputError("PDK artifacts must use distinct files")
        used_pdk_paths.add(path)
        views.append({"role": item["role"], **digest})
    views.sort(key=lambda item: item["role"])

    design = manifest["design"]
    source_records = []
    source_bytes = 0
    used_design_paths: set[Path] = set()
    for raw in design["sources"]:
        path, digest = _artifact(design_root, raw, "RTL source")
        if path.suffix.lower() not in {".v", ".sv"}:
            raise AsicInputError("RTL source extension must be .v or .sv")
        if path in used_design_paths:
            raise AsicInputError("RTL source files must be distinct")
        used_design_paths.add(path)
        source_records.append({"logical_name": Path(raw).as_posix(), **digest})
        source_bytes += digest["bytes"]
    source_records.sort(key=lambda item: item["logical_name"])
    constraints_path, constraints_digest = _artifact(
        design_root, design["constraints_path"], "ASIC constraints"
    )
    if constraints_path.suffix.lower() != ".sdc":
        raise AsicInputError("ASIC constraints extension must be .sdc")
    if constraints_path in used_design_paths:
        raise AsicInputError("ASIC constraints must not also be an RTL source")

    pdk_total_bytes = (
        license_digest["bytes"]
        + liberty_digest["bytes"]
        + rc_digest["bytes"]
        + sum(item["bytes"] for item in views)
    )
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "evidence_id": "",
        "policy_id": policy["policy_id"],
        "backend_id": policy["backend_id"],
        "backend_contract_id": contract["contract_id"],
        "status": STATUS,
        "pdk": {
            "pdk_id": pdk["pdk_id"],
            "source_origin": pdk["source_origin"],
            "source_revision": pdk["source_revision"],
            "license": {
                "spdx_id": pdk["license"]["spdx_id"],
                "review_status": "APPROVED",
                "reviewed_by": pdk["license"]["reviewed_by"],
                "reviewed_at": pdk["license"]["reviewed_at"],
                "sha256": license_digest["sha256"],
                "bytes": license_digest["bytes"],
            },
            "storage": {
                "mode": "EXTERNAL_ONLY",
                "storage_id": pdk["storage_id"],
                "copied_into_repository": False,
                "file_count": len(used_pdk_paths),
                "total_bytes": pdk_total_bytes,
            },
            "corner": {
                "name": corner["name"],
                "process": corner["process"],
                "voltage_v": float(corner["voltage_v"]),
                "temperature_c": float(corner["temperature_c"]),
                "liberty_sha256": liberty_digest["sha256"],
                "liberty_bytes": liberty_digest["bytes"],
                "rc_tech_sha256": rc_digest["sha256"],
                "rc_tech_bytes": rc_digest["bytes"],
            },
            "views": views,
        },
        "design": {
            "design_id": design["design_id"],
            "top_module": design["top_module"],
            "rtl_languages": sorted(design["rtl_languages"]),
            "source_visibility": design["source_visibility"],
            "source_manifest_sha256": "sha256:"
            + hashlib.sha256(_canonical_bytes(source_records)).hexdigest(),
            "source_count": len(source_records),
            "source_bytes": source_bytes,
            "constraints_sha256": constraints_digest["sha256"],
            "constraints_bytes": constraints_digest["bytes"],
        },
        "security": dict(manifest["security"]),
        "execution_authorized": False,
        "asic_metrics_mixed_with_fpga": False,
        "next_gate": NEXT_GATE,
        "closure_status": CLOSURE_STATUS,
    }
    result["evidence_id"] = _content_id(result, "evidence_id")
    validate_evidence(result, policy, contract)
    return result


def validate_evidence(
    value: Any, policy: Mapping[str, Any], contract: Mapping[str, Any]
) -> None:
    backend.validate_policy(policy)
    backend.validate_contract(contract, policy)
    evidence = _fields(value, EVIDENCE_FIELDS, "ASIC input evidence")
    if evidence["schema_version"] != SCHEMA_VERSION:
        raise AsicInputError("ASIC input evidence schema_version is invalid")
    if evidence["evidence_id"] != _content_id(evidence, "evidence_id"):
        raise AsicInputError("ASIC input evidence content ID mismatch")
    fixed = {
        "policy_id": policy["policy_id"],
        "backend_id": policy["backend_id"],
        "backend_contract_id": contract["contract_id"],
        "status": STATUS,
        "security": {
            "paths_are_relative": True,
            "copy_into_repository": False,
            "network_access": False,
            "model_context_export": False,
        },
        "execution_authorized": False,
        "asic_metrics_mixed_with_fpga": False,
        "next_gate": NEXT_GATE,
        "closure_status": CLOSURE_STATUS,
    }
    if any(evidence[field] != expected for field, expected in fixed.items()):
        raise AsicInputError("ASIC input evidence violates reviewed semantics")
    pdk = _fields(
        evidence["pdk"],
        {"pdk_id", "source_origin", "source_revision", "license", "storage", "corner", "views"},
        "ASIC evidence PDK",
    )
    _clean(pdk["pdk_id"], "ASIC evidence PDK ID")
    _https_origin(pdk["source_origin"])
    _clean(pdk["source_revision"], "ASIC evidence revision", pattern=REVISION_RE)
    license_value = _fields(
        pdk["license"],
        {
            "spdx_id",
            "review_status",
            "reviewed_by",
            "reviewed_at",
            "sha256",
            "bytes",
        },
        "ASIC evidence license",
    )
    _clean(license_value["spdx_id"], "ASIC evidence SPDX ID", pattern=SPDX_RE)
    _reviewer(license_value["reviewed_by"], "ASIC evidence reviewer")
    _timestamp(license_value["reviewed_at"], "ASIC evidence reviewed_at")
    if license_value["review_status"] != "APPROVED" or not HASH_RE.fullmatch(
        str(license_value["sha256"])
    ):
        raise AsicInputError("ASIC evidence license is incomplete")
    if (
        isinstance(license_value["bytes"], bool)
        or not isinstance(license_value["bytes"], int)
        or license_value["bytes"] <= 0
    ):
        raise AsicInputError("ASIC evidence license size is invalid")
    storage = _fields(
        pdk["storage"],
        {"mode", "storage_id", "copied_into_repository", "file_count", "total_bytes"},
        "ASIC evidence storage",
    )
    if (
        storage["mode"] != "EXTERNAL_ONLY"
        or storage["copied_into_repository"] is not False
        or isinstance(storage["file_count"], bool)
        or not isinstance(storage["file_count"], int)
        or storage["file_count"] != 3 + len(VIEW_ROLES)
        or isinstance(storage["total_bytes"], bool)
        or not isinstance(storage["total_bytes"], int)
        or storage["total_bytes"] <= 0
    ):
        raise AsicInputError("ASIC evidence storage is invalid")
    _clean(storage["storage_id"], "ASIC evidence storage_id")
    corner = _fields(
        pdk["corner"],
        {
            "name",
            "process",
            "voltage_v",
            "temperature_c",
            "liberty_sha256",
            "liberty_bytes",
            "rc_tech_sha256",
            "rc_tech_bytes",
        },
        "ASIC evidence corner",
    )
    _clean(corner["name"], "ASIC evidence corner name")
    _clean(corner["process"], "ASIC evidence corner process")
    if (
        isinstance(corner["voltage_v"], bool)
        or not isinstance(corner["voltage_v"], (int, float))
        or not 0.1 <= float(corner["voltage_v"]) <= 5.0
        or isinstance(corner["temperature_c"], bool)
        or not isinstance(corner["temperature_c"], (int, float))
        or not -100.0 <= float(corner["temperature_c"]) <= 250.0
    ):
        raise AsicInputError("ASIC evidence corner operating point is invalid")
    for field in ("liberty_sha256", "rc_tech_sha256"):
        if not HASH_RE.fullmatch(str(corner[field])):
            raise AsicInputError(f"ASIC evidence {field} is invalid")
    for field in ("liberty_bytes", "rc_tech_bytes"):
        if (
            isinstance(corner[field], bool)
            or not isinstance(corner[field], int)
            or corner[field] <= 0
        ):
            raise AsicInputError(f"ASIC evidence {field} is invalid")
    if not isinstance(pdk["views"], list) or len(pdk["views"]) != len(VIEW_ROLES):
        raise AsicInputError("ASIC evidence views are incomplete")
    roles = []
    for item in pdk["views"]:
        view = _fields(item, {"role", "sha256", "bytes"}, "ASIC evidence view")
        roles.append(view["role"])
        if not HASH_RE.fullmatch(str(view["sha256"])):
            raise AsicInputError("ASIC evidence view hash is invalid")
        if (
            isinstance(view["bytes"], bool)
            or not isinstance(view["bytes"], int)
            or view["bytes"] <= 0
        ):
            raise AsicInputError("ASIC evidence view size is invalid")
    if roles != sorted(VIEW_ROLES):
        raise AsicInputError("ASIC evidence views must be sorted and complete")
    expected_pdk_bytes = (
        license_value["bytes"]
        + corner["liberty_bytes"]
        + corner["rc_tech_bytes"]
        + sum(item["bytes"] for item in pdk["views"])
    )
    if storage["total_bytes"] != expected_pdk_bytes:
        raise AsicInputError("ASIC evidence PDK total_bytes mismatch")
    design = _fields(
        evidence["design"],
        {
            "design_id",
            "top_module",
            "rtl_languages",
            "source_visibility",
            "source_manifest_sha256",
            "source_count",
            "source_bytes",
            "constraints_sha256",
            "constraints_bytes",
        },
        "ASIC evidence design",
    )
    _clean(design["design_id"], "ASIC evidence design_id")
    _clean(design["top_module"], "ASIC evidence top_module", pattern=TOP_RE)
    if design["source_visibility"] not in {"PUBLIC", "LOCAL_PRIVATE"}:
        raise AsicInputError("ASIC evidence source_visibility is invalid")
    if (
        not isinstance(design["rtl_languages"], list)
        or not design["rtl_languages"]
        or not all(isinstance(item, str) for item in design["rtl_languages"])
        or design["rtl_languages"] != sorted(set(design["rtl_languages"]))
        or not set(design["rtl_languages"]).issubset({"verilog", "systemverilog"})
    ):
        raise AsicInputError("ASIC evidence rtl_languages are invalid")
    for field in ("source_manifest_sha256", "constraints_sha256"):
        if not HASH_RE.fullmatch(str(design[field])):
            raise AsicInputError(f"ASIC evidence {field} is invalid")
    for field in ("source_count", "source_bytes", "constraints_bytes"):
        if (
            isinstance(design[field], bool)
            or not isinstance(design[field], int)
            or design[field] <= 0
        ):
            raise AsicInputError(f"ASIC evidence {field} is invalid")


def _repo_path(root: Path, path: Path, *, must_exist: bool) -> Path:
    resolved_root = root.resolve(strict=True)
    candidate = path if path.is_absolute() else resolved_root / path
    candidate = candidate.resolve(strict=must_exist)
    if not _within(candidate, resolved_root):
        raise AsicInputError(f"path escapes repository root: {candidate}")
    return candidate


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise AsicInputError(f"refusing to overwrite ASIC input evidence: {path}") from exc


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("input", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=Path("config/asic_backend_policy.json"))
    parser.add_argument("--backend-contract", type=Path, required=True)
    parser.add_argument("--pdk-root", type=Path)
    parser.add_argument("--design-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        policy = _load(_repo_path(root, args.policy, must_exist=True))
        contract = _load(_repo_path(root, args.backend_contract, must_exist=True))
        if not isinstance(policy, dict) or not isinstance(contract, dict):
            raise AsicInputError("ASIC policy and backend contract must be objects")
        if args.command == "build":
            if args.output is None or args.pdk_root is None or args.design_root is None:
                raise AsicInputError("build requires --output, --pdk-root, and --design-root")
            manifest = _load(_repo_path(root, args.input, must_exist=True))
            result = build_evidence(
                manifest,
                policy,
                contract,
                repository_root=root,
                pdk_root=args.pdk_root,
                design_root=args.design_root,
            )
            _write_exclusive(_repo_path(root, args.output, must_exist=False), result)
        else:
            if args.output is not None or args.pdk_root is not None or args.design_root is not None:
                raise AsicInputError("verify accepts no output or external roots")
            result = _load(_repo_path(root, args.input, must_exist=True))
            validate_evidence(result, policy, contract)
    except (OSError, backend.AsicContractError, AsicInputError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps({"status": result["status"], "identity": result["evidence_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
