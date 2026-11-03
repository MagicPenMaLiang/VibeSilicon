---
name: asic-signoff-handoff
description: Assemble and independently review an ASIC evidence handoff, including the fixed reference reproduction assessment where applicable, while preserving human signoff authority.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: review
  routes: [asic, both]
---

# ASIC evidence handoff

Use hw-design-review and remain read-only during independent review. Assemble
requirements and architecture approval, RTL gate evidence, PDK/license/corner
review, source/configuration/tool hashes, A01/A02/A03 chains, timing/DRC/LVS,
PPA assumptions, exceptions, missing scope and named signoff ownership. Verify
current primary artifacts and their retention locations; summaries and hashes
alone do not prove the reported checks were adequate.

For the explicitly selected fixed ORFS/SKY130HD/GCD reference profile, read
`config/asic_reproduction_profile.json` and use
`python -m scripts.asic_toolchain_provenance --help`,
`python -m scripts.asic_reference_signoff --help` and
`python -m scripts.asic_reproduction_acceptance --help`.
Bind baseline/replay descriptors, the independent review and toolchain
provenance. Preserve the profile's required independent runs and thresholds;
do not apply it to arbitrary customer designs or change acceptance to fit a run.
Reference-signoff diagnostics explicitly grant no acceptance authority.

State the acceptance scope separately: software contracts, engineering
implementation, fixed-profile reproduction, or independently qualified process
signoff. Missing MMMC, DFT/ATPG, UPF, IR/EM, macro qualification or authoritative
decks must remain open when required by the project; these capabilities are not
implemented by adding this skill. Do not generate human approval or certify
tapeout. Return a traceable handoff with PASS/FAIL/BLOCKED/NOT_APPLICABLE per
required check and concrete ownership of remaining obligations.
