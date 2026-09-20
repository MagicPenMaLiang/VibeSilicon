---
name: fpga-rtl-system
description: Design portable synthesizable RTL, protocols, CDC boundaries, constraints, and target-specific wrappers for FPGA/ASIC systems.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: implementation
  routes: [fpga, asic, both]
---

# RTL system design

Follow `docs/rtl_coding_standard.md` and the machine-readable rules in `config/rtl_quality_rules.json`.

## Boundaries

- Behavioral/control/compute RTL stays technology-neutral where practical.
- Inferred memory is isolated in a dedicated module with documented semantics.
- Vendor primitives, foundry macros, PLLs, transceivers, and I/O cells live behind reviewed wrappers.
- Assertions and testbench code are separate from synthesizable ownership.

## Required design details

- Explicit widths, signedness, clock/reset ownership, and legal parameter ranges.
- Stable protocol behavior under backpressure and reset.
- Reviewed synchronizer/handshake/FIFO topology for every CDC.
- Narrow timing exceptions with endpoint and proof evidence.
- Deterministic behavior for illegal states and unsupported transactions.

References: `references/cdc_primitives.md`, `references/timing_constraints.md`, and `references/verilog_templates/`.
