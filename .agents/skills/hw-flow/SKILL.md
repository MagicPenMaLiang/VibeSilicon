---
name: hw-flow
description: Select and coordinate FPGA, ASIC or dual-target engineering work using shared RTL gates and separate target evidence. Use at project intake or when work crosses stages.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: orchestration
  routes: [fpga, asic, both]
---

# Hardware workflow

Read repository-root `AGENTS.md`, `docs/new_project_inputs.md`, and
`subagents/catalog.json`. Use architect-hw, coder-rtl, reviewer-hw and
orchestrator-hw as four responsibilities, not separate FPGA/ASIC teams.
Use delegation only when the task and environment authorize it.

Select `fpga`, `asic`, or `both` before selecting target tools. Require the
functional/numeric contract, source manifest, clocks/resets, memory boundary,
verification inputs, budgets and review ownership. Prepare the architecture
with hw-microarch and preserve independent human architecture review before
implementation. RTL implementation and verification use rtl-implementation,
rtl-design, rtl-lint, rtl-simulation, rtl-coverage, rtl-cdc and rtl-formal as
applicable; neither a lint result nor directed smoke establishes full correctness.

For FPGA implementation and board work, follow fpga-flow. For ASIC PDK,
synthesis/STA, physical and handoff work, follow asic-flow. A dual-target task
uses both branches with separate manifests, memory wrappers, constraints,
budgets and acceptance. A target-specific result never passes the other branch.
Do not run Vivado, Vitis or AMD documentation queries as an ASIC prerequisite.

Use hw-design-review for independent review and hw-ppa-analysis for compatible
comparisons. Report each required check with source/configuration hashes,
status, evidence and unresolved ownership. Missing tools or approvals leave the
dependent stage BLOCKED; progress on independent authorized work may continue.

See `docs/project_map.md` for implemented adapters and explicit capability gaps.
