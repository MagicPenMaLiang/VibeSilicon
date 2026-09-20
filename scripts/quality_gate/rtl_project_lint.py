#!/usr/bin/env python3
"""Fail-closed multi-file Verilator lint from a reviewed RTL project manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.quality_gate.rtl_manifest import ManifestError, validate_manifest
from scripts.quality_gate.rtl_quality_config import RtlQualityConfigError, load_policy


ROOT = Path(__file__).resolve().parents[2]
VERSION = re.compile(r"\bVerilator\s+(\d+)\.(\d+)\b")
WARNING_HEADER = re.compile(r"^%Warning-([A-Z0-9_]+):\s+(.+?):([1-9][0-9]*):([1-9][0-9]*):")


def _binary(value: str | None) -> Path:
    selected = value or shutil.which("verilator_bin") or shutil.which("verilator")
    if not selected:
        raise ManifestError("required Verilator tool is unavailable")
    path = Path(selected).resolve()
    if not path.is_file():
        raise ManifestError("required Verilator tool is unavailable")
    return path


def _environment(binary: Path) -> dict[str, str]:
    env = os.environ.copy()
    if os.name == "nt" and binary.stem.lower() == "verilator_bin" and not env.get("VERILATOR_ROOT"):
        candidate = binary.parent.parent / "share" / "verilator"
        if candidate.is_dir():
            env["VERILATOR_ROOT"] = str(candidate)
    return env


def _hash_sources(root: Path, data: dict) -> dict[str, str]:
    return {
        source: hashlib.sha256((root / source).read_bytes()).hexdigest()
        for source in data["sources"] + data["headers"] + list(data.get("excluded_sources", {}))
    }


def _warning_headers(stderr: str, allowed_sources: set[str]) -> list[dict]:
    """Keep only bounded, repository-relative warning locations, not RTL excerpts."""
    warnings = []
    for line in stderr.splitlines():
        if not line.startswith("%Warning-"):
            continue
        match = WARNING_HEADER.match(line)
        if not match:
            raise ManifestError("unrecognized Verilator warning header")
        code, source, line_number, column = match.groups()
        source = source.replace("\\", "/")
        if source not in allowed_sources:
            raise ManifestError("Verilator warning source is outside manifest")
        warnings.append({"code": code, "source": source, "line": int(line_number), "column": int(column)})
    return sorted(warnings, key=lambda item: (item["source"], item["line"], item["column"], item["code"]))


def run_lint(manifest: Path, *, repository_root: Path = ROOT, verilator: str | None = None, timeout: int = 120,
             include_warning_headers: bool = False) -> dict:
    if type(timeout) is not int or timeout < 1 or timeout > 900:
        raise ManifestError("lint timeout must be 1..900 seconds")
    root = repository_root.resolve(strict=True)
    # Validation needs the caller's root spelling so Windows 8.3 paths in
    # temporary test projects remain comparable before canonical safety checks.
    data = validate_manifest(manifest, repository_root=repository_root)
    manifest_file = manifest if manifest.is_absolute() else root / manifest
    manifest_hash = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
    source_hashes = _hash_sources(root, data)
    binary = _binary(verilator)
    env = _environment(binary)
    try:
        version_result = subprocess.run(
            [str(binary), "--version"], cwd=root, env=env, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ManifestError("cannot execute required Verilator version probe") from exc
    match = VERSION.search(version_result.stdout)
    if version_result.returncode != 0 or not match:
        raise ManifestError("cannot verify Verilator version")
    major = int(match.group(1))
    if major not in load_policy()["tool_versions"]["verilator"]["accepted_major"]:
        raise ManifestError(f"unapproved Verilator major version: {major}")
    args = [str(binary), "--lint-only", "--timing", "-Wall", "-Wno-fatal", "--top-module", data["top"]]
    args.extend(f"-I{directory}" for directory in data["include_dirs"])
    args.extend(f"+define+{key}={value}" for key, value in sorted(data["defines"].items()))
    args.extend(f"-G{key}={value}" for key, value in sorted(data["parameters"].items()))
    args.extend(data["sources"])
    try:
        result = subprocess.run(
            args, cwd=root, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ManifestError(f"Verilator lint exceeded {timeout}s timeout") from exc
    except OSError as exc:
        raise ManifestError("required Verilator lint could not start") from exc
    if hashlib.sha256(manifest_file.read_bytes()).hexdigest() != manifest_hash or _hash_sources(root, data) != source_hashes:
        raise ManifestError("manifest or source changed during Verilator lint")
    report = {
        "schema_version": 1,
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "top": data["top"],
        "target": data["target"],
        "manifest_sha256": manifest_hash,
        "source_sha256": source_hashes,
        "tool": {"name": "verilator", "version": match.group(0)},
        "returncode": result.returncode,
        "stdout": result.stdout[-8192:],
        "stderr": result.stderr[-8192:],
    }
    if include_warning_headers:
        report["warning_headers"] = _warning_headers(result.stderr, set(data["sources"] + data["headers"]))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--verilator", help="explicit Verilator binary; otherwise resolve from PATH")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--output", type=Path, help="write bounded JSON result inside the repository")
    args = parser.parse_args(argv)
    try:
        report = run_lint(args.manifest, repository_root=args.repository_root, verilator=args.verilator, timeout=args.timeout)
        if args.output:
            root = args.repository_root.resolve(strict=True)
            output = args.output if args.output.is_absolute() else root / args.output
            if (
                not output.parent.resolve().is_relative_to(root)
                or output.is_symlink()
                or output.exists()
                or not output.parent.is_dir()
            ):
                raise ManifestError("output must be a new file in a non-linked repository directory")
            with output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except (ManifestError, RtlQualityConfigError, OSError, ValueError) as exc:
        print(f"RTL project lint BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(f"RTL project lint {report['status']}: {report['top']} with {report['tool']['version']}")
    if report["status"] != "PASS":
        print(report["stderr"], file=sys.stderr)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
