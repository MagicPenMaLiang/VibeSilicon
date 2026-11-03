---
name: asic-synthesis
description: Run or review the fixed Yosys ASIC synthesis and OpenROAD STA adapter using approved PDK, source, constraints and execution bindings.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: implementation
  routes: [asic, both]
---

# ASIC synthesis

Require the reviewed architecture, current shared RTL gate evidence and
asic-pdk-intake outputs. Review allowed cells, driver/load assumptions,
memory/macro mappings and constraints using
`templates/asic_pdk_synthesis_rules.template.json`. Keep technology wrappers
separate from portable RTL; no vendor primitive or initialized RAM assumption
may silently enter the ASIC netlist.

Use `python -m scripts.asic_synth_sta_adapter --help`. Its `run` mode performs
the fixed combined Yosys/OpenROAD A02 operation; there is no standalone synthesis
execution command in this adapter. Bind policy, backend contract, capabilities,
input evidence, reviewed A02 approval and external PDK/design/run roots. Retain
the existing explicit execution flag. `verify` checks evidence without execution
inputs; it still requires the bound approval record.

Preserve generated scripts, tool versions/binary hashes, synthesis statistics,
netlist and logs externally, and emit sanitized content-addressed evidence.
Review inferred/mapped storage, black boxes, cell count/area and diagnostics.
Do not claim RTL/netlist equivalence from synthesis completion; route required
proof to rtl-formal with an appropriate reviewed backend and assumptions.

Pass A02 timing evidence to asic-sta. A completed run with failing timing is not
a synthesis/STA acceptance PASS. Record area and timing against the declared
budget before advancing to asic-physical-design.
