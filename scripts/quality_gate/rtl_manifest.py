#!/usr/bin/env python3
"""Validate a complete, repository-bounded RTL compilation manifest (G0)."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path


RTL_EXTENSIONS = {".v", ".sv"}
HEADER_EXTENSIONS = {".vh", ".svh"}
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
DEFINITION = re.compile(r"[A-Za-z0-9_+'-]+\Z")
FIELDS = {
    "schema_version", "project_root", "target", "source_kinds", "top",
    "source_roots", "sources", "headers", "include_dirs", "defines",
    "parameters", "clocks", "resets",
}
V2_FIELDS = FIELDS | {"excluded_sources"}
EXCLUSION_REASONS = {"testbench", "archive", "mutually_exclusive_variant"}


class ManifestError(ValueError):
    """The manifest cannot safely describe a complete RTL compilation."""


def _is_link(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _bounded_path(root: Path, value: str, *, kind: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ManifestError(f"invalid {kind} path: {value!r}")
    relative = Path(value)
    if relative.is_absolute() or any(part in {".", "..", ""} for part in value.split("/")):
        raise ManifestError(f"{kind} path must be repository-relative without traversal: {value}")
    candidate = root / relative
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        try:
            metadata = cursor.lstat()
        except OSError as exc:
            raise ManifestError(f"missing {kind}: {value}") from exc
        if _is_link(metadata):
            raise ManifestError(f"linked {kind} is not allowed: {value}")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ManifestError(f"{kind} escapes repository: {value}")
    return candidate


def _paths(root: Path, values: object, *, kind: str, extensions: set[str] | None = None) -> dict[str, Path]:
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ManifestError(f"{kind} must be an array of paths")
    if len(values) != len(set(values)):
        raise ManifestError(f"duplicate {kind} path")
    result = {}
    for item in values:
        path = _bounded_path(root, item, kind=kind)
        if extensions is None and not path.is_dir():
            raise ManifestError(f"{kind} is not a directory: {item}")
        if extensions is not None and (not path.is_file() or path.suffix.lower() not in extensions):
            raise ManifestError(f"{kind} is not an expected RTL file: {item}")
        result[item] = path
    return result


def _within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _scan(root: Path, source_roots: dict[str, Path]) -> tuple[set[str], set[str]]:
    sources: set[str] = set()
    headers: set[str] = set()
    def fail_scan(error: OSError) -> None:
        raise ManifestError(f"cannot scan source tree: {error.filename}") from error

    for directory in source_roots.values():
        for current, dirs, files in os.walk(directory, followlinks=False, onerror=fail_scan):
            for name in dirs + files:
                child = Path(current) / name
                relative = child.relative_to(root).as_posix()
                metadata = child.lstat()
                if _is_link(metadata):
                    raise ManifestError(f"linked source tree entry is not allowed: {relative}")
            for name in files:
                path = Path(current) / name
                relative = path.relative_to(root).as_posix()
                if path.suffix.lower() in RTL_EXTENSIONS:
                    sources.add(relative)
                elif path.suffix.lower() in HEADER_EXTENSIONS:
                    headers.add(relative)
    return sources, headers


def validate_manifest(path: Path, *, repository_root: Path) -> dict:
    """Return validated manifest data; reject missing, extra or linked RTL inputs."""
    # Keep the caller's spelling for the containment check. On Windows,
    # resolve() may expand an 8.3 account directory in the root while the
    # manifest argument still uses its short spelling. After deriving the
    # relative path, _bounded_path checks each component under the canonical
    # root and still rejects linked or escaping inputs.
    input_root = repository_root.absolute()
    root = repository_root.resolve(strict=True)
    try:
        absolute_manifest = path if path.is_absolute() else input_root / path
        relative_manifest = absolute_manifest.absolute().relative_to(input_root).as_posix()
    except ValueError as exc:
        raise ManifestError("manifest must be inside repository") from exc
    manifest_path = _bounded_path(root, relative_manifest, kind="manifest")
    if not manifest_path.is_file():
        raise ManifestError("manifest is not a file")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("cannot read manifest JSON") from exc
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or (
        data["schema_version"] == 1 and set(data) != FIELDS
    ) or (
        data["schema_version"] == 2 and set(data) != V2_FIELDS
    ) or data["schema_version"] not in {1, 2}:
        raise ManifestError("unsupported manifest shape or version")
    project = _bounded_path(root, data["project_root"], kind="project_root")
    if not project.is_dir() or project == root:
        raise ManifestError("project_root must be a project directory")
    if not isinstance(data["target"], str) or data["target"] not in {"fpga", "asic"}:
        raise ManifestError("target must be fpga or asic")
    kinds = data["source_kinds"]
    if not isinstance(kinds, list) or not kinds or not all(isinstance(value, str) for value in kinds) or len(kinds) != len(set(kinds)) or not set(kinds) <= {"handwritten", "generated"}:
        raise ManifestError("invalid source_kinds")
    if not isinstance(data["top"], str) or not IDENTIFIER.fullmatch(data["top"]):
        raise ManifestError("invalid top module name")
    roots = _paths(root, data["source_roots"], kind="source_roots")
    if not roots:
        raise ManifestError("source_roots must not be empty")
    if any(not _within(directory, project) for directory in roots.values()):
        raise ManifestError("source_roots must stay within project_root")
    sources = _paths(root, data["sources"], kind="sources", extensions=RTL_EXTENSIONS)
    headers = _paths(root, data["headers"], kind="headers", extensions=HEADER_EXTENSIONS)
    exclusions = data.get("excluded_sources", {})
    if not isinstance(exclusions, dict) or any(
        not isinstance(path, str) or not isinstance(reason, str) or reason not in EXCLUSION_REASONS
        for path, reason in exclusions.items()
    ):
        raise ManifestError("invalid excluded_sources")
    excluded_paths = _paths(root, list(exclusions), kind="excluded_sources", extensions=RTL_EXTENSIONS)
    if set(sources) & set(excluded_paths):
        raise ManifestError("source cannot be compiled and excluded")
    if not sources:
        raise ManifestError("sources must not be empty")
    scanned_sources, scanned_headers = _scan(root, roots)
    inventoried_sources = set(sources) | set(excluded_paths)
    if inventoried_sources != scanned_sources or set(headers) != scanned_headers:
        missing = sorted((scanned_sources - inventoried_sources) | (scanned_headers - set(headers)))
        extra = sorted((inventoried_sources - scanned_sources) | (set(headers) - scanned_headers))
        raise ManifestError(f"source inventory mismatch; omitted={missing}, outside_roots={extra}")
    includes = _paths(root, data["include_dirs"], kind="include_dirs")
    if any(not _within(directory, project) for directory in includes.values()):
        raise ManifestError("include_dirs must stay within project_root")
    for field in ("defines", "parameters"):
        values = data[field]
        if not isinstance(values, dict) or any(
            not isinstance(key, str) or not IDENTIFIER.fullmatch(key)
            or not isinstance(value, str) or not DEFINITION.fullmatch(value)
            for key, value in values.items()
        ):
            raise ManifestError(f"invalid {field}")
    for field in ("clocks", "resets"):
        values = data[field]
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values) or len(values) != len(set(values)) or any(
            not isinstance(value, str) or not IDENTIFIER.fullmatch(value) for value in values
        ):
            raise ManifestError(f"invalid {field}")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    try:
        data = validate_manifest(args.manifest, repository_root=args.repository_root)
    except (ManifestError, OSError, ValueError) as exc:
        print(f"RTL manifest BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(f"RTL manifest PASS: {data['top']} ({len(data['sources'])} sources, {len(data['headers'])} headers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
