---
name: fpga-dcp-analysis
description: Perform read-only diagnosis of a synthesis or routed FPGA checkpoint and bind timing conclusions to source reports and checkpoint hashes.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: analysis
  routes: [fpga]
---

# FPGA checkpoint analysis

This is a read-only diagnostic skill. It may open an existing checkpoint and generate timing, utilization, clock-interaction, and congestion reports. It must not edit RTL, constraints, runs, or the checkpoint.

## Procedure

1. Record checkpoint hash, tool version, target, constraints hash, and implementation stage.
2. Check WNS/TNS, unconstrained paths, clock interactions, path groups, and exception coverage.
3. Classify the dominant path as logic, routing, fanout, memory/DSP boundary, CDC, I/O, or constraint-related.
4. Separate measured facts from hypotheses and identify the minimum next diagnostic.
5. Hand any proposed RTL/XDC/strategy change to `fpga-timing-closure`.

Do not claim an exception is valid from timing reports alone. See `references/classification.md`.
