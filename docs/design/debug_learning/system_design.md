# Debug learning system design

## Information flow

1. Preserve original run evidence in its authorized evidence domain.
2. Extract a sanitized candidate case, keeping observations, rejected hypotheses
   and open questions distinct.
3. Validate its schema, identifiers, relationships and conditional context.
4. Query locally for matching, incomplete or excluded cases; expose limitations.
5. Replay frozen synthetic context/counterexample scenarios.
6. Present a review proposal. Do not automatically promote or execute anything.
7. In future runs, new counterevidence can make an interpretation stale/retracted;
   retain history rather than rewriting a failed trial into success.

## Runtime preparation boundary

A declarative run plan binds attempt/date-derived package and evidence paths,
expected boot, an artifact inventory and a local state capture by digest. The
checker compares local bytes and explicit state declarations. It neither gathers
state nor creates/uploads a package. Unknown, missing or non-ready prerequisites
block offline satisfaction. Capture digests cannot establish live freshness or
prevent the board changing after collection; existing execution gates must still
perform their own authorized checks.

## Evaluation boundary

Use synthetic, distributable positive/negative pairs. Expected results are fixed
before running the checker, never derived from the observed output. A report
identifies catalog and scenario bytes, tested counts and failures. This verifies
matching/abstention and safety contracts only. No LLM is called and no saving of
board iterations or model improvement is claimed.

Future model evaluation must hide later outcomes, split by mechanism/environment
rather than adjacent run IDs, hold tools/model/budget constant, retain failures,
and compare baseline, skill-only, case-only and combined conditions. Holdout
labels and graders must be controlled independently of the candidate writer.

## Scope of this increment

The existing four hardware roles are unchanged. Canonical skills reference one
catalog rather than copying cases into every native skill mirror. The public
catalog is independent of private .vd2 artifacts. No automatic state cleanup,
threshold adjustment or case-to-gate promotion is introduced.
