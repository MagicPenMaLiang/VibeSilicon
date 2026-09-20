"""Fail closed when an inline RTL waiver lacks a current, exact registry entry.

This is a G0 waiver contract, not a replacement for G1 readability or signoff.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.quality_gate.rtl_manifest import ManifestError, _bounded_path, validate_manifest
from scripts.quality_gate.rtl_readability import RULES, WAIVER_RE, _strip_comments, analyze


FIELDS = {
    "id", "rule_id", "source", "module", "scope", "owner", "reason", "risk",
    "approved_by", "approved_at_utc", "expires_at_utc", "removal_condition",
    "compensating_verification", "source_sha256",
}
WAIVER_ID = re.compile(r"[A-Z][A-Z0-9-]{2,63}\Z")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
MODULE = re.compile(r"\bmodule\s+(?:automatic\s+)?([A-Za-z_][A-Za-z0-9_$]*)\b")
ENDMODULE = re.compile(r"\bendmodule\b")
SCOPE = re.compile(r"line:([1-9][0-9]*)\Z")


class WaiverRegistryError(ValueError):
    """The registry is malformed, stale, unapproved or does not match RTL."""


def _utc(value: str, field: str) -> datetime:
    if not isinstance(value, str):
        raise WaiverRegistryError(f"{field} must be a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WaiverRegistryError(f"invalid {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise WaiverRegistryError(f"{field} must be UTC")
    return parsed


def _module_at(lines: list[str], line_number: int) -> str | None:
    current: str | None = None
    for number, line in enumerate(_strip_comments(lines), 1):
        match = MODULE.search(line)
        if match:
            current = match.group(1)
        if number == line_number:
            return current
        if ENDMODULE.search(line):
            current = None
    return None


def _registry_path(root: Path, path: Path, *, project_root: str) -> Path:
    input_root = root.absolute()
    try:
        absolute = path if path.is_absolute() else input_root / path
        relative = absolute.absolute().relative_to(input_root).as_posix()
    except ValueError as exc:
        raise WaiverRegistryError("registry must be inside repository") from exc
    try:
        bounded = _bounded_path(root.resolve(strict=True), relative, kind="registry")
    except ManifestError as exc:
        raise WaiverRegistryError(str(exc)) from exc
    project = _bounded_path(root.resolve(strict=True), project_root, kind="project_root")
    if not bounded.is_relative_to(project):
        raise WaiverRegistryError("registry must be inside manifest project_root")
    if not bounded.is_file():
        raise WaiverRegistryError("registry is not a file")
    return bounded


def validate_waivers(
    manifest_path: Path, registry_path: Path | None = None, *, repository_root: Path,
    now: datetime | None = None,
) -> dict:
    """Recompute findings from manifest sources and validate each waiver exactly."""
    manifest = validate_manifest(manifest_path, repository_root=repository_root)
    root = repository_root.resolve(strict=True)
    if registry_path is None:
        registry_path = Path(manifest["project_root"]) / "rtl_quality_waivers.json"
    registry_file = _registry_path(repository_root, registry_path, project_root=manifest["project_root"])
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WaiverRegistryError("cannot read waiver registry") from exc
    if not isinstance(registry, dict) or set(registry) != {"schema_version", "standard_version", "waivers"}:
        raise WaiverRegistryError("invalid waiver registry shape")
    if type(registry["schema_version"]) is not int or registry["schema_version"] != 1 or registry["standard_version"] != "1.0":
        raise WaiverRegistryError("unsupported waiver registry version")
    if not isinstance(registry["waivers"], list):
        raise WaiverRegistryError("waivers must be an array")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise WaiverRegistryError("current time must be timezone-aware")
    current = current.astimezone(timezone.utc)

    entries: dict[str, dict] = {}
    for entry in registry["waivers"]:
        if not isinstance(entry, dict) or set(entry) != FIELDS:
            raise WaiverRegistryError("invalid waiver entry shape")
        if any(not isinstance(entry[field], str) or not entry[field].strip() for field in FIELDS):
            raise WaiverRegistryError("waiver fields must be non-empty strings")
        waiver_id = entry["id"]
        if not WAIVER_ID.fullmatch(waiver_id) or waiver_id in entries:
            raise WaiverRegistryError("invalid or duplicate waiver ID")
        if entry["rule_id"] not in RULES:
            raise WaiverRegistryError(f"unknown or unimplemented rule: {waiver_id}")
        if entry["source"] not in manifest["sources"] or not SCOPE.fullmatch(entry["scope"]):
            raise WaiverRegistryError(f"waiver has non-manifest source or imprecise scope: {waiver_id}")
        if not SHA256.fullmatch(entry["source_sha256"]):
            raise WaiverRegistryError(f"invalid source hash: {waiver_id}")
        if entry["owner"].casefold() == entry["approved_by"].casefold():
            raise WaiverRegistryError(f"waiver requires independent approval: {waiver_id}")
        approved = _utc(entry["approved_at_utc"], "approved_at_utc")
        expires = _utc(entry["expires_at_utc"], "expires_at_utc")
        if not approved <= current < expires:
            raise WaiverRegistryError(f"waiver is not currently approved: {waiver_id}")
        entries[waiver_id] = entry

    used: set[str] = set()
    for source in manifest["sources"]:
        source_path = _bounded_path(root, source, kind="source")
        raw = source_path.read_bytes()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        lines = raw.decode("utf-8").splitlines()
        findings = analyze(source_path, root=root)["violations"]
        if source_path.read_bytes() != raw:
            raise WaiverRegistryError(f"source changed during waiver validation: {source}")
        annotations: dict[str, tuple[str, int]] = {}
        code = _strip_comments(lines)
        for number, line in enumerate(lines, 1):
            match = WAIVER_RE.search(line)
            if "vibesilicon-waive" in line and (not match or not line.lstrip().startswith("//")):
                raise WaiverRegistryError(f"malformed waiver marker: {source}:{number}")
            if not match:
                continue
            waiver_id = match.group(2)
            if code[number - 1].strip() or waiver_id in annotations:
                raise WaiverRegistryError(f"waiver marker must be a unique comment: {source}:{number}")
            annotations[waiver_id] = (match.group(1), number)
        for waiver_id, (rule_id, marker_line) in annotations.items():
            entry = entries.get(waiver_id)
            if entry is None:
                raise WaiverRegistryError(f"unregistered inline waiver: {waiver_id}")
            matches = [item for item in findings if item["waiver_id"] == waiver_id]
            if len(matches) != 1 or matches[0]["rule_id"] != rule_id:
                raise WaiverRegistryError(f"waiver marker does not bind one finding: {waiver_id}")
            finding = matches[0]
            line_number = finding["line"]
            if marker_line not in {line_number, line_number - 1}:
                raise WaiverRegistryError(f"waiver marker is not adjacent: {waiver_id}")
            if (entry["source"], entry["rule_id"], entry["scope"], entry["module"], entry["source_sha256"]) != (
                source, rule_id, f"line:{line_number}", _module_at(lines, line_number), digest
            ):
                raise WaiverRegistryError(f"waiver scope or source changed: {waiver_id}")
            if waiver_id in used:
                raise WaiverRegistryError(f"waiver ID reused across sources: {waiver_id}")
            used.add(waiver_id)
        if any(item["waived"] and item["waiver_id"] not in annotations for item in findings):
            raise WaiverRegistryError(f"unverifiable waiver marker in {source}")
    if set(entries) != used:
        raise WaiverRegistryError(f"unused registry entries: {sorted(set(entries) - used)}")
    return {"status": "PASS", "gate": "G0_WAIVER_REGISTRY", "sources_checked": len(manifest["sources"]), "waivers_checked": len(used)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("registry", nargs="?", type=Path, help="defaults to <project_root>/rtl_quality_waivers.json")
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args(argv)
    try:
        result = validate_waivers(args.manifest, args.registry, repository_root=args.repository_root)
    except (ManifestError, WaiverRegistryError, OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "gate": "G0_WAIVER_REGISTRY", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
