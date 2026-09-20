#!/usr/bin/env python3
"""Verify deterministic Python syntax scope and the pinned Ruff governance contract."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUFF_VERSION = "0.14.1"


class PythonQualityError(ValueError):
    """Python quality scope or pinned Ruff policy drifted."""


def _content_id(value: dict) -> str:
    raw = json.dumps({key: item for key, item in value.items() if key != "evidence_id"},
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def validate(*, repository_root: Path = ROOT) -> dict:
    root = repository_root.resolve(strict=True)
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    lock = (root / "requirements-dev.lock").read_text(encoding="utf-8")
    workflow = (root / ".github/workflows/p0-fast-gates.yml").read_text(encoding="utf-8")
    if f'"ruff=={RUFF_VERSION}"' not in pyproject or f"ruff=={RUFF_VERSION}" not in lock:
        raise PythonQualityError("Ruff version is not pinned consistently")
    required_fragments = (
        'target-version = "py310"', "line-length = 110",
        'select = ["E4", "E7", "E9", "F"]', "python -m ruff check --no-cache",
    )
    if any(fragment not in pyproject + "\n" + workflow for fragment in required_fragments):
        raise PythonQualityError("Ruff policy or no-cache execution drifted")
    files = sorted(
        [path for path in (root / "scripts/quality_gate").glob("*.py")]
        + [path for path in (root / "tests").glob("test_rtl_*.py")]
    )
    if not 10 <= len(files) <= 128:
        raise PythonQualityError("Python quality scope count is outside the reviewed bound")
    hashes = {}
    for path in files:
        raw = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        try:
            ast.parse(raw, filename=relative)
        except SyntaxError as exc:
            raise PythonQualityError(f"Python syntax failed: {relative}") from exc
        hashes[relative] = hashlib.sha256(raw).hexdigest()
    report = {
        "schema_version": 1, "gate": "PYTHON_QUALITY_CONTRACT", "status": "PASS",
        "evidence_id": "", "syntax_files": len(files),
        "source_set_sha256": _content_id(hashes),
        "ruff": {"version": RUFF_VERSION, "execution": "PINNED_HOSTED_OR_PREINSTALLED"},
        "limitations": [
            "self-hosted job validates syntax and policy without dynamic installation",
            "Ruff findings require the pinned hosted environment or a preinstalled matching binary",
        ],
    }
    report["evidence_id"] = _content_id(report)
    return report


def main() -> int:
    try:
        report = validate()
    except (PythonQualityError, OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"gate": "PYTHON_QUALITY_CONTRACT", "status": "BLOCKED",
                          "reason_code": type(exc).__name__}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
