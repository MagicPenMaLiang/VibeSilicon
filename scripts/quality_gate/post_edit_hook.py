#!/usr/bin/env python3
"""Translate Claude Code/Codex edit-hook payloads into VibeSilicon L1 checks."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


RTL_SUFFIXES = {".v", ".sv", ".svh"}
PATCH_FILE = re.compile(r"^\*\*\* (Add|Update|Delete) File:\s*(.+?)\s*$")
PATCH_MOVE = re.compile(r"^\*\*\* Move to:\s*(.+?)\s*$")


def find_root(cwd: str | None = None) -> Path:
    starts = [Path(cwd).resolve()] if cwd else []
    starts.extend([Path.cwd().resolve(), Path(__file__).resolve().parents[2]])
    for start in starts:
        current = start if start.is_dir() else start.parent
        for candidate in (current, *current.parents):
            if (candidate / ".git").exists() and (candidate / "AGENTS.md").is_file():
                return candidate
    return Path(__file__).resolve().parents[2]


def _resolve_rtl(root: Path, raw_path: str) -> Path | None:
    value = raw_path.strip().strip('"').strip("'")
    candidate = Path(value)
    candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.suffix.lower() in RTL_SUFFIXES else None


def extract_patch_paths(patch: str) -> list[str]:
    """Return post-patch paths, replacing an Update path when its block moves."""
    paths: list[str] = []
    current_update: str | None = None
    for line in patch.splitlines():
        file_match = PATCH_FILE.match(line)
        if file_match:
            action, path = file_match.groups()
            current_update = path if action == "Update" else None
            if action in {"Add", "Update"}:
                paths.append(path)
            continue
        move_match = PATCH_MOVE.match(line)
        if move_match:
            destination = move_match.group(1)
            if current_update is not None:
                for index in range(len(paths) - 1, -1, -1):
                    if paths[index] == current_update:
                        paths.pop(index)
                        break
            paths.append(destination)
            current_update = None
    return paths


def extract_edited_rtl(payload: dict, platform: str, root: Path) -> list[Path]:
    tool_input = payload.get("tool_input") or {}
    raw_paths: list[str] = []
    for key in ("file_path", "path"):
        if isinstance(tool_input.get(key), str):
            raw_paths.append(tool_input[key])

    if platform == "codex":
        patch = tool_input.get("command", "")
        if isinstance(patch, str):
            raw_paths.extend(extract_patch_paths(patch))

    result: list[Path] = []
    seen: set[Path] = set()
    for raw_path in raw_paths:
        path = _resolve_rtl(root, raw_path)
        if path is not None and path not in seen:
            seen.add(path)
            result.append(path)
    return result


def run_gate(root: Path, source: Path, timeout: int = 30) -> tuple[bool, str]:
    if not source.is_file():
        return False, f"edited RTL file does not exist: {source}"
    checker = root / "scripts" / "quality_gate" / "post_run_check.py"
    with tempfile.TemporaryDirectory(prefix="vibesilicon-hook-") as temp_dir:
        report = Path(temp_dir) / "report.json"
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(checker),
                    "--fast",
                    "--source",
                    str(source),
                    "--output",
                    str(report),
                ],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"quality gate could not run for {source}: {exc}"
        detail = (completed.stdout + "\n" + completed.stderr).strip()
        if completed.returncode != 0:
            return False, detail or f"quality gate failed for {source}"

    return True, detail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("claude", "codex"), required=True)
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, TypeError) as exc:
        print(f"VibeSilicon hook received invalid JSON: {exc}", file=sys.stderr)
        return 2

    root = find_root(payload.get("cwd"))
    edited = extract_edited_rtl(payload, args.platform, root)
    failures: list[str] = []
    for source in edited:
        ok, detail = run_gate(root, source)
        if not ok:
            failures.append(f"{source.relative_to(root)}\n{detail}")
    if failures:
        print(
            "VibeSilicon L1 quality gate rejected this RTL edit:\n" + "\n\n".join(failures),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
