#!/usr/bin/env python3
"""Validate canonical skills and synchronize complete native platform copies."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = (".agents/skills", ".claude/skills")
RUNTIME_DIRS = {".omc", ".omo", "__pycache__", ".pytest_cache", ".ruff_cache"}


def inventory(root: Path) -> tuple[dict, dict[str, bytes]]:
    files = {}
    entries = []
    canonical = (root / "skills").resolve(strict=True)
    if not canonical.is_relative_to(root.resolve(strict=True)):
        raise ValueError("canonical skill directory escapes repository")
    for skill in sorted((root / "skills").glob("*/SKILL.md")):
        if skill.is_symlink() or skill.parent.is_symlink() or not skill.parent.resolve().is_relative_to(canonical):
            raise ValueError("skill directory escapes canonical root")
        text = skill.read_text(encoding="utf-8")
        name = re.search(r"^name: ([a-z0-9-]+)$", text, re.M)
        if not text.startswith("---\n") or not name or name[1] != skill.parent.name:
            raise ValueError(f"invalid skill identity: {skill}")
        parts = text.split("---\n", 2)
        if len(parts) != 3:
            raise ValueError(f"invalid skill frontmatter: {skill}")
        frontmatter = yaml.safe_load(parts[1])
        if not isinstance(frontmatter, dict) or frontmatter.get("name") != name[1]:
            raise ValueError(f"invalid skill frontmatter: {skill}")
        metadata = frontmatter.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError(f"invalid skill metadata: {skill}")
        routes = metadata.get("routes", [])
        if (not isinstance(routes, list) or any(not isinstance(route, str) or route not in {"fpga", "asic", "both"} for route in routes)
                or len(routes) != len(set(routes))):
            raise ValueError(f"invalid skill routes: {skill}")
        alias = metadata.get("alias_of")
        if alias is not None and (not isinstance(alias, str) or not re.fullmatch(r"[a-z0-9-]+", alias)):
            raise ValueError(f"invalid skill alias: {skill}")
        for target in re.findall(r"`((?:references|templates|scripts)/[^`]+)`", text):
            # A repository-level template may be shared, but local resources win.
            local = (skill.parent / target).resolve()
            shared = (root / target).resolve()
            if not local.is_relative_to(skill.parent.resolve()) or not shared.is_relative_to(root.resolve()):
                raise ValueError(f"resource escapes skill/repository: {target}")
            if not local.exists() and not shared.exists():
                raise ValueError(f"missing resource in {name[1]}: {target}")
        for resource in sorted(skill.parent.rglob("*")):
            if RUNTIME_DIRS.intersection(resource.relative_to(skill.parent).parts):
                continue
            if resource.is_symlink() or not resource.resolve().is_relative_to(skill.parent.resolve()):
                raise ValueError(f"skill symlinks are unsupported: {resource}")
            if resource.is_file():
                files[resource.relative_to(root / "skills").as_posix()] = resource.read_bytes()
        entry = {
            "name": name[1], "dir": name[1], "path": f"skills/{name[1]}/SKILL.md",
            "category": metadata.get("category", "unspecified"), "routes": routes,
            "kind": "compatibility" if alias else "canonical",
        }
        if alias:
            entry["alias_of"] = alias
            entry["resources_source"] = alias
        entries.append(entry)
    if not entries:
        raise ValueError("no canonical skills")
    by_name = {entry["name"]: entry for entry in entries}
    for entry in entries:
        alias = entry.get("alias_of")
        if alias and (alias not in by_name or by_name[alias]["kind"] != "canonical"
                      or entry["routes"] != by_name[alias]["routes"]):
            raise ValueError(f"skill alias must resolve directly to matching canonical routes: {entry['name']}")
        if alias:
            alias_prefix = entry["name"] + "/"
            target_prefix = alias + "/"
            resources = {relative.removeprefix(target_prefix): content for relative, content in files.items()
                         if relative.startswith(target_prefix) and relative != target_prefix + "SKILL.md"}
            for relative in list(files):
                if relative.startswith(alias_prefix) and relative != alias_prefix + "SKILL.md":
                    if relative.removeprefix(alias_prefix) not in resources:
                        raise ValueError(f"unexpected compatibility resource: {relative}")
            for relative, content in resources.items():
                files[alias_prefix + relative] = content
    alias_count = sum(entry["kind"] == "compatibility" for entry in entries)
    return {
        "schema_version": "1.1", "project": "VibeSilicon", "skill_count": len(entries),
        "canonical_skill_count": len(entries) - alias_count, "compatibility_alias_count": alias_count,
        "skills": entries,
    }, files


def synchronize(root: Path = ROOT, *, write: bool = False) -> list[str]:
    root = root.resolve(strict=True)
    manifest, files = inventory(root)
    differences = []
    manifest_path = root / "skills/manifest.json"
    raw = (json.dumps(manifest, indent=2) + "\n").encode()
    if not manifest_path.is_file() or manifest_path.read_bytes() != raw:
        differences.append("skills/manifest.json")
        if write:
            manifest_path.write_bytes(raw)
    for entry in manifest["skills"]:
        if entry["kind"] != "compatibility":
            continue
        prefix = entry["name"] + "/"
        for relative, content in files.items():
            if not relative.startswith(prefix) or relative == prefix + "SKILL.md":
                continue
            path = root / "skills" / relative
            if not path.is_file() or path.read_bytes() != content:
                differences.append(path.relative_to(root).as_posix())
                if write:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
    for adapter in ADAPTERS:
        base = root / adapter
        if base.is_symlink() or not base.resolve().is_relative_to(root):
            raise ValueError(f"adapter escapes repository: {adapter}")
        # Unknown files are reported, never silently deleted.
        for path in base.rglob("*"):
            if RUNTIME_DIRS.intersection(path.relative_to(base).parts):
                continue
            if path.is_symlink():
                raise ValueError(f"adapter symlink: {path}")
            if path.is_file() and path.relative_to(base).as_posix() not in files:
                differences.append(f"unexpected: {path.relative_to(root).as_posix()}")
        for relative, content in files.items():
            target = base / relative
            if not target.resolve().is_relative_to(base.resolve()):
                raise ValueError(f"adapter resource escapes: {relative}")
            if not target.is_file() or target.read_bytes() != content:
                differences.append(target.relative_to(root).as_posix())
                if write:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
    return differences


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    differences = synchronize(write=args.write)
    remaining = synchronize() if args.write else differences
    print(json.dumps({"status": "FAIL" if remaining else "PASS", "differences": remaining}))
    return 1 if remaining else 0


if __name__ == "__main__":
    raise SystemExit(main())
