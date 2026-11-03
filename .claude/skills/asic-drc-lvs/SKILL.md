---
name: asic-drc-lvs
description: Review ASIC physical DRC/LVS evidence, localize violations and finalize the existing A03 artifact chain without treating engineering checks as foundry signoff.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: verification
  routes: [asic, both]
---

# ASIC DRC and LVS

Require the exact physical run, layout/netlist/top, PDK/rule-deck hashes,
tool/version, A02/A03 bindings and approval records. DRC and LVS are separate
checks; neither clean routing nor a GDS file proves either one.

Use `python -m scripts.asic_physical_artifact --help` for `verify-run`,
`finalize` and `verify-final`. The final manifest consumes the physical evidence
and an independently sourced LVS receipt following
`templates/asic_lvs_receipt.template.json`. Validate the receipt with the
adapter's existing fields and artifact hashes; never fabricate a PASS receipt
from a routing log. Finalization retains timing and DRC/LVS result status.

For read-only violation localization use
`python -m scripts.asic_signoff_localization --help`. Bind diagnostics to the
same final database/layout and rule set. A localization candidate is a debugging
aid, not proof of the responsible source cell or a completed repair. After a
physical or netlist change regenerate dependent timing, extraction, DRC and LVS
evidence; do not reuse a stale clean receipt.

Localization output contains design identifiers and layout coordinates and is
explicitly not repository-safe. Keep it in the external run directory; only
sanitized summaries and artifact hashes may enter a public handoff.

Report violation counts, mismatch classes, primary evidence, waived scope and
whether the selected decks/tools are authoritative for the target process.
Open-source engineering checks do not confer foundry signoff. Pass the verified
final chain and remaining obligations to asic-signoff-handoff.
