---
name: fpga-coverage
description: Close declared RTL coverage goals with supported backend metrics, source-bound evidence and reviewed exclusions without equating coverage with correctness.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: verification
  routes: [fpga]
---

# coverage

Repository paths below are relative to the VibeSilicon project root. Read AGENTS.md before acting.

## Procedure

1. Require a test plan, RTL manifest, simulation contract and explicit coverage scope/thresholds. Use schemas/rtl_coverage_contract.schema.json and python -m scripts.quality_gate.rtl_coverage.

2. The initial adapter supports Verilator line instrumentation only. Branch, toggle, FSM, assertion and functional coverage require a declared compatible backend; unsupported metrics are BLOCKED.

3. Attribute every uncovered point to untested behavior, unreachable behavior or instrumentation limitations. Add tests against the golden contract before considering exclusions.

4. Keep exclusions explicit and independently reviewed; the initial adapter accepts no user exclusions. Do not combine reports from different source hashes, parameters or tools.

5. Return hit/total counts by source and aggregate, execution logs and instrumented-point semantics. A coverage PASS means the declared line target was met by a successful test, not full G2 or sign-off.

## Evidence and handoff

Bind conclusions to current source/configuration, tool version and artifact hashes. Return PASS, FAIL or BLOCKED for each declared check, with assumptions and the next owner. Keep golden inputs read-only and preserve independent review boundaries.
