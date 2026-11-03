"""Read-only opt_design log scoping; preserve attribution and incomplete runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from scripts.evidence_contract import sha256_bytes


MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_RUNS = 32
MAX_EXCERPTS = 80
START = re.compile(r"^\s*Command:\s*opt_design(?:\s|$)")
COMMAND = re.compile(r"^\s*Command:\s*\S+")
END = re.compile(r"^\s*opt_design:\s*Time\b")
RELEVANT = re.compile(r"\[Opt 31-|^\s*Phase\s+\d+|DONT_TOUCH|MARK_DEBUG|CRITICAL WARNING|ERROR:", re.I)


def analyze_opt_log(root: Path, log_path: str) -> dict:
    root = root.resolve(strict=True)
    if not isinstance(log_path, str) or not log_path:
        raise ValueError("log_path must be a non-empty string")
    raw_path = Path(log_path)
    path = (raw_path if raw_path.is_absolute() else root / raw_path).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in {".log", ".txt"}:
        raise ValueError("log must be a .log/.txt file within the project root")
    with path.open("rb") as stream:
        raw = stream.read(MAX_LOG_BYTES + 1)
    if len(raw) > MAX_LOG_BYTES:
        raise ValueError("log exceeds the supported size limit")
    runs = []
    active = None
    for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if START.search(line):
            if len(runs) == MAX_RUNS:
                raise ValueError("too many opt_design runs; supply a bounded per-run log")
            active = {
                "start_line": number, "end_line": None, "command": line[:600],
                "complete": False, "completion_marker": False, "error_seen": False,
                "excerpts": [], "excerpts_truncated": False,
            }
            runs.append(active)
        elif COMMAND.search(line):
            # A different command closes the scope without certifying completion.
            active = None
        elif active is not None:
            if "opt_design completed successfully" in line:
                active["completion_marker"] = True
            if re.search(r"\bERROR:", line):
                active["error_seen"] = True
            if RELEVANT.search(line):
                if len(active["excerpts"]) < MAX_EXCERPTS:
                    active["excerpts"].append({"line": number, "text": line[:600], "text_truncated": len(line) > 600})
                else:
                    active["excerpts_truncated"] = True
            if END.search(line):
                active["end_line"] = number
                active["complete"] = True
                active = None
    return {
        "schema_version": 1,
        "status": "COLLECTED" if runs and all(run["complete"] for run in runs) else "BLOCKED",
        "acceptance": "NOT_EVALUATED", "source_binding": "UNVERIFIED", "hardware_validated": False,
        "log": {"path": path.relative_to(root).as_posix(), "sha256": sha256_bytes(raw), "size_bytes": len(raw)},
        "runs": runs,
        "reason": None if runs and all(run["complete"] for run in runs) else "missing or incomplete opt_design scope",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_path")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = analyze_opt_log(args.root, args.log_path)
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}))
        return 2
    print(json.dumps(result))
    return 0 if result["status"] == "COLLECTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
