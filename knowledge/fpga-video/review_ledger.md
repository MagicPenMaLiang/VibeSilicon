# Case review ledger

Human-owned record of independent reviews of the conditional case catalog. This
ledger is the only place a promotion decision is recorded. Case files keep
`review_status: REVIEW_REQUIRED` by schema and cannot promote themselves; an
entry here does not change their stored status and does not authorize hardware
action. Promotion to an approved knowledge tier remains a separate, explicit
human decision that must be dated and signed below.

## Review round 1 — faithfulness and scope vs retrospective

- Date: 2026-11-10
- Reviewer: independent reviewer-hw agent (read-only), text-faithfulness and
  scope review against `docs/reviews/kv260_video_bringup_retrospective_20261110.md`
  and `knowledge/fpga-video/README.md` only.
- Boundary: raw historical artifacts (r58/r60/r75/r109/r112/r115/r117) were not
  independently re-examined. This review is not current-run evidence, architecture
  approval, or hardware authorization.

| Case | Verdict | Action taken |
|---|---|---|
| nv12-rgbx | ACCEPT | none |
| observer-scope | ACCEPT | none |
| physical-vs-internal | ACCEPT | none |
| prehardware-side-effects | ACCEPT | none |
| r59-attribution | ACCEPT | none |
| shared-golden-error | ACCEPT | none |
| package-binding | REVISE | revised 2026-11-10: re-scoped observation to runtime-record evidence separation; added a second source reference crediting the preflight tooling for package/capture binding instead of attributing it to the retrospective |

The single REVISE finding: `package-binding` attributed "package" evidence
separation to the retrospective, which does not discuss package/capture binding —
that concept belongs to the preflight tooling (`scripts/debug_preflight`, README
P0). The teaching itself (local declarations/digests do not establish live state
or authorization) was sound; only the attribution was corrected. The revised
case re-validates against the schema and the 16 fixed scenarios still pass.

## Review round 2 — re-review of revised package-binding

- Date: 2026-11-10
- Reviewer: independent reviewer-hw agent (read-only), focused re-review of the
  revised `package-binding` against the same two documents.
- Verdict: ACCEPT. The round-1 REVISE finding is resolved: the observation now
  separates retrospective-supported runtime-record evidence separation from the
  tooling-defined package/capture binding, the source references are accurately
  credited, scope stays general (no platform key), and no new overstatement,
  current-finding claim, or gate relaxation was introduced. Counterevidence
  remains an adequate limiting condition.

All seven cases are now text-reviewed with an ACCEPT verdict (six in round 1,
`package-binding` in round 2). They remain `REVIEW_REQUIRED` in file; promotion
is still a separate human decision recorded below.

## Promotion decision

Signed below. This records the human text-review sign-off only. It does not change
any case's stored `review_status` (which remains `REVIEW_REQUIRED` by schema), is
not a benefit claim, and does not authorize hardware action. The benefit trial
remains outstanding.

```
- Approved by (name): Z
- Date: 2026-11-10
- Scope of this signature: all 7 ACCEPT cases
- Tier granted: text-reviewed advisory prior, eligible for the benefit trial
  (NOT verified knowledge; raw hardware evidence not re-examined; benefit not yet shown)
```

Outstanding regardless of the signature above:

1. The signature itself, naming the approver and date.
2. The benefit-measurement contract in
   [benefit_metrics.md](../../docs/design/debug_learning/benefit_metrics.md) run
   as a pre-registered, blind, held-out trial — separately approved, not yet done.

Until both exist, these cases are advisory historical priors only.
