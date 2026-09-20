---
name: fpga-ppa-analysis
description: Analyze FPGA performance, power, area/resources and ASIC PPA evidence without comparing incompatible configurations.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: analysis
  routes: [fpga, asic, both]
---

# PPA analysis

## Evidence normalization

Bind every measurement to design/config hashes, tool version, target, constraints, corner, stage, and source report. FPGA resource and ASIC area are different quantities and must not be combined into one score.

## FPGA

Report LUT, FF, DSP, block/ultra memory, clock resources, WNS/TNS, achieved frequency, estimated/measured power, congestion, and implementation status.

## ASIC

Report cell area/count, macro area, WNS/TNS and violating endpoints by corner, clock assumptions, parasitic stage, power activity source, leakage/internal/switching power, utilization, DRC/LVS status, and whether the flow is sign-off capable.

## Comparison rules

- Compare only equivalent functionality, vectors, constraints, corners, and tool settings.
- Show absolute metrics, deltas, guardrails, and uncertainty.
- Do not hide failed or cancelled candidates.
- A Pareto result is a decision aid, not production sign-off.

References: `references/resource_analysis.md`, `references/timing_analysis.md`, and `references/power_analysis.md`.
