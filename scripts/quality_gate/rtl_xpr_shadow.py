#!/usr/bin/env python3
"""Inventory unsafe-case and four-state RTL constructs without changing gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from bisect import bisect_right
from collections import Counter
from pathlib import Path

from scripts.quality_gate.rtl_manifest import ManifestError, _bounded_path, validate_manifest


ROOT = Path(__file__).resolve().parents[2]
CASEX = re.compile(r"\bcasex\s*\(", re.IGNORECASE)
FOUR_STATE = re.compile(
    r"(?<![A-Za-z0-9_$])(?:[0-9]+\s*)?'(?:[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]*[xXzZ][0-9a-fA-F_xXzZ?]*|[xXzZ])\b"
)


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _normal_text(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n")


def _mask_non_code(source: str) -> str:
    """Mask comments and strings, retaining offsets and newline positions."""
    masked: list[str] = []
    state = "code"
    index = 0
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if char == "/" and following == "/":
                masked.extend("  ")
                index += 2
                state = "line"
                continue
            if char == "/" and following == "*":
                masked.extend("  ")
                index += 2
                state = "block"
                continue
            if char == '"':
                masked.append(" ")
                state = "string"
            else:
                masked.append(char)
        elif state == "line":
            masked.append("\n" if char == "\n" else " ")
            if char == "\n":
                state = "code"
        elif state == "block":
            if char == "*" and following == "/":
                masked.extend("  ")
                index += 2
                state = "code"
                continue
            masked.append("\n" if char == "\n" else " ")
        else:
            if char == "\\" and following:
                masked.extend("\n" if item == "\n" else " " for item in (char, following))
                index += 2
                continue
            masked.append("\n" if char == "\n" else " ")
            if char == '"':
                state = "code"
        index += 1
    if state in {"block", "string"}:
        raise ValueError("unterminated RTL comment or string")
    return "".join(masked)


def _findings(source: str, path: str) -> list[dict]:
    masked = _mask_non_code(source)
    newlines = [index for index, char in enumerate(masked) if char == "\n"]
    findings = []
    for match in CASEX.finditer(masked):
        findings.append({"rule_id": "RTL-XPR-001", "kind": "CASEX", "file": path,
                         "line": bisect_right(newlines, match.start()) + 1})
    for match in FOUR_STATE.finditer(masked):
        literal = match.group(0).lower()
        kind = "Z_LITERAL" if "z" in literal else "X_LITERAL"
        findings.append({"rule_id": "RTL-XPR-001", "kind": kind, "file": path,
                         "line": bisect_right(newlines, match.start()) + 1})
    return sorted(findings, key=lambda row: (row["file"], row["line"], row["kind"]))


def snapshot(manifest: Path, *, repository_root: Path = ROOT) -> dict:
    root = repository_root.resolve(strict=True)
    if manifest.is_absolute():
        raise ManifestError("shadow manifest must be repository-relative")
    manifest_file = _bounded_path(root, manifest.as_posix(), kind="manifest")
    manifest_bytes = _normal_text(manifest_file.read_bytes())
    data = validate_manifest(manifest, repository_root=repository_root)
    paths = sorted(data["sources"] + data["headers"])
    before = {
        path: _normal_text(_bounded_path(root, path, kind="source").read_bytes())
        for path in paths
    }
    findings = []
    for path, raw in before.items():
        findings.extend(_findings(raw.decode("utf-8"), path))
    after = {
        path: _normal_text(_bounded_path(root, path, kind="source").read_bytes())
        for path in paths
    }
    if before != after or manifest_bytes != _normal_text(manifest_file.read_bytes()):
        raise ManifestError("manifest or source changed during RTL-XPR shadow scan")
    manifest_hash = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    counts = dict(sorted(Counter(item["kind"] for item in findings).items()))
    return {
        "schema_version": 1,
        "status": "SHADOW",
        "rule_id": "RTL-XPR-001",
        "manifest_sha256": manifest_hash,
        "source_set_sha256": _digest({path: hashlib.sha256(raw).hexdigest() for path, raw in before.items()}),
        "finding_set_sha256": _digest(findings),
        "finding_count": len(findings),
        "by_kind": counts,
        "preview": findings[:20],
        "limitations": [
            "review inventory only; no severity or merge gate change",
            "X/Z literals may be intentional; inspect context before repair",
            "only selected manifest sources and headers are scanned",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        report = snapshot(args.manifest, repository_root=args.repository_root)
    except (ManifestError, OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
