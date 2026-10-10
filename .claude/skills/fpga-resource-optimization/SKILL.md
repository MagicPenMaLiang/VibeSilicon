---
name: fpga-resource-optimization
description: Reduce FPGA resource use through measured hierarchy hotspots and bounded experiments while preserving numeric, throughput and timing contracts.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: optimization
  routes: [fpga]
---

# resource optimization

Repository paths below are relative to the VibeSilicon project root. Read AGENTS.md before acting.

## Procedure

1. Require normalized utilization and timing evidence, hierarchy attribution, allowed files and non-regression budgets. Use fpga-ppa-analysis before selecting a change.

2. Classify replicated arithmetic, failed RAM/DSP inference, wide control, mux depth or over-buffering. Prefer sharing, reviewed memory wrappers or changed scheduling only when latency and throughput permit.

3. Use scripts/optimization_experiment.py with one hypothesis, baseline hashes, objectives, guardrails and automatic rollback. Do not infer universally acceptable utilization percentages.

4. Preserve width, rounding, overflow, reset and backpressure. Numeric or architectural changes need reviewed contracts; area savings alone do not authorize them.

5. Compare compatible post-synthesis and post-route results separately. Return accepted/rejected/inconclusive candidates, resource deltas, functional evidence and timing/power regressions.

## Evidence and handoff

Bind conclusions to current source/configuration, tool version and artifact hashes. Return PASS, FAIL or BLOCKED for each declared check, with assumptions and the next owner. Keep golden inputs read-only and preserve independent review boundaries.
