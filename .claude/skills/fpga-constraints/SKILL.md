---
name: fpga-constraints
description: Author and review FPGA clocks, IO delays and timing exceptions from a declared interface contract; diagnose unconstrained paths and exception precedence.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: constraints
  routes: [fpga]
---

# constraints

Repository paths below are relative to the VibeSilicon project root. Read AGENTS.md before acting.

## Procedure

1. Require the part, board IO specification, clock/reset inventory, source manifest and reviewed timing contract. Missing IO timing or clock relationships blocks authoring; never invent numbers.

2. Inventory primary/generated clocks and explicit ports. Set min/max input/output delays from board budgets, including hold and external device requirements. Check selector hit counts before applying an exception.

3. Classify synchronous, asynchronous and exclusive relationships. For asynchronous FIFO pointer paths that require bounded delay, a blanket asynchronous clock group can override the intended max-delay constraint. Select a reviewed compatible policy and inspect effective exceptions.

4. Run check_timing, report_clocks, report_clock_interaction, report_exceptions and setup/hold summaries. Identify uncovered endpoints; positive WNS alone does not prove constraint completeness.

5. Use fpga-cdc-check for crossing correctness. Architecture and CDC/reset exceptions retain independent human review. Return proposed XDC, contract traceability, selector counts, effective constraints and unresolved assumptions.

## Evidence and handoff

Bind conclusions to current source/configuration, tool version and artifact hashes. Return PASS, FAIL or BLOCKED for each declared check, with assumptions and the next owner. Keep golden inputs read-only and preserve independent review boundaries.
