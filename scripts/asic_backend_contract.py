#!/usr/bin/env python3
"""Build and probe the non-executing P4.6 A01 ASIC backend contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


SCHEMA_VERSION = 1
POLICY_ID = "vibesilicon-asic-backend-v1"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ALLOWED_ACTIONS = [
    "discover_capabilities",
    "validate_inputs",
    "synthesize",
    "sta",
    "floorplan",
    "place",
    "cts",
    "route",
    "drc",
    "lvs",
    "report",
    "export_gds",
]
REQUIRED_TOOLS = [
    {"name": "yosys", "version_args": ["-V"], "stages": ["synthesize"]},
    {
        "name": "openroad",
        "version_args": ["-version"],
        "stages": ["sta", "floorplan", "place", "cts", "route", "report"],
    },
    {
        "name": "strmrun",
        "version_args": ["--version"],
        "stages": ["export_gds", "drc", "lvs"],
    },
]
PDK_CONTRACT = {
    "storage": "EXTERNAL_ONLY",
    "copied_into_repository": False,
    "license_review_required": True,
    "required_corner_fields": [
        "name",
        "process",
        "voltage_v",
        "temperature_c",
        "liberty_sha256",
        "rc_tech_sha256",
    ],
    "required_view_roles": [
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
    ],
}
SECURITY = {
    "arbitrary_shell": False,
    "arbitrary_tcl": False,
    "network_access": False,
    "gui": False,
    "telemetry": False,
    "remote_execution": False,
    "source_deletion": False,
    "production_writeback": False,
}
POLICY_FIELDS = {
    "schema_version",
    "policy_id",
    "backend_id",
    "execution_mode",
    "allowlisted_actions",
    "required_tools",
    "pdk_contract",
    "security",
}
CONTRACT_FIELDS = {
    "schema_version",
    "contract_id",
    "policy_id",
    "backend_id",
    "status",
    "execution_mode",
    "allowlisted_actions",
    "required_tools",
    "pdk_contract",
    "security",
    "execution_authorized",
    "pdk_configured",
    "design_configured",
    "asic_metrics_mixed_with_fpga",
    "next_gate",
    "closure_status",
}
CAPABILITY_FIELDS = {
    "schema_version",
    "capability_id",
    "policy_id",
    "backend_id",
    "status",
    "platform",
    "tools",
    "execution_authorized",
    "pdk_configured",
    "next_gate",
    "closure_status",
}
TOOL_FIELDS = {
    "name",
    "status",
    "version",
    "binary_sha256",
    "version_args",
    "stages",
}


class AsicContractError(ValueError):
    """Raised when the A01 ASIC contract is malformed, unsafe, or stale."""


Runner = Callable[..., subprocess.CompletedProcess[str]]
Resolver = Callable[[str], str | None]


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _inside(root: Path, path: Path, *, must_exist: bool) -> Path:
    resolved_root = root.resolve(strict=True)
    candidate = path if path.is_absolute() else resolved_root / path
    candidate = candidate.resolve(strict=must_exist)
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise AsicContractError(f"path escapes repository root: {candidate}") from exc
    return candidate


def validate_policy(value: Mapping[str, Any]) -> None:
    if set(value) != POLICY_FIELDS or value["schema_version"] != SCHEMA_VERSION:
        raise AsicContractError("ASIC backend policy fields or schema_version are invalid")
    reviewed = {
        "policy_id": POLICY_ID,
        "backend_id": "openroad-orfs-local",
        "execution_mode": "LOCAL_ALLOWLIST_ONLY",
        "allowlisted_actions": ALLOWED_ACTIONS,
        "required_tools": REQUIRED_TOOLS,
        "pdk_contract": PDK_CONTRACT,
        "security": SECURITY,
    }
    for field, expected in reviewed.items():
        if value[field] != expected:
            raise AsicContractError(f"ASIC backend {field} does not match reviewed policy")


def build_contract(policy: Mapping[str, Any]) -> dict[str, Any]:
    validate_policy(policy)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "contract_id": "",
        "policy_id": policy["policy_id"],
        "backend_id": policy["backend_id"],
        "status": "A01_PART_A_CONTRACT_READY",
        "execution_mode": policy["execution_mode"],
        "allowlisted_actions": list(policy["allowlisted_actions"]),
        "required_tools": [dict(item) for item in policy["required_tools"]],
        "pdk_contract": dict(policy["pdk_contract"]),
        "security": dict(policy["security"]),
        "execution_authorized": False,
        "pdk_configured": False,
        "design_configured": False,
        "asic_metrics_mixed_with_fpga": False,
        "next_gate": "A01_PART_B_PDK_INPUT_EVIDENCE",
        "closure_status": "BLOCKED",
    }
    result["contract_id"] = _content_id(result, "contract_id")
    validate_contract(result, policy)
    return result


def validate_contract(value: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    validate_policy(policy)
    if set(value) != CONTRACT_FIELDS or value["schema_version"] != SCHEMA_VERSION:
        raise AsicContractError("ASIC backend contract fields or schema_version are invalid")
    if value["contract_id"] != _content_id(value, "contract_id"):
        raise AsicContractError("ASIC backend contract content ID mismatch")
    fixed = {
        "policy_id": policy["policy_id"],
        "backend_id": policy["backend_id"],
        "status": "A01_PART_A_CONTRACT_READY",
        "execution_mode": policy["execution_mode"],
        "allowlisted_actions": policy["allowlisted_actions"],
        "required_tools": policy["required_tools"],
        "pdk_contract": policy["pdk_contract"],
        "security": policy["security"],
        "execution_authorized": False,
        "pdk_configured": False,
        "design_configured": False,
        "asic_metrics_mixed_with_fpga": False,
        "next_gate": "A01_PART_B_PDK_INPUT_EVIDENCE",
        "closure_status": "BLOCKED",
    }
    if any(value[field] != item for field, item in fixed.items()):
        raise AsicContractError("ASIC backend contract does not match reviewed semantics")


def _safe_version(output: str) -> str:
    line = next((item.strip() for item in output.splitlines() if item.strip()), "")
    line = "".join(character for character in line if character.isprintable())[:256]
    if not line:
        raise AsicContractError("ASIC tool returned no printable version")
    return line


def discover_capabilities(
    policy: Mapping[str, Any],
    *,
    runner: Runner = subprocess.run,
    resolver: Resolver = shutil.which,
) -> dict[str, Any]:
    validate_policy(policy)
    tools: list[dict[str, Any]] = []
    for item in policy["required_tools"]:
        executable = resolver(item["name"])
        status = "MISSING"
        version = None
        binary_sha256 = None
        if executable:
            path = Path(executable)
            try:
                if not path.is_file() or path.is_symlink():
                    raise OSError("tool launcher is not a regular file")
                binary_sha256 = _sha256_file(path)
                completed = runner(
                    [str(path), *item["version_args"]],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    shell=False,
                )
                if completed.returncode == 0:
                    version = _safe_version((completed.stdout or "") + (completed.stderr or ""))
                    status = "PASS"
                else:
                    status = "ERROR"
                    binary_sha256 = None
            except (OSError, subprocess.TimeoutExpired, AsicContractError):
                status = "ERROR"
                version = None
                binary_sha256 = None
        tools.append(
            {
                "name": item["name"],
                "status": status,
                "version": version,
                "binary_sha256": binary_sha256,
                "version_args": list(item["version_args"]),
                "stages": list(item["stages"]),
            }
        )
    ready = all(item["status"] == "PASS" for item in tools)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "capability_id": "",
        "policy_id": policy["policy_id"],
        "backend_id": policy["backend_id"],
        "status": "CAPABILITIES_PRESENT_UNQUALIFIED" if ready else "BLOCKED",
        "platform": {
            "os": platform.system().lower(),
            "architecture": platform.machine().lower(),
        },
        "tools": tools,
        "execution_authorized": False,
        "pdk_configured": False,
        "next_gate": "A01_PART_B_PDK_INPUT_EVIDENCE",
        "closure_status": "BLOCKED",
    }
    result["capability_id"] = _content_id(result, "capability_id")
    validate_capabilities(result, policy)
    return result


def validate_capabilities(value: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    validate_policy(policy)
    if set(value) != CAPABILITY_FIELDS or value["schema_version"] != SCHEMA_VERSION:
        raise AsicContractError("ASIC capability fields or schema_version are invalid")
    if value["capability_id"] != _content_id(value, "capability_id"):
        raise AsicContractError("ASIC capability content ID mismatch")
    if value["policy_id"] != policy["policy_id"] or value["backend_id"] != policy["backend_id"]:
        raise AsicContractError("ASIC capability policy binding is invalid")
    platform_value = value["platform"]
    if not isinstance(platform_value, Mapping) or set(platform_value) != {"os", "architecture"}:
        raise AsicContractError("ASIC capability platform fields are invalid")
    if any(not isinstance(item, str) or not item for item in platform_value.values()):
        raise AsicContractError("ASIC capability platform values are invalid")
    tools = value["tools"]
    if not isinstance(tools, list) or len(tools) != len(policy["required_tools"]):
        raise AsicContractError("ASIC capability must report every required tool")
    for actual, required in zip(tools, policy["required_tools"]):
        if not isinstance(actual, Mapping) or set(actual) != TOOL_FIELDS:
            raise AsicContractError("ASIC capability tool fields are invalid")
        if (
            actual["name"] != required["name"]
            or actual["version_args"] != required["version_args"]
            or actual["stages"] != required["stages"]
        ):
            raise AsicContractError("ASIC capability tool does not match reviewed policy")
        if actual["status"] == "PASS":
            if not isinstance(actual["version"], str) or not actual["version"]:
                raise AsicContractError("PASS ASIC capability requires a version")
            if not isinstance(actual["binary_sha256"], str) or not HASH_RE.fullmatch(
                actual["binary_sha256"]
            ):
                raise AsicContractError("PASS ASIC capability requires a binary hash")
        elif actual["status"] in {"MISSING", "ERROR"}:
            if actual["version"] is not None or actual["binary_sha256"] is not None:
                raise AsicContractError("unavailable ASIC tool cannot claim version or binary hash")
        else:
            raise AsicContractError("ASIC capability tool status is invalid")
    ready = all(item["status"] == "PASS" for item in tools)
    expected_status = "CAPABILITIES_PRESENT_UNQUALIFIED" if ready else "BLOCKED"
    if value["status"] != expected_status:
        raise AsicContractError("ASIC capability aggregate status is inconsistent")
    if (
        value["execution_authorized"] is not False
        or value["pdk_configured"] is not False
        or value["next_gate"] != "A01_PART_B_PDK_INPUT_EVIDENCE"
        or value["closure_status"] != "BLOCKED"
    ):
        raise AsicContractError("ASIC capability cannot grant execution or closure")


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AsicContractError(f"cannot load ASIC contract JSON: {path}") from exc


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise AsicContractError(f"refusing to overwrite ASIC output: {path}") from exc


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "discover", "verify"))
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=Path("config/asic_backend_policy.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        policy = _load(_inside(root, args.policy, must_exist=True))
        if not isinstance(policy, dict):
            raise AsicContractError("ASIC policy root must be an object")
        if args.command in {"build", "discover"}:
            if args.input is not None or args.output is None:
                raise AsicContractError(f"{args.command} requires --output and no input")
            result = build_contract(policy) if args.command == "build" else discover_capabilities(policy)
            _write_exclusive(_inside(root, args.output, must_exist=False), result)
        else:
            if args.input is None or args.output is not None:
                raise AsicContractError("verify requires one input and no --output")
            result = _load(_inside(root, args.input, must_exist=True))
            if not isinstance(result, dict):
                raise AsicContractError("ASIC evidence root must be an object")
            if "contract_id" in result:
                validate_contract(result, policy)
            elif "capability_id" in result:
                validate_capabilities(result, policy)
            else:
                raise AsicContractError("ASIC evidence type is unknown")
    except (OSError, AsicContractError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}), file=sys.stderr)
        return 2
    identity = result.get("contract_id", result.get("capability_id"))
    print(json.dumps({"status": result["status"], "identity": identity}))
    return 0 if result["status"] != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
