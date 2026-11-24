# Blind benefit trial — KV260 LUT3D video path (pre-registered 2026-11-10)

This is a **real** pre-registered trial of the conditional-case feedback mechanism,
run per [`benefit_metrics.md`](../../docs/design/debug_learning/benefit_metrics.md).
It is an offline study of diagnostic-decision quality. It accesses no board, runs
no model A/B automatically, and proves no hardware finding.

## Roles (fixed before scoring)

- **Decision author (assistant):** generated the treatment arm of every pair and
  the control arm of the two **non-held-out** pairs only. The author does **not**
  score and does **not** write any held-out control arm.
- **Independent control author (separate person):** writes the control arm for the
  four **held-out** pairs from `control_authoring_worksheet.md`, cold, without
  reading the treatment arms. This removes the single-author bias on the decisions
  that decide success. Does not score.
- **Trial custodian (James):** pastes each independent control decision into
  `decisions.blind.json` at its token; keeps `plan.json` and the worksheet sealed
  from the scorer.
- **Independent scorer (James arranges):** reads the completed `decisions.blind.json`,
  scores each token in a copy of `scores.template.json`, and must not have authored
  any decision. The scorer is **not** given `plan.json` or the worksheet.
- **Aggregator (tool):** `scripts/debug_trial_eval.py` joins plan + scores,
  enforces blinding/pairing/held-out/coverage, and reports whether the
  pre-registered condition is met arithmetically. It never claims benefit.

## Pre-registration

- `plan.json` fixes, before any score exists: the six pairs, each decision's arm,
  its held-out status, and its opaque `blind_token`; and the success condition
  `improved_metrics=[m1,m4]`, `max_overreach=0`, `min_pairs=3`,
  `require_g1_non_regression=true`.
- Success requires, **on held-out decisions only**, a strict reduction in **both**
  M1 (premature root cause) and M4 (missing counterevidence) in treatment vs
  control, with zero M3 overreach in treatment and no G1/G2 regression. Any one of
  these failing yields "not shown," which is an honest outcome, not a defect.

## Arms

- **control** = a competent decision made **without** consulting the case catalog.
- **treatment** = a decision made **after** a documented catalog query.

## Held-out design and its limit

The seven promoted cases were distilled from the bring-up retrospective, so a trial
scored on case-covered topics could "win" by regurgitating its own sources. To
avoid that:

- Pairs **p1 (nv12-rgbx)** and **p2 (observer-scope)** are marked **not held-out**:
  their topics are directly covered by a case. They are included for context and
  are **excluded** from the success computation by the aggregator.
- Pairs **p3 (throughput), p4 (geometry), p5 (single-bank), p6 (eos-ownership)**
  are **held-out**: these retrospective topics were deliberately **not** distilled
  into any case. On these, the catalog returns no applicable case, so treatment can
  only help through disciplined **abstention** (G1) and first-principles reasoning,
  never by memorizing a case. This makes the held-out arms the sharpest, fairest
  test of the mechanism and is why they alone decide success.

## Honest limitations (these bound what a "met" result means)

1. **Single-author bias (mitigated).** The four held-out control arms — the only
   ones that decide success — are written by an **independent** author who does not
   see the treatment arms (`control_authoring_worksheet.md`), so arm construction on
   the deciding decisions is no longer single-author. The treatment arms and the two
   non-held-out (context, excluded) control arms remain assistant-authored. The
   scorer is still asked to flag any decision that reads as a strawman.
2. **Small N.** Four held-out pairs is a pilot, not a powered study. Treat a met
   result as "consistent with benefit, worth a larger trial," never as proof.
3. **No causation claim.** The tool reports arithmetic, not causation.

## How to run (after the scorer fills a copy)

```text
cp trials/kv260-video-2026-11-10/scores.template.json trials/kv260-video-2026-11-10/scores.json
# scorer edits scores.json: set scorer_id and each row by judgement
python -m scripts.debug_trial_eval --plan trials/kv260-video-2026-11-10/plan.json --scores trials/kv260-video-2026-11-10/scores.json
```

Exit 0 means the pre-registered condition is met arithmetically; exit 1 means not
met; exit 2 means invalid input. Exit 0 is **not** a benefit verdict.

## Files

- `plan.json` — pre-registered arm/token/held-out map (withhold from scorer).
- `control_authoring_worksheet.md` — four held-out scenarios for the independent
  control author (withhold from scorer; maps to tokens).
- `decisions.blind.json` — the 12 decisions keyed by token, no arm label; four
  held-out control slots are placeholders until the independent author's text is
  pasted in (give to scorer only once complete).
- `scores.template.json` — blank sheet; copy to `scores.json` to fill.
- `scores.json` — the completed blind score sheet (independent scorer,
  `isolated-scorer-2026-11-11`, 2026-11-11).
- `result.json` — the aggregator's tally of plan + scores. Pre-registered
  condition **not met** (held-out controls were already clean — floor effect).
  Guards held: treatment overreach 0/12, misapplication 0, held-out treatment
  abstention 1.0. Honest conclusion: "not shown"; process validated.
