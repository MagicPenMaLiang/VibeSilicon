"""Replay fixed synthetic retrieval expectations; never evaluate a model or board."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.debug_case_io import DebugDataError, read_document, validate_schema
from scripts.debug_cases import load_catalog, query_contexts, validate_cases
from scripts.evidence_contract import content_id

ROOT = Path(__file__).resolve().parents[1]
GROUPS = ("matched", "needs_context", "excluded")


def _validate_labels(cases: list[dict], scenarios: list[dict]) -> None:
    known = {case["case_id"] for case in cases}
    ids = [scenario["id"] for scenario in scenarios]
    if len(set(ids)) != len(ids):
        raise DebugDataError("duplicate scenario IDs")
    for scenario in scenarios:
        labels = [label for group in GROUPS for label in scenario["expected"][group]]
        if len(labels) != len(set(labels)) or set(labels) != known:
            raise DebugDataError("scenario labels must partition the complete catalog")


def _replay(query: dict, scenario: dict) -> dict:
    actual = {group: sorted(row["case_id"] for row in query[group]) for group in GROUPS}
    expected = {group: sorted(scenario["expected"][group]) for group in GROUPS}
    return {
        "id": scenario["id"], "passed": actual == expected,
        "expected": expected, "actual": actual,
    }


def _scope() -> dict:
    return {
        "evaluation_kind": "deterministic_offline_contract", "synthetic": True,
        "model_evaluation_performed": False, "hardware_validated": False,
        "execution_authorized": False,
    }


def evaluate_scenarios(cases: list[dict], document: dict) -> dict:
    """Compare independently declared partitions; do not change cases or labels."""
    validate_cases(cases)
    validate_schema(document, "debug_scenarios.schema.json")
    _validate_labels(cases, document["scenarios"])
    queries = query_contexts(cases, [scenario["context"] for scenario in document["scenarios"]])
    results = [_replay(query, scenario) for query, scenario in zip(queries, document["scenarios"])]
    passed = sum(row["passed"] for row in results)
    return {
        **_scope(), "status": "PASS" if passed == len(results) else "FAIL",
        "catalog_id": content_id({"cases": sorted(cases, key=lambda case: case["case_id"])}, "id"),
        "scenario_set_id": content_id(document, "id"),
        "total": len(results), "passed": passed, "results": results,
        "limitations": [
            "Only fixed synthetic retrieval partitions were checked.",
            "No primary hardware evidence was replayed or authenticated.",
            "These public scenarios are not a blinded model holdout or a causal diagnosis grader.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "knowledge/fpga-video/cases")
    parser.add_argument("--scenarios", type=Path,
                        default=ROOT / "knowledge/fpga-video/evaluation/scenarios.json")
    args = parser.parse_args(argv)
    try:
        report = evaluate_scenarios(load_catalog(args.catalog), read_document(args.scenarios))
    except (DebugDataError, OSError, ValueError) as error:
        report = {**_scope(), "status": "INVALID", "error": str(error)}
        print(json.dumps(report, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
