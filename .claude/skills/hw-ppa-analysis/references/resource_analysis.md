# Resource attribution and comparison

Require a target part, source/configuration hashes, tool version, stage and utilization report. Record LUT, register, BRAM, URAM where supported, DSP and clock resources with both used/available and percentages. Missing rows are unknown, never zero.

Collect hierarchical utilization to find the dominant units. Reconcile hierarchy totals with the flat report; shared or optimized logic may prevent additive accounting. Inspect inferred memories, DSPs and large muxes before proposing an implementation change.

Compare matching functionality, numeric width, parameters, throughput, latency and constraints. Post-synthesis and routed measurements have different meanings. Device utilization has no universal 90% failure threshold; use declared budgets and congestion/timing evidence.

For actionable experiments use fpga-resource-optimization and the existing optimization experiment contract. Report absolute values, deltas, guardrails and rejected candidates; retain evidence hashes and stage labels.
