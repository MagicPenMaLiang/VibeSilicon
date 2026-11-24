"""Aggregate a pre-registered, blind benefit trial. Never declares benefit itself.

The score sheet is keyed only by opaque blind tokens and carries no arm label, so
a scorer cannot see which decision used the case catalog. This module joins the
pre-registered plan to the blind scores, enforces blinding/completeness/held-out
integrity, and mechanically tallies the rubric metrics per arm. It reports whether
the plan's pre-registered success condition is met as an arithmetic fact; it does
not assert that the feedback mechanism "works", rank any model, or authorize any
hardware action.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.debug_case_io import DebugDataError, read_document, validate_schema
from scripts.evidence_contract import content_id

ROOT = Path(__file__).resolve().parents[1]
METRICS = ("m1", "m2", "m3", "m4", "m5")
IMPROVABLE = ("m1", "m2", "m4", "m5")
ARMS = ("control", "treatment")


def _index_plan(plan: dict) -> dict:
    tokens: dict[str, dict] = {}
    pairs: dict[str, set[str]] = {}
    for decision in plan["decisions"]:
        token = decision["blind_token"]
        if token in tokens:
            raise DebugDataError("duplicate blind token in plan")
        tokens[token] = decision
        pairs.setdefault(decision["pair_id"], set()).add(decision["arm"])
    for arms in pairs.values():
        if arms != {"control", "treatment"}:
            raise DebugDataError("each pair_id must have exactly one control and one treatment")
    if not any(decision["held_out"] for decision in plan["decisions"]):
        raise DebugDataError("plan declares no held-out decisions")
    return tokens


def _index_scores(scores: dict, tokens: dict) -> dict:
    scored: dict[str, dict] = {}
    for row in scores["scores"]:
        token = row["blind_token"]
        if token in scored:
            raise DebugDataError("duplicate blind token in scores")
        if token not in tokens:
            raise DebugDataError("score references an unknown blind token")
        scored[token] = row
    if set(scored) != set(tokens):
        raise DebugDataError("every planned decision must be scored exactly once")
    return scored


def _tally(tokens: dict, scored: dict, held_out_only: bool) -> dict:
    counts = {arm: {"n": 0, **{metric: 0 for metric in METRICS},
                    "g1_abstained": 0, "g2_misapplied": 0} for arm in ARMS}
    for token, decision in tokens.items():
        if held_out_only and not decision["held_out"]:
            continue
        arm = counts[decision["arm"]]
        row = scored[token]
        arm["n"] += 1
        for metric in METRICS:
            arm[metric] += int(row[metric])
        arm["g1_abstained"] += int(row["g1_abstained_when_underspecified"])
        arm["g2_misapplied"] += int(row["g2_misapplied"])
    return counts


def _rate(counts: dict) -> dict:
    out = {}
    for arm, data in counts.items():
        total = data["n"]
        out[arm] = {"n": total}
        for key in (*METRICS, "g1_abstained", "g2_misapplied"):
            out[arm][key] = None if total == 0 else data[key] / total
    return out


def _success(plan: dict, held_out: dict) -> dict:
    """Mechanically test the pre-registered condition. Arithmetic, not a benefit verdict."""
    condition = plan["success_condition"]
    control, treatment = held_out["control"], held_out["treatment"]
    reasons = []
    if control["n"] < condition["min_pairs"] or treatment["n"] < condition["min_pairs"]:
        reasons.append("fewer held-out decisions per arm than pre-registered minimum")
    if treatment["m3"] != condition["max_overreach"]:
        reasons.append("treatment authorization-overreach rate exceeds the pre-registered maximum")
    for metric in condition["improved_metrics"]:
        c, t = control[metric], treatment[metric]
        if c is None or t is None or not t < c:
            reasons.append(f"{metric} not strictly lower in treatment")
    for arm in (control, treatment):
        if arm["g2_misapplied"] != 0:
            reasons.append("case-misapplication guard regressed")
    if condition["require_g1_non_regression"] and treatment["g1_abstained"] < control["g1_abstained"]:
        reasons.append("abstention guard regressed: treatment abstains less under missing context")
    return {"pre_registered_condition_met": not reasons, "unmet_reasons": sorted(set(reasons))}


def aggregate_trial(plan: dict, scores: dict) -> dict:
    validate_schema(plan, "debug_trial_plan.schema.json")
    validate_schema(scores, "debug_trial_scores.schema.json")
    if plan["trial_id"] != scores["trial_id"]:
        raise DebugDataError("plan and scores trial_id disagree")
    tokens = _index_plan(plan)
    scored = _index_scores(scores, tokens)
    all_rates = _rate(_tally(tokens, scored, held_out_only=False))
    held_out_counts = _tally(tokens, scored, held_out_only=True)
    held_out_rates = _rate(held_out_counts)
    if held_out_rates["control"]["n"] == 0 or held_out_rates["treatment"]["n"] == 0:
        raise DebugDataError("held-out analysis needs both arms represented")
    success = _success(plan, held_out_rates)
    return {
        "report_kind": "offline_blind_trial_tally",
        "trial_id": plan["trial_id"],
        "plan_id": content_id(plan, "plan_id"),
        "scores_id": content_id(scores, "scores_id"),
        "all_decisions": all_rates,
        "held_out": held_out_rates,
        **success,
        "benefit_claimed_by_tool": False,
        "model_evaluation_performed": False,
        "hardware_validated": False,
        "execution_authorized": False,
        "limitations": [
            "This is an arithmetic tally of independently supplied blind scores.",
            "A met condition is evidence for the pre-registered hypothesis, not a tool-issued benefit verdict or a causal proof.",
            "Scoring quality, decision sampling and blinding integrity are human responsibilities outside this tool.",
            "No raw hardware evidence was replayed and no board was accessed.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--scores", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = aggregate_trial(read_document(args.plan), read_document(args.scores))
    except (DebugDataError, OSError, ValueError) as error:
        print(json.dumps({"report_kind": "offline_blind_trial_tally", "status": "INVALID",
                          "error": str(error), "benefit_claimed_by_tool": False}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0 if report["pre_registered_condition_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
