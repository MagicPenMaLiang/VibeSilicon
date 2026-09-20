#!/usr/bin/env python3
"""Evidence-bound FPGA optimization experiment and snapshot rollback state machine."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
EXPERIMENT_RE = re.compile(r"^OPT-[A-Za-z0-9][A-Za-z0-9-]{2,63}$")
EVIDENCE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OPERATORS = {">=", "<=", ">", "<", "=="}


class ExperimentError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", delete=False
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def _inside(root: Path, raw: str | Path, *, must_exist: bool = True) -> Path:
    candidate = Path(raw)
    path = (candidate if candidate.is_absolute() else root / candidate).resolve(strict=must_exist)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ExperimentError(f"experiment path is outside project root: {path}") from exc
    if must_exist and (not path.is_file() or path.is_symlink()):
        raise ExperimentError(f"experiment input must be a regular non-symlink file: {path}")
    return path


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExperimentError(f"{label} must be numeric")
    return float(value)


def validate_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version", "experiment_id", "hypothesis", "baseline", "objectives",
        "guardrails", "non_regression", "invariants", "files", "required_gates",
        "max_iterations", "auto_rollback",
    }
    unknown = set(spec) - (required | {"min_improvement"})
    missing = required - set(spec)
    if missing or unknown:
        raise ExperimentError(f"experiment spec fields missing={sorted(missing)} unknown={sorted(unknown)}")
    if spec["schema_version"] != SCHEMA_VERSION:
        raise ExperimentError("unsupported experiment schema_version")
    experiment_id = spec["experiment_id"]
    if not isinstance(experiment_id, str) or not EXPERIMENT_RE.fullmatch(experiment_id):
        raise ExperimentError("experiment_id must match OPT-<id>")
    if not isinstance(spec["hypothesis"], str) or not spec["hypothesis"].strip():
        raise ExperimentError("hypothesis must be non-empty")
    baseline = spec["baseline"]
    if not isinstance(baseline, Mapping) or set(baseline) != {"evidence_id", "metrics"}:
        raise ExperimentError("baseline must contain exactly evidence_id and metrics")
    if not isinstance(baseline["evidence_id"], str) or not EVIDENCE_RE.fullmatch(baseline["evidence_id"]):
        raise ExperimentError("baseline evidence_id must be content-addressed")
    if not isinstance(baseline["metrics"], Mapping) or not baseline["metrics"]:
        raise ExperimentError("baseline metrics must be a non-empty object")
    for name, value in baseline["metrics"].items():
        _number(value, f"baseline metric {name}")
    for field in ("objectives", "guardrails", "non_regression"):
        if not isinstance(spec[field], list) or not spec[field]:
            raise ExperimentError(f"{field} must be a non-empty list")
    baseline_metric_names = set(baseline["metrics"])
    for objective in spec["objectives"]:
        if not isinstance(objective, Mapping) or set(objective) != {"metric", "operator", "value"}:
            raise ExperimentError("each objective requires metric/operator/value")
        if objective["operator"] not in OPERATORS:
            raise ExperimentError(f"unsupported objective operator: {objective['operator']}")
        if not isinstance(objective["metric"], str) or objective["metric"] not in baseline_metric_names:
            raise ExperimentError("objective metric must exist in baseline metrics")
        _number(objective["value"], "objective value")
    for guardrail in spec["guardrails"]:
        if not isinstance(guardrail, Mapping) or set(guardrail) != {"metric", "max_delta_pct"}:
            raise ExperimentError("each guardrail requires metric/max_delta_pct")
        if not isinstance(guardrail["metric"], str) or guardrail["metric"] not in baseline_metric_names:
            raise ExperimentError("guardrail metric must exist in baseline metrics")
        if _number(guardrail["max_delta_pct"], "guardrail max_delta_pct") < 0:
            raise ExperimentError("guardrail max_delta_pct must be non-negative")
    for item in spec["non_regression"]:
        if not isinstance(item, Mapping) or set(item) != {"metric", "direction"}:
            raise ExperimentError("each non_regression item requires metric/direction")
        if item["direction"] not in {"higher", "lower"}:
            raise ExperimentError("non_regression direction must be higher or lower")
        if not isinstance(item["metric"], str) or item["metric"] not in baseline_metric_names:
            raise ExperimentError("non_regression metric must exist in baseline metrics")
    for field in ("invariants", "files", "required_gates"):
        values = spec[field]
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
            raise ExperimentError(f"{field} must be a non-empty string list")
        if len(values) != len(set(values)):
            raise ExperimentError(f"{field} contains duplicates")
    if isinstance(spec["max_iterations"], bool) or not isinstance(spec["max_iterations"], int):
        raise ExperimentError("max_iterations must be an integer")
    if not 1 <= spec["max_iterations"] <= 3:
        raise ExperimentError("max_iterations must be between 1 and 3")
    if spec["auto_rollback"] is not True:
        raise ExperimentError("v1 requires auto_rollback=true")
    if "min_improvement" in spec:
        improvement = spec["min_improvement"]
        if not isinstance(improvement, Mapping) or set(improvement) != {"metric", "absolute"}:
            raise ExperimentError("min_improvement requires metric/absolute")
        if improvement["metric"] not in baseline_metric_names:
            raise ExperimentError("min_improvement metric must exist in baseline metrics")
        if _number(improvement["absolute"], "min_improvement absolute") < 0:
            raise ExperimentError("min_improvement absolute must be non-negative")
    return json.loads(json.dumps(spec))


def _experiment_dir(root: Path, experiment_id: str) -> Path:
    if not EXPERIMENT_RE.fullmatch(experiment_id):
        raise ExperimentError("invalid experiment_id")
    return root / ".vibesilicon" / "optimization" / experiment_id


def start_experiment(root: Path, spec_value: Mapping[str, Any]) -> dict[str, Any]:
    resolved_root = root.resolve(strict=True)
    spec = validate_spec(spec_value)
    directory = _experiment_dir(resolved_root, spec["experiment_id"])
    if directory.exists():
        raise ExperimentError(f"experiment already exists: {spec['experiment_id']}")
    sources: list[tuple[Path, Path]] = []
    for raw in spec["files"]:
        source = _inside(resolved_root, raw)
        sources.append((source, source.relative_to(resolved_root)))
    files: list[dict[str, Any]] = []
    for source, relative in sources:
        snapshot = directory / "baseline" / relative
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, snapshot)
        files.append({"path": relative.as_posix(), "sha256": _sha256(source)})
    state = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": spec["experiment_id"],
        "status": "ACTIVE",
        "iteration": 0,
        "started_at": _now(),
        "updated_at": _now(),
        "spec": spec,
        "baseline_manifest": files,
        "last_metrics": dict(spec["baseline"]["metrics"]),
        "stagnant_iterations": 0,
        "history": [],
    }
    _write_json(directory / "state.json", state)
    return state


def _compare(actual: float, operator: str, expected: float) -> bool:
    return {
        ">=": actual >= expected,
        "<=": actual <= expected,
        ">": actual > expected,
        "<": actual < expected,
        "==": actual == expected,
    }[operator]


def _load_state(root: Path, experiment_id: str) -> tuple[Path, dict[str, Any]]:
    directory = _experiment_dir(root.resolve(strict=True), experiment_id)
    path = directory / "state.json"
    if not path.is_file():
        raise ExperimentError(f"experiment state not found: {experiment_id}")
    return directory, json.loads(path.read_text(encoding="utf-8"))


def _restore(root: Path, directory: Path, state: Mapping[str, Any]) -> list[str]:
    restored: list[str] = []
    for record in state["baseline_manifest"]:
        destination = _inside(root, record["path"], must_exist=False)
        if destination.relative_to(root).as_posix() != record["path"]:
            raise ExperimentError(f"rollback path was redirected: {record['path']}")
        if destination.exists() and (not destination.is_file() or destination.is_symlink()):
            raise ExperimentError(f"rollback destination is not a regular file: {record['path']}")
        if not destination.parent.is_dir():
            raise ExperimentError(f"rollback parent directory is missing: {record['path']}")
        snapshot = _inside(directory, directory / "baseline" / record["path"])
        if _sha256(snapshot) != record["sha256"]:
            raise ExperimentError(f"baseline snapshot hash mismatch: {record['path']}")
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
        shutil.copy2(snapshot, temporary)
        os.replace(temporary, destination)
        restored.append(record["path"])
    return restored


def evaluate_experiment(
    root: Path, experiment_id: str, result: Mapping[str, Any]
) -> dict[str, Any]:
    resolved_root = root.resolve(strict=True)
    directory, state = _load_state(resolved_root, experiment_id)
    if state["status"] != "ACTIVE":
        raise ExperimentError(f"experiment is not ACTIVE: {state['status']}")
    required_result = {"schema_version", "evidence_id", "metrics", "invariants", "gates"}
    if set(result) != required_result or result.get("schema_version") != SCHEMA_VERSION:
        raise ExperimentError("result must contain schema_version/evidence_id/metrics/invariants/gates")
    if not isinstance(result["evidence_id"], str) or not EVIDENCE_RE.fullmatch(result["evidence_id"]):
        raise ExperimentError("result evidence_id must be content-addressed")
    metrics = result["metrics"]
    invariants = result["invariants"]
    gates = result["gates"]
    if not all(isinstance(value, Mapping) for value in (metrics, invariants, gates)):
        raise ExperimentError("result metrics/invariants/gates must be objects")
    spec = state["spec"]
    reasons: list[str] = []
    required_metrics = {
        item["metric"] for field in ("objectives", "guardrails", "non_regression")
        for item in spec[field]
    }
    missing_metrics = sorted(required_metrics - set(metrics))
    if missing_metrics:
        reasons.append(f"missing_metrics:{','.join(missing_metrics)}")
    valid_metrics: dict[str, float] = {}
    for name in sorted(required_metrics & set(metrics)):
        try:
            valid_metrics[name] = _number(metrics[name], f"result {name}")
        except ExperimentError:
            reasons.append(f"invalid_metric:{name}")
    for name in spec["invariants"]:
        if invariants.get(name) is not True:
            reasons.append(f"invariant_failed:{name}")
    for name in spec["required_gates"]:
        if gates.get(name) != "PASS":
            reasons.append(f"gate_not_pass:{name}")
    baseline_metrics = spec["baseline"]["metrics"]
    for item in spec["guardrails"]:
        name = item["metric"]
        if name not in valid_metrics or name not in baseline_metrics:
            continue
        baseline = _number(baseline_metrics[name], f"baseline {name}")
        actual = valid_metrics[name]
        delta = 0.0 if baseline == actual == 0 else float("inf") if baseline == 0 else (
            (actual - baseline) / abs(baseline) * 100.0
        )
        if delta > _number(item["max_delta_pct"], f"guardrail {name}"):
            reasons.append(f"guardrail_exceeded:{name}")
    for item in spec["non_regression"]:
        name = item["metric"]
        if name not in valid_metrics or name not in baseline_metrics:
            continue
        actual = valid_metrics[name]
        baseline = _number(baseline_metrics[name], f"baseline {name}")
        if (item["direction"] == "higher" and actual < baseline) or (
            item["direction"] == "lower" and actual > baseline
        ):
            reasons.append(f"regression:{name}")
    objectives_met = not missing_metrics and not any(
        reason.startswith("invalid_metric:") for reason in reasons
    ) and all(
        _compare(
            valid_metrics[item["metric"]],
            item["operator"],
            _number(item["value"], f"objective {item['metric']}"),
        )
        for item in spec["objectives"]
    )
    state["iteration"] += 1
    if "min_improvement" in spec:
        item = spec["min_improvement"]
        name = item["metric"]
        if name in valid_metrics and name in state["last_metrics"]:
            improvement = abs(valid_metrics[name] - _number(state["last_metrics"][name], name))
            state["stagnant_iterations"] = (
                state["stagnant_iterations"] + 1
                if improvement < _number(item["absolute"], "min improvement") else 0
            )
            if state["stagnant_iterations"] >= 2:
                reasons.append(f"stagnant:{name}")
    if not reasons and objectives_met:
        decision = "ACCEPT"
        state["status"] = "ACCEPTED"
    elif reasons or state["iteration"] >= spec["max_iterations"]:
        if not reasons:
            reasons.append("max_iterations_without_target")
        decision = "ROLLBACK"
        state["status"] = "ROLLBACK_REQUIRED"
    else:
        decision = "CONTINUE"
    restored: list[str] = []
    if decision == "ROLLBACK" and spec["auto_rollback"]:
        restored = _restore(resolved_root, directory, state)
        state["status"] = "ROLLED_BACK"
    state["last_metrics"] = dict(metrics)
    state["updated_at"] = _now()
    state["history"].append(
        {
            "iteration": state["iteration"],
            "evidence_id": result["evidence_id"],
            "decision": decision,
            "reasons": reasons,
            "restored": restored,
            "at": state["updated_at"],
        }
    )
    _write_json(directory / "state.json", state)
    return state


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    start_parser = subparsers.add_parser("start")
    start_parser.add_argument("spec", type=Path)
    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("experiment_id")
    evaluate_parser.add_argument("result", type=Path)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("experiment_id")
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            output = start_experiment(args.root, json.loads(args.spec.read_text(encoding="utf-8")))
        elif args.command == "evaluate":
            output = evaluate_experiment(
                args.root, args.experiment_id, json.loads(args.result.read_text(encoding="utf-8"))
            )
        else:
            _, output = _load_state(args.root.resolve(strict=True), args.experiment_id)
    except (OSError, json.JSONDecodeError, ExperimentError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["status"] not in {"ROLLBACK_REQUIRED", "ROLLED_BACK"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
