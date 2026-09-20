#!/usr/bin/env python3
"""Fail-closed, path-free health evidence for required RTL quality tools."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.quality_gate.rtl_quality_config import load_policy


class ToolHealthError(ValueError):
    """A required tool is missing, unapproved, or cannot be inspected."""


def _digest(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except (OSError, ValueError) as exc:
        raise ToolHealthError("cannot hash required tool") from exc
    return f"sha256:{digest.hexdigest()}"


def _resolve(names: tuple[str, ...]) -> Path:
    selected = None
    for name in names:
        selected = shutil.which(name)
        if selected:
            break
    if not selected:
        raise ToolHealthError(f"required tool unavailable: {names[0]}")
    path = Path(selected).resolve()
    if not path.is_file():
        raise ToolHealthError(f"required tool unavailable: {names[0]}")
    return path


def _version(path: Path, expression: str, name: str) -> tuple[str, int]:
    try:
        result = subprocess.run(
            [str(path), "--version"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolHealthError(f"required tool version probe failed: {name}") from exc
    match = re.search(expression, result.stdout)
    if result.returncode or not match:
        raise ToolHealthError(f"required tool version probe failed: {name}")
    return match.group(0), int(match.group(1))


def collect_health() -> dict:
    """Record versions and binary hashes; never publish local installation paths."""
    versions = load_policy()["tool_versions"]
    python_rule = versions["python"]
    if (
        sys.version_info.major not in python_rule["accepted_major"]
        or sys.version_info.minor < python_rule["minimum_minor"]
    ):
        raise ToolHealthError("unapproved Python version")
    python_path = Path(sys.executable).resolve()
    git_path = _resolve(("git",))
    verilator_path = _resolve(("verilator_bin", "verilator"))
    git_version, _ = _version(git_path, r"git version (\d+)\.\d+(?:\.\d+)?", "git")
    verilator_version, verilator_major = _version(
        verilator_path, r"Verilator (\d+)\.\d+", "verilator"
    )
    if verilator_major not in versions["verilator"]["accepted_major"]:
        raise ToolHealthError("unapproved Verilator version")
    return {
        "schema_version": 1,
        "status": "PASS",
        "tools": {
            "python": {
                "version": f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                "binary_sha256": _digest(python_path),
            },
            "git": {"version": git_version, "binary_sha256": _digest(git_path)},
            "verilator": {
                "version": verilator_version,
                "binary_sha256": _digest(verilator_path),
            },
        },
        "optional_not_run": ["iverilog"],
    }


def main() -> int:
    try:
        report = collect_health()
    except (ToolHealthError, OSError, ValueError) as exc:
        print(f"RTL tool health BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
