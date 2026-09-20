"""Inventory legacy RTL readability findings without turning them into a gate.

This report is deliberately SHADOW, never PASS. It neither elaborates a project
nor proves that the selected tree contains every source for a particular top.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

from scripts.quality_gate.rtl_manifest import ManifestError, _bounded_path, _scan
from scripts.quality_gate.rtl_readability import RULESET_VERSION, analyze


ROOT = Path(__file__).resolve().parents[2]


def scan_shadow(project_root: str, source_root: str, *, repository_root: Path = ROOT) -> dict:
    """Return a bounded, source-hashed snapshot with no source-line excerpts."""
    root = repository_root.resolve(strict=True)
    project = _bounded_path(root, project_root, kind="project_root")
    directory = _bounded_path(root, source_root, kind="source_root")
    if not project.is_dir() or not directory.is_dir() or not directory.is_relative_to(project):
        raise ManifestError("source_root must be a directory inside project_root")
    sources, headers = _scan(root, {source_root: directory})
    if not sources:
        raise ManifestError("source_root contains no .v or .sv files")

    files: list[dict] = []
    header_inventory: list[dict] = []
    rule_counts: Counter[str] = Counter()
    blocking = warnings = waived = 0
    for relative in sorted(sources):
        path = _bounded_path(root, relative, kind="source")
        before = path.read_bytes()
        try:
            report = analyze(path, root=root)
        except UnicodeError as exc:
            raise ManifestError(f"source must be UTF-8: {relative}") from exc
        if path.read_bytes() != before:
            raise ManifestError(f"source changed during shadow scan: {relative}")
        summary = report["summary"]
        blocking += summary["blocking"]
        warnings += summary["warnings"]
        waived += summary["waived"]
        findings = [
            {"rule_id": item["rule_id"], "line": item["line"], "severity": item["severity"], "waived": item["waived"]}
            for item in report["violations"]
        ]
        rule_counts.update(item["rule_id"] for item in findings)
        files.append({
            "source": relative,
            "sha256": "sha256:" + hashlib.sha256(before).hexdigest(),
            "findings": findings,
        })

    for relative in sorted(headers):
        path = _bounded_path(root, relative, kind="header")
        before = path.read_bytes()
        if path.read_bytes() != before:
            raise ManifestError(f"header changed during shadow scan: {relative}")
        header_inventory.append({"source": relative, "sha256": "sha256:" + hashlib.sha256(before).hexdigest()})

    inventory = sorted(
        [{"source": item["source"], "sha256": item["sha256"]} for item in files + header_inventory],
        key=lambda item: item["source"],
    )
    source_set_sha256 = "sha256:" + hashlib.sha256(
        json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "schema_version": 1,
        "status": "SHADOW",
        "readability_ruleset_version": RULESET_VERSION,
        "project_root": project_root,
        "source_root": source_root,
        "source_count": len(sources),
        "header_count": len(headers),
        "source_set_sha256": source_set_sha256,
        "summary": {
            "blocking_candidates": blocking,
            "warning_candidates": warnings,
            "inline_waiver_marked_findings": waived,
            "by_rule": dict(sorted(rule_counts.items())),
        },
        "files": files,
        "headers": header_inventory,
        "limitations": [
            "directory inventory is not a reviewed compilation manifest",
            "legacy readability findings are candidates, not adjudicated project failures",
            "headers are inventoried but not passed to the legacy readability scanner",
            "no elaboration, simulation, CDC/RDC, implementation or signoff was run",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", help="repository-relative project directory")
    parser.add_argument("source_root", help="repository-relative RTL source directory")
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        result = scan_shadow(args.project_root, args.source_root, repository_root=args.repository_root)
    except (ManifestError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
