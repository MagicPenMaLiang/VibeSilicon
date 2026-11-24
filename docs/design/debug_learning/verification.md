# First offline increment: verification

Date: 2026-11-10. These are software checks of the current local working tree,
not board qualification, production sign-off or knowledge approval.

## Second increment: case review and blind-trial scaffolding (2026-11-10)

- Independent two-round text review of all seven cases: six ACCEPT in round 1,
  `package-binding` REVISE then ACCEPT in round 2 after its attribution was
  corrected. Recorded in [`knowledge/fpga-video/review_ledger.md`](../../../knowledge/fpga-video/review_ledger.md).
- Human text-review sign-off recorded in the ledger (approver Z, 2026-11-10).
  Case files keep `review_status: REVIEW_REQUIRED`; the ledger is the only
  promotion record and grants an advisory prior tier, not verified knowledge.
- Benefit-measurement contract added:
  [`benefit_metrics.md`](benefit_metrics.md) (M1–M5 primary, G1–G3 guard,
  two-arm held-out blind design, explicit non-claims).
- Offline blind-trial aggregator (`scripts/debug_trial_eval.py`) with two schemas.
  Scores are keyed only by opaque blind tokens and carry no arm label. The tool
  tallies metrics per arm and reports whether the pre-registered condition is met
  arithmetically; it never sets `benefit_claimed_by_tool`, `hardware_validated`,
  `execution_authorized` or `model_evaluation_performed` true.
- New results: 13 trial tests OK; combined new-module coverage 91% (trial module
  86%); full repository unittest discovery passes with external temp dir; ruff
  PASS; skill sync PASS; public release audit unchanged at 11 pre-existing failures.
- Independent security/correctness review of the scaffolding: no CRITICAL/HIGH;
  overall LOW. The one MEDIUM (success condition omitted the G1 abstention guard
  that the rubric requires) and the LOW dead-config (`max_overreach` unread) and
  example-token findings were fixed: the plan now carries
  `require_g1_non_regression`, `_success` reads `max_overreach` and blocks on G1
  regression, the example uses high-entropy tokens, and the rubric/README state the
  conjunctive metric semantics and the exit-code meaning.
- The trial tool aggregates human scores only. It does not run a model A/B, sample
  decisions, grade decisions, or prove causation. The example trial uses synthetic
  scores. A met condition is evidence for the pre-registered hypothesis, subject to
  human blinding and sampling integrity, not a tool-issued benefit verdict.

## Issued pilot trial instance (2026-11-10)

A real pre-registered pilot was issued under `trials/kv260-video-2026-11-10/`
(`plan.json`, `decisions.blind.json`, `scores.template.json`, `README.md`). It is
a data instance, not new code; it adds no test and changes no module. Structural
verification of the instance, not a benefit result:

- `plan.json` and `scores.template.json` both pass their local schemas; the plan,
  the blinded workbook and the score template share the same twelve opaque tokens;
  the workbook carries no `arm`/`pair` label.
- Six pairs / twelve decisions: four held-out pairs on retrospective topics with
  **no** corresponding case (throughput r75, geometry r71/r78, single-bank r66,
  EOS ownership S11) and two non-held-out pairs on case-covered topics (nv12-rgbx,
  observer-scope). Held-out decisions decide success; the aggregator counts four
  held-out pairs per arm, meeting the pre-registered `min_pairs=3`.
- Aggregator dry-run on the blank all-false template reports
  `pre_registered_condition_met: false` (exit 1) with the four authorization flags
  false, confirming no benefit is pre-baked and that blinding, pairing, held-out
  presence and coverage checks pass before any human score exists.
- The decision author (assistant) wrote both arms and did **not** score. Primary
  threat to validity, recorded in the trial README: single-author arm construction;
  a met result is evidence only if an independent blind scorer also certifies the
  control arms were fairly constructed. With four held-out pairs this is a pilot;
  a met result means "worth a larger trial," not "proven."
- `tests.test_debug_trial_eval` re-run after adding the instance: 13 tests OK. The
  `trials/` data directory does not perturb `tests/` discovery.

## Pilot trial outcome (2026-11-11)

The pilot was executed as registered: the four held-out control arms were written
by an independent author from the cold worksheet, the twelve decisions were scored
blind by an independent scorer (`scorer_id: isolated-scorer-2026-11-11`), and the
aggregator joined plan + scores with all integrity checks passing. Result retained
in `trials/kv260-video-2026-11-10/result.json` (binds `plan_id` and `scores_id`
content IDs).

- Pre-registered condition: **not met** (exit 1; reasons: m1 and m4 not strictly
  lower in treatment).
- Held-out arms (n=4 per arm, the ones that decide success): control m1=0, m4=0,
  m3=0; treatment m1=0, m4=0, m3=0. The independent control author did not write
  strawmen — the held-out controls were already clean, so there was no headroom for
  a strict reduction at this sample size (floor effect).
- All twelve decisions: control m1=1/6 and m3=1/6, both landing on the
  assistant-authored **non-held-out** context arms; treatment all-zero everywhere.
  These pairs are excluded from the success computation by pre-registration, so
  this is an observation, not evidence.
- Guards held as designed: treatment M3 overreach 0/12, G2 misapplication 0
  everywhere, and held-out treatment G1 abstention 1.0 — on topics with no
  applicable case the mechanism abstained and reasoned from first principles
  rather than forcing a match, with no abstention regression.
- Honest conclusion: **"not shown"** — the pilot validates the process and the
  guards, and does not demonstrate (or refute) an M1/M4 benefit. A larger trial
  with harder held-out scenarios, or decisions sampled from real work rather than
  synthetic scenarios, is required before any benefit claim. The trial tool's
  flags remain false; nothing here authorizes hardware or promotes a case.

## Delivered

- Source-qualified video bring-up retrospective and five planning documents.
- Seven conditional cases, all `REVIEW_REQUIRED`, with observations,
  interpretations, counterevidence and unresolved questions kept separate.
- Strict local schemas and bounded, read-only catalog validation/query.
- Sixteen fixed synthetic matching/rejection/abstention scenarios.
- Offline run-plan naming, declared artifact closure/hash and captured-state checks.
- Thin integration in two canonical skills and synchronized native skill copies.
- Unit tests, CLI integration and negative security/input tests using existing
  unittest discovery. No new runtime dependency was introduced.

## Actual results

| Check | Result |
|---|---|
| Focused tests including public-source regression | 49 tests, OK |
| Full repository unittest discovery | 465 tests, OK; 4 skipped |
| New-module branch-aware coverage | 92% combined |
| `debug_case_io` | 92% |
| `debug_cases` | 98% |
| `debug_learning_eval` | 96% |
| `debug_preflight` | 86% |
| Ruff across `scripts`, `mcp`, `tests` | PASS |
| Skill generation `--write`, then `--check` | PASS; no differences |
| `git diff --check` | PASS |
| Independent code and security reviews | No remaining CRITICAL/HIGH findings |
| Final narrow code delta review | No additional findings |
| Public release audit | FAIL: 11 issues in pre-existing local assets |

Skipped repository tests are not PASS evidence for their underlying capabilities.
CLI subprocess integration runs were verified independently; the coverage report
measures the in-process paths and does not claim to include subprocess coverage.

The first full-suite attempt used a temporary directory inside the repository.
That invalidated existing external-PDK and outside-root fixtures: it produced
43 errors and 3 failures. A complete rerun with temporary fixtures outside the
repository passed. No containment rule or ASIC/protocol implementation was changed.

The release audit still reports nine out-of-profile `.zcode/` paths and two
issues (profile and local-path content) in the pre-existing private package script.
The new `knowledge/` source directory is allowed, but sensitive extensions and
private-path checks remain enforced. No user asset was removed to make the audit
pass. This working tree is **not** certified for public release.

## Reproduction

Use the existing project Python environment from the repository root:

```text
python -m unittest tests.test_debug_cases tests.test_debug_learning_eval tests.test_debug_preflight tests.test_debug_learning_integration tests.test_public_release_audit
python -m coverage run --branch --source=scripts.debug_case_io,scripts.debug_cases,scripts.debug_learning_eval,scripts.debug_preflight -m unittest tests.test_debug_cases tests.test_debug_learning_eval tests.test_debug_preflight tests.test_debug_learning_integration tests.test_public_release_audit
python -m coverage report --show-missing
python -m unittest discover -s tests -p "test_*.py"
python -m ruff check scripts mcp tests
python scripts/sync_skills.py --check
python scripts/public_release_audit.py --json
```

`coverage==7.10.7` was installed as a local verification tool, not added as a
runtime requirement. For full-suite discovery, TMP/TEMP must point to a writable
directory **outside** the repository so external-root fixtures remain external.

Local logs, coverage data and a content-addressed source/log manifest are retained
under `.vibesilicon/debug-learning/`. They are local verification artifacts, not
public source or trusted hardware receipts. Hashes bind the recorded bytes only;
they do not authenticate historical sources or prove approval.

## Review corrections verified

- Unified case IDs and independently declared scenario labels.
- Rejected empty catalogs to prevent vacuous evaluation success.
- Converted preflight tests to unittest so existing CI actually discovers them.
- Cached only bundled schemas and batch-validated retrieval inputs.
- Required real confined package/evidence directories and role/capture ownership.
- Stopped catalog enumeration at the first over-limit case.
- Rejected unsupported Python path types with controlled errors.
- Added bounded schema field/rule diagnostics and relative artifact hash locations.
- Preserved read-only inputs and false execution/hardware flags on all outcomes.

## Explicitly deferred

There is no board access, live collector, actual package generator/uploader,
trusted receipt-to-metrics resolver, complete baseline/current object-delta check,
model A/B experiment, hidden holdout, automatic case promotion or automatic
optimization acceptance. No RTL, real golden vectors, timing limits, hardware
approvals or role permissions were changed. No commit or push was performed.

An offline preflight PASS never sets `eligible_for_hardware`,
`live_state_verified`, `execution_authorized` or `hardware_validated` to true.
Historical case summaries still require independent human review before promotion.
