---
name: fpga-lint-triage
description: Triage RTL lint diagnostics by correctness risk and repair the smallest reviewed issue while preserving interfaces and numeric behavior.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: verification
  routes: [fpga]
---

# lint triage

Repository paths below are relative to the VibeSilicon project root. Read AGENTS.md before acting.

## Procedure

1. Require the declared source manifest, tool version, diagnostics and accepted numeric/interface contracts. Run python -m scripts.quality_gate.rtl_project_lint for the existing bounded lint flow.

2. Group by cause: unintended latch or multiple driver, width/sign/truncation, reset and unused state, then style. Map every diagnosis to a source location and a concrete behavioral risk.

3. Inspect signedness and expression sizing before extending, slicing or casting. Check whether unused logic signals a disconnected interface. Never shrink widths merely to eliminate a warning.

4. Repair one cause, rerun lint and the relevant numeric/protocol simulation. Use formal comparison for behavior-preserving changes where applicable.

5. Waivers need a scoped justification, owner and expiry through the existing waiver policy. Return original diagnostics, change, verification and unresolved findings; missing tools or suppressed checks cannot pass.

## Evidence and handoff

Bind conclusions to current source/configuration, tool version and artifact hashes. Return PASS, FAIL or BLOCKED for each declared check, with assumptions and the next owner. Keep golden inputs read-only and preserve independent review boundaries.
