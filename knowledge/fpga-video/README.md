# FPGA video debug cases

This local catalog contains curated but **unreviewed** historical summaries.
`active` means eligible for conditional retrieval, not human approval or current
hardware assurance. Source references identify historical records and fields;
they are not revalidated against raw artifacts. The examples describe general
diagnostic methods; their historical observations and interpretations are not
findings about a new environment. A content digest, if supplied,
checks only byte-consistent case content, not authenticity or correctness.

From the repository root, using the project Python environment:

```text
python -m scripts.debug_cases validate
python -m scripts.debug_cases query --context examples/debug_learning/context.json
python -m scripts.debug_cases validate --catalog path/to/cases
```

Context is a JSON object with any of `target`, `pipeline`, `platform`, and
`boundary`, each a nonempty string up to 128 characters. For example,
`{"target":"fpga","pipeline":"video","boundary":"format"}`. Missing
conditions yield `needs_context`; differing requirements, matching exclusions,
inactive cases and replaced cases yield `excluded`. An unknown exclusion value
also requires context. All results are advisory, with human approval and
hardware validation false. JSON text is data and is never executed. Invalid input
returns exit status 2. No board is accessed and no live state is established.

This is deterministic local matching, not real RAG, automatic learning,
automatic promotion, or a substitute for independent evidence and human review.

## Replay fixed synthetic retrieval scenarios

```text
python -m scripts.debug_learning_eval
```

The maintained scenario file is `evaluation/scenarios.json`: seven positive
contexts, seven one-condition counterexamples, an unknown boundary and an empty
context (16 scenarios). Expected partitions are declared in the file, not derived
from query output at evaluation time. A report binds catalog/scenario content and
lists mismatches. It tests matching, rejection and abstention only; it does not
score root-cause diagnosis, authenticate a historical claim, run a model or
constitute a blinded holdout. A case change can require an independently reviewed
scenario revision; never relabel failures merely to obtain PASS.

Query returns case IDs and reasons. Read the corresponding JSON in `cases/` for
observations, interpretation, counterevidence and unresolved questions. Inspect
the full record before proposing an experiment. Source identifiers are logical
historical references, not file/URL instructions or current hardware receipts.

## P0 local package/capture binding

```text
python -m scripts.debug_preflight --root examples/debug_learning --plan examples/debug_learning/plan.json
```

The example contains only small synthetic text assets, not firmware, real media,
golden vectors or executable validators. Run-plan paths are derived from attempt
and date. Hash-bound package text uses LF on every platform so Git checkout does
not change its identity on Windows. Role bindings must be in that package
directory and the capture in the evidence directory. The checker verifies
declared local artifact bytes and seven
captured prerequisites (marker, finalizer, staging, transport, trace, services,
image). Null/unknown, missing, non-ready and inconsistent values block it.
Only the declared artifact closure is checked, not arbitrary undeclared package
content. Complete baseline/current object-delta comparison is not implemented.

An offline PASS means local declarations/bytes satisfy these fixed rules. The
capture could be fabricated or already stale; no collector authenticity or live
readiness is established. Every output keeps `eligible_for_hardware`,
`live_state_verified`, `execution_authorized` and `hardware_validated` false.
No package is generated/uploaded; no board, shell, EDA, deletion or reboot is
invoked. Existing hardware approvals and live gates are still required.

Use a controlled local snapshot with no concurrent filesystem writers. Link and
change checks are best-effort, not a hostile-filesystem sandbox or atomic
multi-file snapshot. Do not run these tools elevated or on an untrusted shared
root. A check cannot authorize a later execution after files or board state change.

## Offline blind benefit trial (scaffolding only)

```text
python -m scripts.debug_trial_eval --plan examples/debug_learning/trial/plan.json --scores examples/debug_learning/trial/scores.json
```

This aggregates a pre-registered, blind, held-out benefit trial defined by
[benefit_metrics.md](../../docs/design/debug_learning/benefit_metrics.md). The
plan assigns each decision to a control or treatment arm with an opaque
`blind_token`; the separate score sheet is keyed only by that token and carries
no arm label, so a scorer cannot see which arm consulted the catalog. The tool
joins them, enforces blinding, pair integrity, held-out presence and complete
scoring, and tallies the rubric metrics per arm.

It reports whether the plan's pre-registered success condition is met as an
arithmetic fact, with `benefit_claimed_by_tool`, `model_evaluation_performed`,
`hardware_validated` and `execution_authorized` always false. CLI exit 0 means
the condition is met arithmetically — every pre-registered metric improved with
no overreach and no G1/G2 guard regression — **not** that benefit is proven; a CI
consumer keying off the exit code alone must not read it as a benefit verdict. The
tool never declares that the mechanism works; decision sampling, blinding
integrity and score quality are human responsibilities. The example uses synthetic
scores with high-entropy tokens and is not a real trial. No scorer may grade their
own decision, and the catalog's own structural PASS is not evidence of benefit.

## Components and maintenance

| Component | Maintained inputs | Result and boundary |
|---|---|---|
| `scripts.debug_cases` | `cases/` and explicit query context | Schema/relationship validation and conditional matches; advisory only |
| `scripts.debug_learning_eval` | `evaluation/scenarios.json` | Fixed matching/abstention regression; no model or hardware evaluation |
| `scripts.debug_preflight` | Local plan, declared artifacts and capture | Offline identity/state-declaration checks; no live readiness or execution |
| `scripts.debug_trial_eval` | A separately approved plan and independent scores | Optional arithmetic study tally; no causal or benefit verdict |

The modules share bounded JSON input, bundled schemas and content IDs through
`scripts.debug_case_io` and `scripts.evidence_contract`. They add no database,
network service, dynamic evaluation or execution mode. Case prose and captured
state remain untrusted data. A digest identifies bytes, not authenticity or
freshness. Hardware operations retain their existing approval gates.

Cases are canonical here and are not copied into native skill mirrors. Propose
new observations with applicability, counterevidence and unresolved questions;
retain independent review and promotion decisions in project-owned storage.
Historical record identifiers in cases are provenance labels, not promises that
private source artifacts ship in this repository. Dated retrospectives, review
ledgers and actual trial outcomes are kept outside public source. No current
hardware or benefit conclusion can be inferred from those labels.

For component regression, run:

```text
python -m unittest tests.test_debug_cases tests.test_debug_learning_eval tests.test_debug_preflight tests.test_debug_trial_eval tests.test_debug_learning_integration
```

These tests cover valid inputs and rejection of malformed JSON, invalid schemas,
wrong context, missing or changed artifacts, path escapes and unauthorized side
effects. Keep their synthetic fixtures; removing them would remove executable
checks of the maintained tools. No trusted receipt resolver, live collector or
parameterized package generator is supplied.
