---
name: asic-sta
description: Review ASIC timing constraints, process-corner and parasitic assumptions, and source-bound STA evidence from the existing synthesis or physical adapters.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: analysis
  routes: [asic, both]
---

# ASIC static timing analysis

Require source/netlist bindings, reviewed clocks and IO timing, SDC, Liberty/PVT,
RC/parasitic stage, load/drive assumptions, clock uncertainty and exceptions.
Do not translate a board XDC or reference-design clock into an ASIC timing
contract. An absent constraint or unanalysed corner is unknown, not zero slack.

Read the A02 evidence from scripts.asic_synth_sta_adapter and, where present,
the A03 evidence from scripts.asic_physical_artifact. Use each module's `--help`
for its evidence verification mode. A02 STA executes with synthesis through
asic-synthesis; this skill does not expose arbitrary Tcl or a new STA launcher.

For each required mode/corner distinguish setup, hold, unconstrained endpoints,
clock propagation and exceptions, and estimated versus extracted parasitics.
Check primary reports rather than inferring timing closure from WNS alone.
The A02 contract exposes aggregate WNS/TNS and timing_met; it does not establish
complete setup/hold, constraint-completeness or MMMC signoff. Mark required
checks outside the supplied evidence BLOCKED and identify the external report
or backend needed. Do not weaken a clock or exception to hide violations.

Return a mode/corner matrix containing evidence IDs, stage, reported metrics,
missing analyses and budget verdicts. Keep corner-specific results separate.
Use rtl-cdc for crossing correctness, hw-design-review for independent review
and asic-ppa for performance reporting. Physical timing repairs require a
reviewed bounded implementation change and fresh downstream evidence.
