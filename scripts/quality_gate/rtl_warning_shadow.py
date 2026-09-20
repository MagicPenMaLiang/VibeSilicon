"""Inventory Verilator warnings without changing lint severity or merge gates.

This is a content-bound SHADOW comparison, not a clean-RTL or signoff PASS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from scripts.quality_gate.rtl_manifest import ManifestError, _bounded_path, validate_manifest
from scripts.quality_gate.rtl_project_lint import ROOT, run_lint


REVIEW_FIRST = {"IMPLICIT", "UNDRIVEN", "ALWNEVER"}
NUMERIC_REVIEW = {"WIDTHTRUNC", "WIDTHEXPAND"}
CLEANUP_REVIEW = {"UNUSEDSIGNAL", "UNUSEDPARAM", "DECLFILENAME"}


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _text_sha256(raw: bytes) -> str:
    """Bind textual inputs across LF/CRLF Git checkouts without hiding edits."""
    return "sha256:" + hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def _text_inputs(manifest_path: Path, *, repository_root: Path) -> tuple[str, dict[str, str]]:
    root = repository_root.resolve(strict=True)
    data = validate_manifest(manifest_path, repository_root=repository_root)
    manifest_file = manifest_path if manifest_path.is_absolute() else root / manifest_path
    sources = data["sources"] + data["headers"] + list(data.get("excluded_sources", {}))
    source_hashes = {
        source: _text_sha256(_bounded_path(root, source, kind="source").read_bytes())
        for source in sources
    }
    return _text_sha256(manifest_file.read_bytes()), source_hashes


def snapshot(manifest_path: Path, *, repository_root: Path = ROOT, verilator: str | None = None) -> dict:
    normalized_before = _text_inputs(manifest_path, repository_root=repository_root)
    lint = run_lint(manifest_path, repository_root=repository_root, verilator=verilator,
                    include_warning_headers=True)
    if _text_inputs(manifest_path, repository_root=repository_root) != normalized_before:
        raise ManifestError("manifest or source changed during warning snapshot")
    if lint["status"] != "PASS":
        raise ManifestError("Verilator lint failed; cannot baseline warnings")
    warnings = lint["warning_headers"]
    by_code = dict(sorted(Counter(item["code"] for item in warnings).items()))
    known = REVIEW_FIRST | NUMERIC_REVIEW | CLEANUP_REVIEW
    priority = {
        "review_first": sum(by_code.get(code, 0) for code in REVIEW_FIRST),
        "numeric_review": sum(by_code.get(code, 0) for code in NUMERIC_REVIEW),
        "cleanup_review": sum(by_code.get(code, 0) for code in CLEANUP_REVIEW),
        "unclassified": sum(count for code, count in by_code.items() if code not in known),
    }
    return {
        "schema_version": 1,
        "text_normalization": "CRLF-to-LF",
        "manifest_sha256": normalized_before[0],
        "source_set_sha256": _digest(normalized_before[1]),
        "tool_version": lint["tool"]["version"],
        "warning_set_sha256": _digest(warnings),
        "warning_count": len(warnings),
        "by_code": by_code,
        "triage_counts": priority,
        "review_first_locations": [item for item in warnings if item["code"] in REVIEW_FIRST],
    }


def compare_snapshot(manifest_path: Path, baseline_path: str, *, repository_root: Path = ROOT,
                     verilator: str | None = None) -> dict:
    root = repository_root.resolve(strict=True)
    manifest = validate_manifest(manifest_path, repository_root=repository_root)
    baseline_file = _bounded_path(root, baseline_path, kind="warning baseline")
    project = _bounded_path(root, manifest["project_root"], kind="project_root")
    if not baseline_file.is_file() or not baseline_file.is_relative_to(project):
        raise ManifestError("warning baseline must be a project-local file")
    try:
        expected = json.loads(baseline_file.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("warning baseline must be UTF-8 JSON") from exc
    observed = snapshot(manifest_path, repository_root=repository_root, verilator=verilator)
    if not isinstance(expected, dict) or set(expected) != set(observed):
        raise ManifestError("warning baseline shape is invalid")
    return {
        "status": "SHADOW_MATCH" if expected == observed else "SHADOW_DRIFT",
        "warning_count": observed["warning_count"],
        "by_code": observed["by_code"],
        "triage_counts": observed["triage_counts"],
        "source_set_sha256": observed["source_set_sha256"],
        "warning_set_sha256": observed["warning_set_sha256"],
        "review_first_locations": observed["review_first_locations"],
        "limitations": ["non-blocking legacy warning inventory", "triage classes are review order, not confirmed defects", "no RTL repair or signoff was run"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("baseline", nargs="?", help="project-local JSON snapshot to compare")
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--verilator", help="explicit Verilator executable")
    args = parser.parse_args(argv)
    try:
        if args.baseline:
            report = compare_snapshot(args.manifest, args.baseline, repository_root=args.repository_root,
                                      verilator=args.verilator)
        else:
            report = {"status": "SHADOW", **snapshot(args.manifest, repository_root=args.repository_root,
                                                       verilator=args.verilator)}
    except (ManifestError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
