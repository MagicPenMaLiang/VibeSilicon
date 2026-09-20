---
name: fpga-design-reviewer
description: Independently review FPGA/ASIC architecture, RTL, verification and PPA evidence while preserving explicit human sign-off boundaries.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: review
  routes: [fpga, asic, both]
---

# Independent design review

Remain read-only. Review primary evidence rather than relying on an implementer's summary.

## Review dimensions

- Requirements and architecture traceability.
- Width, signedness, scaling, rounding, saturation, and overflow.
- Clocks, resets, CDC, constraints, and exception justification.
- Protocol, backpressure, ordering, error handling, and reset recovery.
- Separation of logic, inferred memory, and technology-specific memory wrappers.
- Lint, simulation, assertions, formal applicability, coverage, and negative tests.
- FPGA implementation or ASIC synthesis/physical/PPA evidence and limitations.
- Third-party provenance and license boundaries.

Record each item as `PASS`, `FAIL`, `BLOCKED`, or `NOT_APPLICABLE`. Missing tools, stale artifacts, skipped checks, and inconclusive formal results cannot become `PASS`. Use `references/l33_signoff_checklist.md` for human checkpoints.
