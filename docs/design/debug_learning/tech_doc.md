# Debug learning technical design

## Implementation contracts

- Python 3.10-3.12; reuse pinned jsonschema and scripts.evidence_contract hashes.
- Fixed repository JSON schemas with additionalProperties disabled and bounded
  strings/arrays; no remote schema resolution or new dependency.
- Read JSON with duplicate-key and non-finite-number rejection, size limits and
  explicit errors. Treat all loaded prose as untrusted data.
- Root-relative artifacts reject absolute/drive/backslash/traversal forms and
  resolved escapes. Validate regular files before reading/hashing them.
- Commands read local inputs and print JSON. They do not shell out, call EDA,
  access a board, write inputs, fetch references or evaluate case instructions.
- Deterministic sorted output; content IDs bind relevant report inputs, but never
  authenticate their origin or turn declarations into measured observations.

## Interfaces

The first implementation provides scripts.debug_cases (validate/query),
scripts.debug_learning_eval (fixed offline scenario replay), and
scripts.debug_preflight (local run-plan/capture validation). Each exposes Python
functions for unit tests and python -m CLI entry points. See the catalog README
for exact arguments and neutral fixture usage; the README must be kept aligned
with actual --help output.

## Required negative coverage

Schema/ID mismatch, duplicate IDs, dangling/cyclic replacement relations,
missing context, wrong environment, stale/retracted cases, unknown symptoms,
unknown status, wrong boot/capture digest, absent artifacts, invalid names,
artifact hash mismatch, root escapes/symlinks, residual or unknown prerequisites,
invalid JSON/NaN/duplicate keys and oversized input. Test both valid input and
rejection; an always-blocking implementation is not acceptable.

## Verification

Run targeted unit/CLI integration tests and measure new-module coverage, then
ruff, skill sync --write/--check, release checks and the repository test suite.
Distinguish pre-existing local/public-release failures from regressions. Never
change existing dirty files or delete private assets to make a check pass.

## Deferred

Actual package generation, live capture adapter, trusted receipt-to-metric
resolver, signed knowledge promotion and blinded model A/B. None may be claimed
as delivered by deterministic fixture tests or by a successful offline plan.
