---
name: fpga-cdc-check
description: Analyze clock-domain crossings, choose safe synchronizers or asynchronous FIFOs, and review CDC evidence without accepting structural lint as functional proof.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: verification
  routes: [fpga, asic, both]
---

# CDC analysis

Use this skill when a design has multiple clocks, asynchronous inputs, generated clocks, or reset-domain crossings.

## Required inputs

- Clock/reset inventory and relationships.
- Source manifest and target configuration.
- Crossing list with data width, rate, coherency, and loss/backpressure requirements.
- Structural CDC report and applicable protocol/formal evidence.

## Rules

- Single-bit level: reviewed two-or-more-flop synchronizer, with the first stages placed together where supported.
- Pulse/event: toggle, pulse-stretch, or request/acknowledge scheme with a proven minimum spacing.
- Multi-bit data: handshake, Gray-coded pointer, or asynchronous FIFO. Never synchronize bits independently.
- Reset: assert/deassert behavior must match the architecture; asynchronous deassertion requires reviewed synchronization.
- Constraints: exceptions identify explicit endpoints and never replace a CDC circuit.

## Output

For every crossing report source, destination, scheme, structural result, functional evidence, remaining assumptions, and status. Missing/inconclusive evidence is `BLOCKED`, not `PASS`.

References: `references/async_reg_guide.md`, `references/cdc_levels.md`, and `references/xpm_primitives.md`.
