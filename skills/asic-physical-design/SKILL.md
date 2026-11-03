---
name: asic-physical-design
description: Prepare, execute or review the fixed OpenROAD ASIC physical flow with approved floorplan, placement, CTS, routing and extracted evidence inputs.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: implementation
  routes: [asic, both]
---

# ASIC physical implementation

Require verified A01/A02 bindings, reviewed physical configuration and
stage-specific approval. Read `templates/asic_physical_config.template.json`,
`templates/asic_pdk_physical_rules.template.json` and
`templates/asic_physical_approval.template.json` at repository root. The
reference physical configuration is design/PDK specific, not a universal
floorplan or routing recommendation.

Use `python -m scripts.asic_physical_artifact --help`. Its `run` mode consumes
the config, manifest, policy, capabilities, A02 evidence/approval and external
PDK/design/A02-run/physical-run roots. Execution requires both the matching
approval and explicit authorization flag. Keep raw runs, databases, GDS and
parasitics external. Use `verify-run` to validate the evidence without launching
implementation; artifact existence alone cannot pass a stage.

Review floorplan/site/units, placement density, pin layers, filler/tie/tap
requirements, RC/routing layers, CTS and supported repair settings against the
selected PDK and source. Inspect the fixed adapter before promising support for
macro placement, power delivery, hierarchical design or other advanced scope.
Do not inject arbitrary Tcl or silently alter electrical/physical assumptions.

For optimization preserve a baseline and change one reviewed hypothesis with
explicit timing/area/power/DRC limits. Preserve failing candidates. Route
physical checks/finalization to asic-drc-lvs, timing interpretation to asic-sta
and comparable metrics to asic-ppa. A03 run completion is distinct from final
DRC/LVS acceptance and production signoff.
