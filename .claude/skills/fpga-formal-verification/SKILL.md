---
name: fpga-formal-verification
description: Select an appropriate equivalence or property-proof mode and evaluate whether formal evidence is sufficient for the claimed RTL change.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: verification
  routes: [fpga, asic, both]
---

# Formal verification

Use for refactoring, pipeline changes, state-machine changes, protocol logic, reset behavior, CDC control, and optimization candidates.

## Select a proof

- Combinational equivalence for purely combinational rewrites.
- Sequential equivalence with explicit latency/state mapping for pipelined or retimed designs.
- Assertions for protocol, safety, progress, FIFO, arbitration, and reset invariants.
- Bounded proof only when the claimed scope explicitly ends at the bound.
- Induction or complete proof when an unbounded claim is required.

## Evidence requirements

Bind tool version, design/config hashes, top, clocks/resets, assumptions, black boxes, depth, cover/vacuity checks, solver status, and counterexample artifacts. Tool unavailable, timeout, unknown, vacuous proof, or an unreviewed black box is `BLOCKED` or `INCONCLUSIVE`.

See `references/proof_modes.md`.
