---
name: fpga-ip-design
description: Implement fixed-point RTL or HLS from a reviewed architecture while preserving numeric behavior, interfaces, latency, throughput and verification contracts.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: implementation
  routes: [fpga, asic, both]
---

# IP implementation

## Before coding

Require the reviewed specification, numeric contract, interface/clock/reset contract, source manifest, test vectors, PPA budget, and signed architecture.

## Implementation rules

- Map widths and signedness explicitly; never choose a new quantization silently.
- Make truncation, rounding, saturation, and overflow visible and testable.
- Preserve ready/valid, ordering, backpressure, and reset behavior.
- Keep control/compute logic separate from inferred memory and technology-specific memory wrappers.
- Parameterize reusable blocks without allowing illegal configurations.
- Add HLS pragmas only with an expected scheduling/resource effect and a validation plan.
- Keep generated RTL provenance and do not hand-edit generated files without changing their ownership classification.

## Completion

Run G0/G1 and applicable G2 gates, compare outputs bit-exactly or within the reviewed tolerance, and report resource/timing deltas against the budget. Three failed iterations require escalation rather than threshold relaxation.

References: `references/bit_width_mapping.md`, `references/pragma_cheatsheet.md`, and `references/hls_templates/`.
