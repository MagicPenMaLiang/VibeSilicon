---
name: fpga-power-optimization
description: Optimize FPGA power using explicit activity assumptions and controlled experiments that preserve clocks, reset, latency and throughput.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: optimization
  routes: [fpga]
---

# power optimization

Repository paths below are relative to the VibeSilicon project root. Read AGENTS.md before acting.

## Procedure

1. Require baseline power evidence with activity provenance, voltage, temperature, part, tool, stage and operating mode. A vectorless estimate is not a measured board result.

2. Find high-activity clocks, datapaths, unnecessary switching and duplicated storage. Evaluate clock enables or operand isolation only under the declared protocol/numeric contract.

3. Do not gate FPGA fabric clocks with combinational logic. Use reviewed technology clock-control wrappers where needed; ASIC clock gating belongs to its separate target flow.

4. Use scripts/optimization_experiment.py with matched activity/corner assumptions and timing/resource/functional guardrails. Test wakeup, idle transitions, reset and backpressure.

5. Report static/dynamic contributions, uncertainty, activity coverage and absolute/delta values. Incomplete activity evidence blocks a strong power claim; declared estimates must remain labeled.

## Evidence and handoff

Bind conclusions to current source/configuration, tool version and artifact hashes. Return PASS, FAIL or BLOCKED for each declared check, with assumptions and the next owner. Keep golden inputs read-only and preserve independent review boundaries.
