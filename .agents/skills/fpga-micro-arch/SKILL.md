---
name: fpga-micro-arch
description: Convert reviewed requirements into an FPGA/ASIC microarchitecture before RTL or HLS implementation begins.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: architecture
  routes: [fpga, asic, both]
---

# Microarchitecture design

## Required sections

1. Interfaces, protocols, clock/reset domains, and CDC boundaries.
2. Dataflow graph, pipeline stages, latency, throughput, and backpressure.
3. Numeric contract for every boundary and arithmetic stage.
4. Memory hierarchy, ports, latency, collision behavior, and technology wrapper boundary.
5. RTL/HLS partition and implementation strategy.
6. Resource/area, frequency, power, and bandwidth budget.
7. Verification plan covering nominal, boundary, reset, error, and stress behavior.

## Target separation

When one IP targets FPGA and ASIC, share behavioral contracts only. Maintain separate memory wrappers, constraints, tool manifests, PPA budgets, and target evidence. Do not translate FPGA initialization or vendor primitive behavior into an ASIC assumption.

## Exit criteria

Coding begins only after an independent reviewer approves interfaces, numeric behavior, clock/reset strategy, memory semantics, target split, and acceptance criteria.

References: `references/algorithm_profiling.md`, `references/axi4_lite_slave.md`, `references/register_file_pattern.md`, `references/rtl_fsm_design.md`, and `templates/micro_arch_template.md`.
