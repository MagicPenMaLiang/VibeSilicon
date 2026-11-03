---
name: asic-ppa
description: Plan and verify ASIC power, performance and area reports using bound synthesis/physical evidence, explicit activity and parasitic assumptions.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: analysis
  routes: [asic, both]
---

# ASIC PPA evidence

Use hw-ppa-analysis for comparison rules. Require A01/A02 and, for routed claims,
A03 evidence, the primary power report/script and matching netlist/SDC/Liberty.
Read repository-root `docs/asic_ppa.md` and
`templates/asic_power_activity.template.json`.

Use `python -m scripts.asic_ppa_report --help` and its `plan`, `build`, and
`verify` modes. Planning emits inputs for power estimation; it does not execute
a new power-analysis backend or prove timing/physical acceptance. Build only
from real reports and preserve the module's hash and stage consistency checks.

Disclose VCD/SAIF/ESTIMATED mode, activity scope and annotation, clocks, time
window and vectorless defaults as applicable. Do not silently replace missing
activity with defaults. Record parasitic stage and SPEF binding where used.
If a required activity field or analysis is not recorded by the current schema,
retain it in the supporting reviewed record and declare the limitation.

Report cell count/area and macro area where available, corner-specific timing,
leakage/internal/switching/total power, utilization and DRC/LVS status. Missing
dimensions stay missing; do not convert them to zero. Compare only matching
behavior, throughput, corners, constraints, tools and activity assumptions.
Keep FPGA resource counts separate from ASIC area. Send evidence IDs, budget
verdicts and unresolved scope to asic-signoff-handoff.
