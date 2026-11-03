---
name: fpga-ila-debug
description: Plan and execute bounded FPGA ILA captures against an exact reviewed device and matching bitstream/probe artifacts.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: hardware
  routes: [fpga]
---

# ila debug

Repository paths below are relative to the VibeSilicon project root. Read AGENTS.md before acting.

## Procedure

1. Require a board target manifest, exact target/device identities, part, matching bitstream/LTX hashes and debug-core/probe contract. Build the capture request using scripts/fpga_board.py; preview before execution.

2. First state an observable hypothesis, sampling clock and required signals. Select one named ILA core and fixed immediate capture; the initial adapter does not accept arbitrary Tcl trigger expressions.

   If probes are missing or instrumentation changes timing, read
   `references/instrumentation.md` before preparing a new reviewed image.

3. Check hardware identity, programmed image provenance and probe correspondence before arming. Existing unknown device contents cannot be certified merely by loading an LTX file; program the matched bitstream in the approved capture transaction.

4. Bound sample depth, timeout and exclusive board ownership. Preserve the CSV/waveform hash and device/run identity; do not modify unrelated targets or kill other sessions.

5. Capture shows sampled signals, not complete CDC or timing proof. Return capture status, sample clock assumptions, artifacts and a reproducible next test.

## Evidence and handoff

Bind conclusions to current source/configuration, tool version and artifact hashes. Return PASS, FAIL or BLOCKED for each declared check, with assumptions and the next owner. Keep golden inputs read-only and preserve independent review boundaries.
