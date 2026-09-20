"""Fail closed when a public source tree contains local or generated assets."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
BLOCKED_TOP_LEVEL = {"project", "artifacts", "runner-work", "private", "licenses", "pdks"}
BLOCKED_SUFFIXES = {
    ".bit", ".dcp", ".gds", ".jou", ".log", ".ltx", ".spef", ".str", ".tar", ".wdb", ".zip"
}
MAX_FILE_BYTES = 2 * 1024 * 1024
TEXT_SUFFIXES = {
    "", ".bat", ".cfg", ".cpp", ".h", ".json", ".md", ".ps1", ".py", ".sv", ".svh",
    ".tcl", ".toml", ".txt", ".v", ".yaml", ".yml",
}
TEXT_BLOCKERS = (
    re.compile(r"(?i)(?:^|[\s=\"'])(?:[A-Z]:[\\/](?![^\s]*<)|/(?:home|Users)/[^/\s]+)"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*[\"'][^\"']+[\"']"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def source_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"symbolic link is not allowed in public source: {relative.as_posix()}")
        if path.is_file():
            files.append(path)
    return sorted(files)


def audit() -> list[str]:
    failures: list[str] = []
    legacy_brand = ("vibe" + "fpga").lower()
    private_project_terms = (("gain" + "map").lower(), ("spi_" + "slave").lower())

    for name in BLOCKED_TOP_LEVEL:
        if (ROOT / name).exists():
            failures.append(f"blocked top-level path: {name}")

    for path in source_files():
        relative = path.relative_to(ROOT)
        if path.stat().st_size > MAX_FILE_BYTES:
            failures.append(f"file exceeds {MAX_FILE_BYTES} bytes: {relative.as_posix()}")
        if path.suffix.lower() in BLOCKED_SUFFIXES:
            failures.append(f"generated/binary artifact is not allowed: {relative.as_posix()}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"non-UTF-8 text file: {relative.as_posix()}")
            continue
        lowered = text.lower()
        if legacy_brand in lowered:
            failures.append(f"legacy private brand reference: {relative.as_posix()}")
        if any(term in lowered for term in private_project_terms):
            failures.append(f"private project reference: {relative.as_posix()}")
        for pattern in TEXT_BLOCKERS:
            if pattern.search(text):
                failures.append(f"local path or secret-like value: {relative.as_posix()}")
                break
    return sorted(set(failures))


def main() -> int:
    failures = audit()
    if failures:
        for failure in failures:
            print(f"BLOCKED: {failure}", file=sys.stderr)
        return 1
    print("PASS: public release tree contains only the allowed source profile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
