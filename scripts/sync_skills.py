#!/usr/bin/env python3
"""Validate canonical skills and synchronize complete native platform copies."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = (".agents/skills", ".claude/skills")


def inventory(root: Path) -> tuple[dict, dict[str, bytes]]:
    files = {}
    entries = []
    canonical = (root / "skills").resolve(strict=True)
    if not canonical.is_relative_to(root.resolve(strict=True)):
        raise ValueError("canonical skill directory escapes repository")
    for skill in sorted((root / "skills").glob("*/SKILL.md")):
        if skill.parent.is_symlink() or not skill.parent.resolve().is_relative_to(canonical):
            raise ValueError("skill directory escapes canonical root")
        text = skill.read_text(encoding="utf-8")
        name = re.search(r"^name: ([a-z0-9-]+)$", text, re.M)
        if not text.startswith("---\n") or not name or name[1] != skill.parent.name:
            raise ValueError(f"invalid skill identity: {skill}")
        for target in re.findall(r"`((?:references|templates|scripts)/[^`]+)`", text):
            # A repository-level template may be shared, but local resources win.
            local = (skill.parent / target).resolve()
            shared = (root / target).resolve()
            if not local.is_relative_to(skill.parent.resolve()) or not shared.is_relative_to(root.resolve()):
                raise ValueError(f"resource escapes skill/repository: {target}")
            if not local.exists() and not shared.exists():
                raise ValueError(f"missing resource in {name[1]}: {target}")
        for resource in sorted(skill.parent.rglob("*")):
            if resource.is_symlink() or not resource.resolve().is_relative_to(skill.parent.resolve()):
                raise ValueError(f"skill symlinks are unsupported: {resource}")
            if resource.is_file():
                files[resource.relative_to(root / "skills").as_posix()] = resource.read_bytes()
        entries.append({"name": name[1], "dir": name[1], "path": f"skills/{name[1]}/SKILL.md"})
    if not entries:
        raise ValueError("no canonical skills")
    return {"schema_version": "1.0", "project": "VibeSilicon", "skill_count": len(entries), "skills": entries}, files


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
    for adapter in ADAPTERS:
        base = root / adapter
        if base.is_symlink() or not base.resolve().is_relative_to(root):
            raise ValueError(f"adapter escapes repository: {adapter}")
        # Unknown files are reported, never silently deleted.
        for path in base.rglob("*"):
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
