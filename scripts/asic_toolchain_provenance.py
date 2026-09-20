#!/usr/bin/env python3
"""Collect and verify repository-safe A04 toolchain provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
STATUS = "A04_TOOLCHAIN_PROVENANCE_READY"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
DIAGNOSTIC_VARIABLES = (
    "SKIP_REPAIR_TIE_FANOUT",
    "SKIP_INCREMENTAL_REPAIR",
    "SKIP_GATE_CLONING",
)
ROOT_FIELDS = {
    "schema_version",
    "provenance_id",
    "profile_id",
    "profile_sha256",
    "status",
    "source_build",
    "tools",
    "diagnostic_overrides",
    "compatibility_gate",
    "repository_content",
}


class AsicToolchainProvenanceError(ValueError):
    """Raised when toolchain or compatibility evidence is unsafe or stale."""


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
        raise AsicToolchainProvenanceError(f"cannot hash required file: {path.name}") from exc
    return "sha256:" + digest.hexdigest()


def _content_id(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "provenance_id"}
    return _sha256_value(payload)


def _fields(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise AsicToolchainProvenanceError(f"{label} fields are incomplete or unknown")
    return value


def _clean_text(value: str, label: str) -> str:
    cleaned = value.strip()
    if (
        not cleaned
        or len(cleaned) > 256
        or "\n" in cleaned
        or "\r" in cleaned
        or not all(character.isprintable() for character in cleaned)
    ):
        raise AsicToolchainProvenanceError(f"{label} is invalid")
    return cleaned


def _run(
    argv: Sequence[str],
    *,
    label: str,
    runner: Any = subprocess.run,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    try:
        completed = runner(
            list(argv),
            check=False,
            capture_output=True,
            text=True,
            input=input_text,
            env=dict(env) if env is not None else None,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AsicToolchainProvenanceError(f"cannot run {label}") from exc
    if completed.returncode != 0:
        raise AsicToolchainProvenanceError(f"{label} failed")
    output = (completed.stdout + "\n" + completed.stderr).strip()
    return _clean_text(output.splitlines()[0], f"{label} output")


def _revision(root: Path, label: str, runner: Any) -> str:
    revision = _run(
        ["git", "-C", str(root.resolve(strict=True)), "rev-parse", "HEAD"],
        label=f"{label} revision probe",
        runner=runner,
    )
    if not REVISION_RE.fullmatch(revision):
        raise AsicToolchainProvenanceError(f"{label} revision is not a full commit")
    return revision


def _tool(
    name: str,
    path: Path,
    version_args: Sequence[str],
    source_revision: str | None,
    *,
    runner: Any,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise AsicToolchainProvenanceError(f"{name} launcher is not a file")
    version = _run(
        [str(resolved), *version_args],
        label=f"{name} version probe",
        runner=runner,
        env=env,
    )
    return {
        "name": name,
        "version": version,
        "binary_sha256": _sha256_file(resolved),
        "source_revision": source_revision,
    }


def _diagnostic_overrides(vars_file: Path) -> list[str]:
    try:
        text = vars_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AsicToolchainProvenanceError("cannot read ORFS vars file") from exc
    overrides: list[str] = []
    for name in DIAGNOSTIC_VARIABLES:
        match = re.search(rf"^(?:export\s+)?{re.escape(name)}=[\"']?([^\"'\r\n]*)", text, re.M)
        if match and match.group(1).strip() not in {"", "0"}:
            overrides.append(f"{name}={match.group(1).strip()}")
    return overrides


def collect_provenance(
    profile: Mapping[str, Any],
    *,
    orfs_root: Path,
    openroad: Path,
    yosys: Path,
    strmrun: Path,
    strmrun_library_dirs: Sequence[Path],
    vars_file: Path,
    floorplan_odb: Path,
    floorplan_sdc: Path,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    reference = profile.get("reference")
    if not isinstance(reference, Mapping):
        raise AsicToolchainProvenanceError("profile reference is missing")
    revisions = reference.get("tool_source_revisions")
    if not isinstance(revisions, Mapping):
        raise AsicToolchainProvenanceError("profile tool revisions are missing")
    orfs_revision = _revision(orfs_root, "ORFS", runner)
    openroad_revision = _revision(orfs_root / "tools" / "OpenROAD", "OpenROAD", runner)
    yosys_revision = _revision(orfs_root / "tools" / "yosys", "Yosys", runner)
    if (
        orfs_revision != reference.get("orfs_revision")
        or openroad_revision != revisions.get("openroad")
        or yosys_revision != revisions.get("yosys")
    ):
        raise AsicToolchainProvenanceError("source revisions drift from the fixed profile")

    library_dirs = [str(path.resolve(strict=True)) for path in strmrun_library_dirs]
    strmrun_env = dict(os.environ)
    if library_dirs:
        existing = strmrun_env.get("LD_LIBRARY_PATH")
        strmrun_env["LD_LIBRARY_PATH"] = os.pathsep.join(
            [*library_dirs, *([existing] if existing else [])]
        )
    tools = [
        _tool("yosys", yosys, ["-V"], yosys_revision, runner=runner),
        _tool("openroad", openroad, ["-version"], openroad_revision, runner=runner),
        _tool("strmrun", strmrun, ["--version"], None, runner=runner, env=strmrun_env),
    ]
    probe = (
        'puts "repair_tie_fanout=[llength [info commands repair_tie_fanout]]"\n'
        'puts "replace_arith_modules=[llength [info commands replace_arith_modules]]"\n'
        "exit\n"
    )
    resolved_openroad = openroad.resolve(strict=True)
    try:
        completed = runner(
            [str(resolved_openroad), "-no_init", "-no_splash"],
            check=False,
            capture_output=True,
            text=True,
            input=probe,
            env=None,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AsicToolchainProvenanceError("cannot probe OpenROAD command surface") from exc
    command_output = completed.stdout + "\n" + completed.stderr
    command_requirements = {
        "repair_tie_fanout": "repair_tie_fanout=1" in command_output,
        "replace_arith_modules": "replace_arith_modules=1" in command_output,
    }
    if completed.returncode != 0 or not all(command_requirements.values()):
        raise AsicToolchainProvenanceError("OpenROAD command surface is incompatible")

    overrides = _diagnostic_overrides(vars_file)
    if overrides:
        raise AsicToolchainProvenanceError("ORFS compatibility gate used diagnostic overrides")
    for path, label in ((floorplan_odb, "floorplan ODB"), (floorplan_sdc, "floorplan SDC")):
        try:
            if not path.resolve(strict=True).is_file() or path.stat().st_size <= 0:
                raise AsicToolchainProvenanceError(f"{label} is empty")
        except OSError as exc:
            raise AsicToolchainProvenanceError(f"{label} is missing") from exc

    build_launcher = orfs_root / "build_openroad.sh"
    dependency_prefixes = orfs_root / "openroad_deps_prefixes.txt"
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "provenance_id": "",
        "profile_id": profile.get("profile_id"),
        "profile_sha256": _sha256_value(profile),
        "status": STATUS,
        "source_build": {
            "mode": "LOCAL_SOURCE_BUILD",
            "orfs_revision": orfs_revision,
            "openroad_revision": openroad_revision,
            "yosys_revision": yosys_revision,
            "build_launcher_sha256": _sha256_file(build_launcher),
            "dependency_prefixes_sha256": _sha256_file(dependency_prefixes),
            "kepler_formal": "NOT_REQUIRED_FOR_A04_RTL_TO_GDS",
        },
        "tools": tools,
        "diagnostic_overrides": [],
        "compatibility_gate": {
            "design_id": reference.get("design_id"),
            "target": "floorplan",
            "result_status": "PASS",
            "command_requirements": command_requirements,
            "vars_sha256": _sha256_file(vars_file.resolve(strict=True)),
            "floorplan_odb_sha256": _sha256_file(floorplan_odb.resolve(strict=True)),
            "floorplan_sdc_sha256": _sha256_file(floorplan_sdc.resolve(strict=True)),
        },
        "repository_content": "HASHES_AND_SANITIZED_EVIDENCE_ONLY",
    }
    result["provenance_id"] = _content_id(result)
    validate_provenance(result, profile)
    return result


def validate_provenance(value: Any, profile: Mapping[str, Any]) -> None:
    evidence = _fields(value, ROOT_FIELDS, "toolchain provenance")
    if evidence["schema_version"] != SCHEMA_VERSION or evidence["status"] != STATUS:
        raise AsicToolchainProvenanceError("toolchain provenance status or schema is invalid")
    if evidence["provenance_id"] != _content_id(evidence):
        raise AsicToolchainProvenanceError("toolchain provenance content ID mismatch")
    if evidence["profile_id"] != profile.get("profile_id"):
        raise AsicToolchainProvenanceError("toolchain provenance profile ID mismatch")
    if evidence["profile_sha256"] != _sha256_value(profile):
        raise AsicToolchainProvenanceError("toolchain provenance profile hash mismatch")
    reference = profile["reference"]
    source = _fields(
        evidence["source_build"],
        {
            "mode",
            "orfs_revision",
            "openroad_revision",
            "yosys_revision",
            "build_launcher_sha256",
            "dependency_prefixes_sha256",
            "kepler_formal",
        },
        "source build",
    )
    if (
        source["mode"] != "LOCAL_SOURCE_BUILD"
        or source["orfs_revision"] != reference["orfs_revision"]
        or source["openroad_revision"] != reference["tool_source_revisions"]["openroad"]
        or source["yosys_revision"] != reference["tool_source_revisions"]["yosys"]
        or source["kepler_formal"] != "NOT_REQUIRED_FOR_A04_RTL_TO_GDS"
    ):
        raise AsicToolchainProvenanceError("source build does not match the fixed profile")
    for field in ("build_launcher_sha256", "dependency_prefixes_sha256"):
        if not HASH_RE.fullmatch(str(source[field])):
            raise AsicToolchainProvenanceError("source build hash is invalid")
    tools = evidence["tools"]
    if not isinstance(tools, list) or [item.get("name") for item in tools] != [
        "yosys",
        "openroad",
        "strmrun",
    ]:
        raise AsicToolchainProvenanceError("tool identities are incomplete or out of order")
    expected_revisions = reference["tool_source_revisions"]
    for item in tools:
        item = _fields(
            item,
            {"name", "version", "binary_sha256", "source_revision"},
            "tool identity",
        )
        _clean_text(item["version"], "tool version")
        if not HASH_RE.fullmatch(str(item["binary_sha256"])):
            raise AsicToolchainProvenanceError("tool binary hash is invalid")
        expected = expected_revisions.get(item["name"])
        if item["source_revision"] != expected:
            raise AsicToolchainProvenanceError("tool source revision is invalid")
    if evidence["diagnostic_overrides"] != []:
        raise AsicToolchainProvenanceError("diagnostic overrides are forbidden")
    gate = _fields(
        evidence["compatibility_gate"],
        {
            "design_id",
            "target",
            "result_status",
            "command_requirements",
            "vars_sha256",
            "floorplan_odb_sha256",
            "floorplan_sdc_sha256",
        },
        "compatibility gate",
    )
    if (
        gate["design_id"] != reference["design_id"]
        or gate["target"] != "floorplan"
        or gate["result_status"] != "PASS"
        or gate["command_requirements"]
        != {"repair_tie_fanout": True, "replace_arith_modules": True}
    ):
        raise AsicToolchainProvenanceError("compatibility gate did not pass")
    for field in ("vars_sha256", "floorplan_odb_sha256", "floorplan_sdc_sha256"):
        if not HASH_RE.fullmatch(str(gate[field])):
            raise AsicToolchainProvenanceError("compatibility artifact hash is invalid")
    if evidence["repository_content"] != "HASHES_AND_SANITIZED_EVIDENCE_ONLY":
        raise AsicToolchainProvenanceError("repository content boundary is invalid")


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AsicToolchainProvenanceError(f"cannot load JSON: {path.name}") from exc


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("collect")
    collect.add_argument("--profile", type=Path, required=True)
    collect.add_argument("--orfs-root", type=Path, required=True)
    collect.add_argument("--openroad", type=Path, required=True)
    collect.add_argument("--yosys", type=Path, required=True)
    collect.add_argument("--strmrun", type=Path, required=True)
    collect.add_argument("--strmrun-library-dir", type=Path, action="append", default=[])
    collect.add_argument("--vars", type=Path, required=True)
    collect.add_argument("--floorplan-odb", type=Path, required=True)
    collect.add_argument("--floorplan-sdc", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("evidence", type=Path)
    verify.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        profile = _load(args.profile)
        if args.command == "collect":
            evidence = collect_provenance(
                profile,
                orfs_root=args.orfs_root,
                openroad=args.openroad,
                yosys=args.yosys,
                strmrun=args.strmrun,
                strmrun_library_dirs=args.strmrun_library_dir,
                vars_file=args.vars,
                floorplan_odb=args.floorplan_odb,
                floorplan_sdc=args.floorplan_sdc,
            )
            _write(args.output, evidence)
        else:
            validate_provenance(_load(args.evidence), profile)
    except AsicToolchainProvenanceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
