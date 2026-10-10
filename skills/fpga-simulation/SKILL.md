---
name: fpga-simulation
description: Bring up and diagnose bounded RTL simulation using project manifests, self-checking testbenches and preserved execution logs.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: verification
  routes: [fpga]
---

# simulation

Repository paths below are relative to the VibeSilicon project root. Read AGENTS.md before acting.

## Procedure

1. Require immutable golden vectors, the RTL manifest and a separate testbench contract. Check top, compile order, includes, defines, timescale, reset polarity and tool/version availability before launching.

2. Run the repository directed smoke gate first. For persistent logs and line coverage use python -m scripts.quality_gate.rtl_coverage with a declared coverage contract.

3. Classify elaboration, compile, initialization, protocol, numeric mismatch and timeout failures from the first causal diagnostic. Reduce one failure without changing the golden reference.

4. Check reset release, clock edges, unknown states and scoreboard alignment before changing arithmetic. Preserve vector/source hashes, commands, exit codes and logs for each run.

5. Stop only processes owned by the adapter; never kill all simulator processes. Return a minimal reproducer and failure category. Directed smoke is limited evidence, not full verification or hardware validation.

## Evidence and handoff

Bind conclusions to current source/configuration, tool version and artifact hashes. Return PASS, FAIL or BLOCKED for each declared check, with assumptions and the next owner. Keep golden inputs read-only and preserve independent review boundaries.
