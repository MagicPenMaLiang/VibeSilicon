---
name: fpga-soc-bringup
description: Plan Zynq PS7 or MPSoC bring-up from reviewed board presets and initialization evidence, distinguishing implementation checks from DDR and boot validation.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: hardware
  routes: [fpga]
---

# soc bringup

Repository paths below are relative to the VibeSilicon project root. Read AGENTS.md before acting.

## Procedure

1. Require the declared ps7 or mpsoc family, compatible part, reviewed preset hash, clock/reset/address/interface contract and software/initialization provenance.

2. Use scripts/fpga_board.py validate-soc for a bounded input checklist. The initial adapter validates a plan; it does not manufacture a board preset, FSBL, device tree or processing-system configuration.

3. PS7 and MPSoC use different initialization and boot flows. Check board oscillator, DDR topology, pin assignments and reset sequencing against board documentation; DRC cannot prove DDR electrical parameters.

4. Before application testing establish JTAG identity, image provenance, serial boot logs and the correct reviewed PS initialization. Verify DDR with a board memory test and preserve observed results.

5. Then test peripheral addresses, interrupts, DMA/cache coherency, PL clocks and reset recovery. Report each stage separately, with BLOCKED for absent evidence. Hardware and production sign-off require independent human review.

If platform/application/boot packaging is required, read
`references/software_boot_handoff.md` before connecting software artifacts to the
board plan. This is an optional SoC branch; the adapter remains input preflight.

## Evidence and handoff

Bind conclusions to current source/configuration, tool version and artifact hashes. Return PASS, FAIL or BLOCKED for each declared check, with assumptions and the next owner. Keep golden inputs read-only and preserve independent review boundaries.
