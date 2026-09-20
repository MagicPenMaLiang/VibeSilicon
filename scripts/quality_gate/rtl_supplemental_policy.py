#!/usr/bin/env python3
"""Supplemental RTL maintenance, generated-source and CDC/RDC policy checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from scripts.quality_gate.rtl_manifest import validate_manifest
from scripts.quality_gate.rtl_quality_config import load_policy
from scripts.quality_gate.rtl_readability import _always_blocks, _strip_comments


ROOT = Path(__file__).resolve().parents[2]
HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
TODO = re.compile(r"\b(TODO|FIXME|XXX)(?:\(([A-Za-z][A-Za-z0-9_.-]{1,31})\))?\s*:", re.IGNORECASE)


class SupplementalPolicyError(ValueError):
    """A required supplemental quality contract is absent or inconsistent."""


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _content_id(value: dict) -> str:
    payload = json.dumps(
        {key: item for key, item in value.items() if key != "evidence_id"},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return _sha(payload)


def _manifest_file(root: Path, manifest_path: Path) -> Path:
    candidate = manifest_path if manifest_path.is_absolute() else root / manifest_path
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise SupplementalPolicyError("manifest escapes repository root")
    return resolved


def maintenance_snapshot(manifest_path: Path, *, repository_root: Path = ROOT) -> dict:
    """Produce warning-only complexity and TODO evidence without changing thresholds."""
    root = repository_root.resolve(strict=True)
    manifest = validate_manifest(manifest_path, repository_root=repository_root)
    policy = load_policy()
    thresholds = policy["readability_thresholds"]
    findings: list[dict] = []
    source_hashes: dict[str, str] = {}
    for source in sorted(manifest["sources"] + manifest["headers"]):
        target = (root / source).resolve(strict=True)
        raw = target.read_bytes()
        source_hashes[source] = _sha(raw)
        lines = raw.decode("utf-8").splitlines()
        code = _strip_comments(lines)
        module_lines = [number for number, line in enumerate(code, 1) if re.search(r"^\s*module\b", line)]
        if len(lines) > thresholds["module_lines_warn"] and module_lines:
            findings.append({"kind": "MODULE_LINES", "file": source, "line": module_lines[0],
                             "value": len(lines), "limit": thresholds["module_lines_warn"]})
        for block in _always_blocks(code):
            length = block["end"] - block["start"] + 1
            if length > thresholds["process_lines_warn"]:
                findings.append({"kind": "PROCESS_LINES", "file": source, "line": block["start"],
                                 "value": length, "limit": thresholds["process_lines_warn"]})
        depth = 0
        max_depth = 0
        max_depth_line = 1
        for number, line in enumerate(code, 1):
            depth += len(re.findall(r"\bbegin\b", line))
            if depth > max_depth:
                max_depth = depth
                max_depth_line = number
            depth = max(0, depth - len(re.findall(r"\bend\b", line)))
        if max_depth > thresholds["nesting_depth_warn"]:
            findings.append({"kind": "NESTING_DEPTH", "file": source, "line": max_depth_line,
                             "value": max_depth, "limit": thresholds["nesting_depth_warn"]})
        for number, line in enumerate(lines, 1):
            for match in TODO.finditer(line):
                findings.append({"kind": "OWNED_TODO" if match.group(2) else "UNOWNED_TODO",
                                 "file": source, "line": number, "value": 1, "limit": 0})
    findings.sort(key=lambda item: (item["file"], item["line"], item["kind"]))
    report = {
        "schema_version": 1, "status": "SHADOW", "rule_id": "RTL-MNT-001",
        "evidence_id": "", "source_set_sha256": _content_id(source_hashes),
        "finding_count": len(findings), "by_kind": {
            kind: sum(item["kind"] == kind for item in findings)
            for kind in sorted({item["kind"] for item in findings})
        },
        "preview": findings[:20], "findings_truncated": max(0, len(findings) - 20),
        "limitations": [
            "warning-only shadow evidence; no Quality Gate threshold change",
            "structural token counts do not replace elaborated lint or review",
        ],
    }
    report["evidence_id"] = _content_id(report)
    return report


def validate_generated_provenance(manifest_path: Path, *, repository_root: Path = ROOT) -> dict:
    root = repository_root.resolve(strict=True)
    manifest = validate_manifest(manifest_path, repository_root=repository_root)
    if "generated" not in manifest["source_kinds"]:
        return {"status": "NOT_APPLICABLE", "contract": None}
    contract_path = root / manifest["project_root"] / "rtl_generator_provenance.json"
    try:
        value = json.loads(contract_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SupplementalPolicyError("generated RTL requires rtl_generator_provenance.json") from exc
    required = {
        "schema_version", "generator", "generated_sources", "reproducible",
        "generated_by", "approved_by", "evidence_id",
    }
    if not isinstance(value, dict) or set(value) != required or value["schema_version"] != 1:
        raise SupplementalPolicyError("invalid generated RTL provenance shape")
    generator = value["generator"]
    if (not isinstance(generator, dict) or set(generator) != {"name", "version", "input_sha256"}
            or not all(isinstance(generator[key], str) and generator[key] for key in ("name", "version"))
            or not isinstance(generator["input_sha256"], str) or not HASH.fullmatch(generator["input_sha256"])):
        raise SupplementalPolicyError("invalid generator identity")
    generated = value["generated_sources"]
    if not isinstance(generated, list) or not generated:
        raise SupplementalPolicyError("generated source inventory is empty")
    observed = []
    for item in generated:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise SupplementalPolicyError("invalid generated source entry")
        if item["path"] not in manifest["sources"] or not isinstance(item["sha256"], str) or not HASH.fullmatch(item["sha256"]):
            raise SupplementalPolicyError("generated source is outside the manifest")
        if item["sha256"] != _sha((root / item["path"]).read_bytes()):
            raise SupplementalPolicyError("generated source hash mismatch")
        observed.append(item["path"])
    if len(observed) != len(set(observed)) or value["reproducible"] is not True:
        raise SupplementalPolicyError("generated RTL provenance is not reproducible")
    if (not isinstance(value["generated_by"], str) or not value["generated_by"].strip()
            or not isinstance(value["approved_by"], str) or not value["approved_by"].strip()
            or value["generated_by"] == value["approved_by"]):
        raise SupplementalPolicyError("generated RTL provenance lacks independent approval")
    if not isinstance(value["evidence_id"], str) or value["evidence_id"] != _content_id(value):
        raise SupplementalPolicyError("generated RTL provenance content ID mismatch")
    return {"status": "PASS", "contract": value["evidence_id"]}


def validate_domain_evidence(manifest_path: Path, *, repository_root: Path = ROOT) -> dict:
    root = repository_root.resolve(strict=True)
    manifest = validate_manifest(manifest_path, repository_root=repository_root)
    if len(manifest["clocks"]) <= 1 and len(manifest["resets"]) <= 1:
        return {"status": "NOT_APPLICABLE", "evidence_id": None}
    contract_path = root / manifest["project_root"] / "rtl_domain_evidence.json"
    try:
        value = json.loads(contract_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SupplementalPolicyError("multi-domain project requires CDC/RDC evidence") from exc
    required = {"schema_version", "top", "manifest_sha256", "clocks", "resets", "tool", "cdc_status", "rdc_status", "evidence_id"}
    manifest_file = _manifest_file(root, manifest_path)
    if not isinstance(value, dict) or set(value) != required or value["schema_version"] != 1:
        raise SupplementalPolicyError("invalid CDC/RDC evidence shape")
    tool = value["tool"]
    if (value["top"] != manifest["top"] or value["manifest_sha256"] != _sha(manifest_file.read_bytes())
            or value["clocks"] != manifest["clocks"] or value["resets"] != manifest["resets"]
            or not isinstance(tool, dict) or set(tool) != {"name", "version"}
            or not all(isinstance(tool[key], str) and tool[key] for key in tool)
            or value["cdc_status"] != "PASS" or value["rdc_status"] != "PASS"):
        raise SupplementalPolicyError("CDC/RDC evidence does not match the project")
    if not isinstance(value["evidence_id"], str) or value["evidence_id"] != _content_id(value):
        raise SupplementalPolicyError("CDC/RDC evidence content ID mismatch")
    return {"status": "PASS", "evidence_id": value["evidence_id"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("maintenance", "generated", "domains"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        functions = {
            "maintenance": maintenance_snapshot,
            "generated": validate_generated_provenance,
            "domains": validate_domain_evidence,
        }
        report = functions[args.action](args.manifest, repository_root=args.repository_root)
    except (SupplementalPolicyError, OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"gate": "RTL_SUPPLEMENTAL_POLICY", "status": "BLOCKED",
                          "reason_code": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
