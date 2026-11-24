"""Read-only, offline validation of an untrusted declared debug run plan."""
from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from scripts.debug_case_io import DebugDataError, confined_path, read_artifact, read_document, validate_schema
from scripts.evidence_contract import content_id, sha256_bytes

LIMITATIONS = [
    "Capture and collector are untrusted declarations, not authenticated observations.",
    "No fresh live state is verified; dates and sequence numbers do not prove freshness.",
    "No TOCTOU execution guarantee is provided; no hardware execution is authorized.",
    "Artifact checks cover the declared binding closure, not every package file.",
]


def _result(reasons, **ids):
    return {"scope": "offline_run_plan_validation", "offline_checks": "BLOCKED" if reasons else "PASS",
            "eligible_for_hardware": False, "live_state_verified": False,
            "execution_authorized": False, "hardware_validated": False,
            "reasons": reasons, "limitations": list(LIMITATIONS), **ids}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DebugDataError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_):
    raise DebugDataError("non-finite JSON number")


def _depth(value, depth=0):
    if depth > 32:
        raise DebugDataError("JSON nesting exceeds limit")
    if isinstance(value, dict):
        for item in value.values():
            _depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _depth(item, depth + 1)


def _capture(data):
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
        _depth(value)
        if not isinstance(value, dict):
            raise DebugDataError("capture must be an object")
        validate_schema(value, "debug_capture.schema.json")
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise DebugDataError("invalid capture JSON") from exc


def _safe_token(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise DebugDataError("invalid safe token")


def _plan_paths(plan):
    _safe_token(plan["attempt"])
    _safe_token(plan["bound_boot"])
    try:
        date.fromisoformat(plan["date"])
    except ValueError as exc:
        raise DebugDataError("date must be a real ISO calendar date") from exc
    suffix = plan["attempt"] + "-" + plan["date"]
    if plan["package_path"] != "packages/" + suffix or plan["evidence_path"] != "evidence/" + suffix:
        raise DebugDataError("package or evidence path does not match attempt and date")


def _artifacts(root, plan):
    for name in ("package_path", "evidence_path"):
        if not confined_path(root, plan[name]).is_dir():
            raise DebugDataError("declared directory is unavailable")
    if not plan["capture_path"].startswith(plan["evidence_path"] + "/"):
        raise DebugDataError("capture must be in evidence directory")
    entries = plan["artifacts"]
    paths = [entry["path"] for entry in entries]
    bindings = list(plan["bindings"].values())
    if len(paths) != len(set(paths)) or len(bindings) != len(set(bindings)):
        raise DebugDataError("artifact paths and role bindings must be unique")
    if not set(bindings).issubset(paths):
        raise DebugDataError("role binding is outside declared artifacts")
    if any(not path.startswith(plan["package_path"] + "/") for path in bindings):
        raise DebugDataError("role binding must be in package directory")
    hashes = {}
    remaining = 64 * 1024 * 1024
    for entry in entries:
        data = read_artifact(root, entry["path"], max_bytes=min(32 * 1024 * 1024, remaining))
        remaining -= len(data)
        actual = sha256_bytes(data)
        if actual != entry["sha256"]:
            raise DebugDataError("artifact digest mismatch: " + entry["path"])
        hashes[entry["path"]] = actual
    return hashes


def _check_capture(capture, plan, hashes):
    _safe_token(capture["boot_id"])
    _safe_token(capture["collector_id"])
    if any(type(capture[name]) is not int for name in ("sequence_start", "sequence_end")):
        raise DebugDataError("capture sequence must contain integers")
    for name in ("finalizer", "staging", "transport"):
        value = capture["checks"][name]
        if value is not None and type(value["entries"]) is not int:
            raise DebugDataError("capture entries must be integers")
    if capture["boot_id"] != plan["bound_boot"]:
        raise DebugDataError("capture boot mismatch")
    if capture["sequence_end"] < capture["sequence_start"]:
        raise DebugDataError("capture sequence is reversed")
    checks = capture["checks"]
    expected = {"persistent_marker": {"consumed": False}, "finalizer": {"entries": 0},
                "staging": {"entries": 0}, "transport": {"entries": 0},
                "trace": {"baseline_matches": True}, "services": {"restored": True},
                "image": {"sha256": hashes[plan["bindings"]["image"]]}}
    for name, value in expected.items():
        if checks[name] != value:
            raise DebugDataError("capture check is unknown or not ready: " + name)


def check_run_plan(root: Path, plan: dict) -> dict:
    try:
        validate_schema(plan, "debug_run_plan.schema.json")
        _plan_paths(plan)
        hashes = _artifacts(root, plan)
        data = read_artifact(root, plan["capture_path"], max_bytes=1024 * 1024)
        if sha256_bytes(data) != plan["capture_sha256"]:
            raise DebugDataError("capture digest mismatch")
        capture = _capture(data)
        _check_capture(capture, plan, hashes)
        return _result([], plan_id=content_id(plan, "plan_id"), capture_id=sha256_bytes(data))
    except DebugDataError as exc:
        return _result([str(exc)])
    except (OSError, ValueError):
        return _result(["Invalid or unsafe plan, artifact, or capture."])


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DebugDataError("invalid command line")


def main(argv=None):
    try:
        parser = _Parser(description=__doc__)
        parser.add_argument("--root", type=Path, required=True)
        parser.add_argument("--plan", type=Path, required=True)
        args = parser.parse_args(argv)
        result = check_run_plan(args.root, read_document(args.plan))
    except DebugDataError as exc:
        result = _result([str(exc)])
    except (OSError, ValueError):
        result = _result(["Invalid or unsafe CLI input."])
    print(json.dumps(result, sort_keys=True))
    return 0 if result["offline_checks"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
