# L3.3 human sign-off for high-risk RTL and engineering results

The normative sources are repository-root `docs/rtl_coding_standard.md` and
`config/rtl_quality_rules.json`. An authorized human reviewer must be distinct
from the proposer; an agent must not sign on behalf of either person.

## Sign-off contract

Records must satisfy `schemas/rtl_quality_signoff.schema.json`, binding the source
commit, FPGA/ASIC and handwritten/generated profiles, standard/policy versions,
rule IDs, scope, raw evidence IDs, risk conclusion, approver and UTC approval time.
Review applicable PHY, power-up/cross-domain reset, security/key handling,
clock/timing exceptions, ASIC DFT/low-power and release conclusions.

Reassess after source, constraint or evidence changes. Missing evidence or approval
is BLOCKED; ordinary lint PASS is not sign-off. Register waivers separately under
`schemas/rtl_quality_waiver.schema.json`, with owner, expiry, compensating checks
and removal conditions.

## Ownership and verdicts

Architecture/RTL owners cover interfaces, numeric behavior and pipelines;
CDC/reset/timing owners cover crossings, reset, clocks and exceptions. FPGA owners
cover primitives, implementation and board conclusions; ASIC owners cover PDKs,
macros, DFT/low-power and STA/DRC/LVS. Security/PHY specialists review their scope.
Roles may be combined where authorized, but proposer and approver remain separate.

Use evidence-bound PASS, explicit BLOCKED, or NOT_APPLICABLE with a reason.
A file's existence or `signed: true` does not establish approval. Approval identity
and evidence must currently be checked by a human; the workflow does not
cryptographically authenticate a reviewer.
