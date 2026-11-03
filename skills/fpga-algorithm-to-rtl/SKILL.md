---
name: fpga-algorithm-to-rtl
description: Map an immutable algorithm into a streaming or scheduled FPGA RTL architecture, with explicit numeric stages, storage access schedules and golden-to-RTL verification. Use before writing algorithmic RTL; HLS is an optional separately selected route.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: architecture
  routes: [fpga]
---

# Algorithm to RTL

Use the existing architect, coder, reviewer and orchestrator contracts. This is
the FPGA path; ASIC and dual-target acceptance remain governed by AGENTS.md.

1. Freeze the algorithm, numeric specification and vector dependency manifests.
   Do not execute model code through an MCP evaluation tool. Inventory operations,
   casts, state, loop bounds, array access and input/output ordering before selecting
   parallelism. Floating-point code requires a reviewed integer/fixed-point
   reference before making bit-exact RTL claims.
2. Map each operation to a named RTL stage and each stored value to a memory
   wrapper. Specify accepted-token enables, alignment, latency, stalls and reset
   for both data and sidebands. Read `references/streaming_architecture.md` for
   reductions, windows, memory banking and elastic channels.
3. Check candidate arithmetic with `python -m scripts.fpga_feasibility PLAN.json
   --root PROJECT_ROOT`, using `templates/fpga_feasibility.json.tpl` and its schema.
   REJECTED stops that candidate. CANDIDATE only means declared estimates fit;
   it does not approve architecture, achieve timing or prove a storage schedule.
4. Record the mapping in the hw-microarch template and obtain the existing
   independent architecture review before implementation. Hand the coder a source
   manifest/top, frozen numeric table, port-by-cycle memory schedule and tests.
5. Implement synthesizable RTL through rtl-implementation/rtl-design. Compare
   accepted output transactions against the frozen reference, including extrema,
   ties, casts, reset and randomized stalls. Use rtl-simulation and existing
   G0/G1/G2 contracts; cycle alignment is checked separately from numeric equality.

Use handwritten RTL by default on this FPGA path. If the project explicitly
selects HLS or an HLS sub-block, retain this behavioral contract and consult
`skills/rtl-implementation/references/hls_diagnosis.md`. Do not replace the direct RTL
path with a compulsory HLS baseline or HLS-generated module.
