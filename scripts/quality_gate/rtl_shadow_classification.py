"""Validate a source-bound role inventory for a legacy RTL shadow scan.

Classification is not a compilation manifest or a quality gate PASS.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.quality_gate.rtl_manifest import ManifestError, _bounded_path
from scripts.quality_gate.rtl_shadow_baseline import ROOT, scan_shadow


ROLES = {"design_candidate", "testbench", "archive"}


def classify_shadow(inventory_path: str, *, repository_root: Path = ROOT) -> dict:
    root = repository_root.resolve(strict=True)
    path = _bounded_path(root, inventory_path, kind="classification")
    if not path.is_file():
        raise ManifestError("classification must be a file")
    try:
        inventory = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("classification must be UTF-8 JSON") from exc
    if not isinstance(inventory, dict) or set(inventory) != {
        "schema_version", "project_root", "source_root", "source_set_sha256", "groups"
    } or inventory["schema_version"] != 1:
        raise ManifestError("invalid classification schema")
    groups = inventory["groups"]
    if not isinstance(groups, dict) or set(groups) != ROLES:
        raise ManifestError("classification requires exactly the reviewed roles")
    if not all(isinstance(items, list) and all(isinstance(item, str) for item in items)
               for items in groups.values()):
        raise ManifestError("classification groups must contain path arrays")
    assigned = [item for role in sorted(ROLES) for item in groups[role]]
    if len(assigned) != len(set(assigned)):
        raise ManifestError("duplicate classified source")
    snapshot = scan_shadow(inventory["project_root"], inventory["source_root"], repository_root=root)
    actual = {item["source"] for item in snapshot["files"]}
    if set(assigned) != actual:
        raise ManifestError("classification has missing or unexpected RTL sources")
    if inventory["source_set_sha256"] != snapshot["source_set_sha256"]:
        raise ManifestError("classification source set hash drift")
    return {
        "schema_version": 1,
        "status": "CLASSIFIED_SHADOW",
        "project_root": inventory["project_root"],
        "source_root": inventory["source_root"],
        "source_set_sha256": snapshot["source_set_sha256"],
        "role_counts": {role: len(groups[role]) for role in sorted(ROLES)},
        "limitations": [
            "roles do not select a production top or a complete compilation set",
            "no elaboration, simulation, implementation or signoff was run",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory_path", help="repository-relative classification JSON")
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        result = classify_shadow(args.inventory_path, repository_root=args.repository_root)
    except (ManifestError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
