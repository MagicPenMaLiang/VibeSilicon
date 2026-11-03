"""Audit publishable Git candidates or a source export, optionally preparing a snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache"}
SOURCE_DIRS = {
    ".agents", ".claude", ".codex", ".github", ".opencode", "config", "docs", "examples",
    "mcp", "schemas", "scripts", "skills", "subagents", "templates", "tests", "third_party",
}
SOURCE_FILES = {
    ".gitattributes", ".gitignore", ".mcp.json", "AGENTS.md", "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md", "LICENSE", "README.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md",
    "opencode.json", "pyproject.toml", "requirements.lock", "requirements-dev.lock",
}
BLOCKED_SUFFIXES = {
    ".bit", ".dcp", ".dmp", ".gds", ".jou", ".log", ".ltx", ".pb", ".spef", ".str",
    ".tar", ".wdb", ".zip", ".xpr", ".vcd", ".fst", ".pyc", ".pyo",
}
MAX_FILE_BYTES = 2 * 1024 * 1024
TEXT_SUFFIXES = {
    "", ".bat", ".cfg", ".cpp", ".h", ".json", ".md", ".ps1", ".py", ".sv", ".svh",
    ".tcl", ".toml", ".tpl", ".template", ".txt", ".v", ".yaml", ".yml", ".sh", ".js", ".cmd",
    ".lock", ".rpt", ".sdc", ".xdc", ".c",
}
TEXT_BLOCKERS = (
    re.compile(r"(?i)(?:^|[\s=\"'])(?:[A-Z]:[\\/](?![^\s]*<)|/(?:home|Users)/[^/\s]+)"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*[\"'][^\"']+[\"']"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def source_files(root: Path = ROOT) -> list[Path]:
    """Use Git's publish candidates without traversing ignored local design trees."""
    root = root.resolve(strict=True)
    if (root / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True, check=False, timeout=30,
        )
        if result.returncode:
            raise ValueError("cannot enumerate Git release candidates")
        names = {item.decode("utf-8") for item in result.stdout.split(b"\0") if item}
        paths = []
        for name in sorted(names):
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Git candidate escapes repository")
            path = root / relative
            # A tracked deletion is a proposed removal, not a file to export.
            if not os.path.lexists(path):
                continue
            paths.append(path)
        return paths
    files = []
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=_walk_error):
        base = Path(directory)
        for name in list(dirs):
            path = base / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_reparse_tag", 0):
                raise ValueError(f"symbolic directory is not allowed: {path.relative_to(root).as_posix()}")
            if name in SKIP_DIRS:
                dirs.remove(name)
        files.extend(base / name for name in names)
    return sorted(files)


def _walk_error(error: OSError) -> None:
    raise error


def _public_path(relative: Path) -> bool:
    if len(relative.parts) == 1:
        return relative.name in SOURCE_FILES
    if relative.parts[0] not in SOURCE_DIRS or any(part in SKIP_DIRS for part in relative.parts):
        return False
    if relative.parts[0] in {".agents", ".claude", ".codex", ".opencode"}:
        allowed = {
            ".agents": {"skills"}, ".claude": {"skills", "agents", "settings.json"},
            ".codex": {"agents", "config.toml", "hooks.json"}, ".opencode": {"plugins"},
        }[relative.parts[0]]
        return relative.parts[1] in allowed and not relative.name.endswith(".local.json")
    return True


def audit(root: Path = ROOT) -> list[str]:
    root = root.resolve(strict=True)
    failures: list[str] = []
    legacy_brand = ("vibe" + "fpga").lower()
    private_project_terms = (("gain" + "map").lower(), ("spi_" + "slave").lower())

    try:
        candidates = source_files(root)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError) as exc:
        return [f"cannot enumerate release source: {type(exc).__name__}"]
    if not candidates:
        return ["no public source files found"]
    for path in candidates:
        relative = path.relative_to(root)
        if not _public_path(relative):
            failures.append(f"path outside public source profile: {relative.as_posix()}")
        try:
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_reparse_tag", 0):
                failures.append(f"linked/reparse file is not allowed: {relative.as_posix()}")
                continue
            if not stat.S_ISREG(metadata.st_mode) or not path.resolve().is_relative_to(root):
                failures.append(f"not a regular source file: {relative.as_posix()}")
                continue
        except OSError:
            failures.append(f"cannot inspect source file: {relative.as_posix()}")
            continue
        if metadata.st_size > MAX_FILE_BYTES:
            failures.append(f"file exceeds {MAX_FILE_BYTES} bytes: {relative.as_posix()}")
            continue
        if path.suffix.lower() in BLOCKED_SUFFIXES:
            failures.append(f"generated/binary artifact is not allowed: {relative.as_posix()}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            failures.append(f"unsupported public file type: {relative.as_posix()}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            failures.append(f"unreadable or non-UTF-8 text file: {relative.as_posix()}")
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


def prepare_snapshot(root: Path, output: Path) -> dict:
    """Copy audited bytes without changing the Git index or any source file."""
    root = root.resolve(strict=True)
    output = (root / output).resolve()
    if not output.is_relative_to(root / ".vibesilicon") or output == root / ".vibesilicon":
        raise ValueError("snapshot output must be a new directory below .vibesilicon")
    if output.exists():
        raise ValueError("refusing to overwrite an existing release snapshot")
    failures = audit(root)
    if failures:
        raise ValueError("source audit must pass before snapshot preparation")
    # Freeze the bytes and hashes before creating the destination.
    sources = {path.relative_to(root).as_posix(): path.read_bytes() for path in source_files(root)}
    manifest = {"schema_version": 1, "files": [
        {"path": name, "bytes": len(data), "sha256": "sha256:" + hashlib.sha256(data).hexdigest()}
        for name, data in sorted(sources.items())
    ]}
    manifest["manifest_id"] = "sha256:" + hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    output.mkdir(parents=True)
    for name, data in sources.items():
        path = output / "source" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        # Preserve executable bits for shell wrappers in a Linux checkout.
        path.chmod((root / name).stat().st_mode & 0o777)
    if audit(output / "source"):
        raise ValueError("prepared snapshot failed its independent source-tree audit")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--prepare", type=Path, help="new snapshot directory below .vibesilicon")
    args = parser.parse_args()
    try:
        root = args.root.resolve(strict=True)
        failures = audit(root)
        manifest = prepare_snapshot(root, args.prepare) if args.prepare and not failures else None
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        failures, manifest = [str(exc)], None
    if args.json:
        print(json.dumps({"status": "FAIL" if failures else "PASS", "failures": failures,
                          "snapshot_manifest_id": manifest["manifest_id"] if manifest else None}))
        return 1 if failures else 0
    if failures:
        for failure in failures:
            print(f"BLOCKED: {failure}", file=sys.stderr)
        return 1
    print("PASS: public release tree contains only the allowed source profile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
