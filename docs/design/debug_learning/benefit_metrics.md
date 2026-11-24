# Feedback mechanism: benefit metrics and acceptance definition

Status: draft for human approval, 2026-11-10. This defines how to judge whether
the conditional-case feedback mechanism helps real bring-up work. It is a
measurement contract, not a claim that benefit has been shown. Nothing here
authorizes a board run, relaxes a gate, or promotes a case.

## Why this document exists

A passing scenario evaluation (`debug_learning_eval`) proves only that retrieval
matches, excludes and abstains as declared. It does not show that the cases
improve decisions. "The mechanism helps" must be restated as measurable outcomes
before any trial, or the trial will neither confirm nor refute anything.

## Unit of measurement: the diagnostic decision

The measured unit is a single **diagnostic decision** during bring-up: given the
latest result and its bound records, an agent (or engineer) states the failing
layer, the next discriminating experiment, and the stop/authorization decision.
We do not measure whole sessions, version counts, or "runs" — a prehardware stop
is not a hardware trial, and more run IDs are not progress.

## Primary metrics

Each decision is scored by an independent reviewer against the retrospective's
own standard of separating first failure, protective stop and hypothesized root
cause. Lower is better for all error metrics.

| ID | Metric | Definition | Target direction |
|---|---|---|---|
| M1 | Premature root-cause rate | Fraction of decisions asserting a settled root cause that the evidence does not yet support (a reversed/withdrawn explanation stated as fact). | Decrease |
| M2 | Layer-misattribution rate | Fraction of decisions that assign the failure to the wrong dimension (pixels/protocol, deadlines, harness, evidence, recovery, physical sink). | Decrease |
| M3 | Authorization-overreach count | Count of decisions that treat an offline/internal/host-side result as live readiness, execution authorization or hardware validation. | Drive to zero |
| M4 | Missing-counterevidence rate | Fraction of decisions that apply a historical fact without stating the condition that limits its transfer to the current environment. | Decrease |
| M5 | Wasted-experiment rate | Fraction of proposed expensive experiments that do not distinguish between the stated competing hypotheses. | Decrease |

A single authorization overreach (M3 > 0) is a blocking defect regardless of the
other metrics; the mechanism must never make overreach more likely.

## Secondary / guard metrics

| ID | Metric | Purpose |
|---|---|---|
| G1 | Retrieval abstention rate | The mechanism should say "needs context" rather than force a match; a low abstention rate under missing context is a regression. |
| G2 | Case-misapplication count | Times a matched case was applied despite an unmet required condition or a matching exclusion — must be zero. |
| G3 | Added latency per decision | The mechanism must not materially slow a decision; measured but not optimized at this stage. |

## Comparison design (for a later, separately approved trial)

To attribute any change to the mechanism rather than to the engineer, model or
luck, a trial must contrast two arms on the **same** decision inputs:

- Arm A (control): decision made without consulting the case catalog.
- Arm B (treatment): decision made after a documented catalog query.

Required controls, none implemented here:

1. **Held-out decisions.** Score decisions whose underlying history is not among
   the cases, so the mechanism cannot win by memorizing its own source records.
2. **Blind scoring.** The reviewer scoring M1–M5 must not know which arm produced
   a decision.
3. **No self-grading.** The agent that made a decision never scores its own
   decision; the catalog's own PASS/structural validity is not evidence of benefit.
4. **Pre-registered expectations.** Scenario/label partitions and scoring rubric
   are fixed before the trial, not adjusted to produce a favorable result.

## What would count as evidence of benefit

Benefit is shown only if, across a pre-registered set of held-out decisions with
blind scoring, Arm B (treatment) shows a reviewer-confirmed strict reduction in
**every** metric the plan pre-registers in `improved_metrics` (a conjunction: the
aggregator requires all listed metrics to improve, not just one), with M3 held at
the pre-registered maximum of zero in treatment and G1/G2 not regressing. The
plan must set `require_g1_non_regression` to encode the G1 guard; the aggregator
then blocks a "met" result if treatment abstains less than control under missing
context. Absent all of this, the honest conclusion is "not shown," not "no
benefit" and not "benefit."

The aggregator reports whether this pre-registered condition is met as an
arithmetic fact. `pre_registered_condition_met: true` (CLI exit 0) means the
numbers clear the pre-registered bar; it is not a tool-issued proof that the
mechanism works, and the tool never sets a benefit flag.

## Explicit non-claims

This document does not rank language models, does not establish any current
hardware finding, and does not define a pass/fail gate for the board. The trial
it describes is deferred and separately approved. The cases remain
`REVIEW_REQUIRED` until independent review promotes them; measuring benefit
assumes that review has first confirmed the cases are faithful to their sources.

## Related documents

- [Requirements](PRD.md)
- [Verification and limitations](verification.md)
- [Bring-up retrospective](../../reviews/kv260_video_bringup_retrospective_20261110.md)
- [Case catalog and semantics](../../../knowledge/fpga-video/README.md)
