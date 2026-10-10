---
name: fpga-programming
description: Prepare and execute reviewed FPGA volatile programming or configuration-memory operations with exact device matching and explicit artifact approval.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: hardware
  routes: [fpga]
---

# programming

Repository paths below are relative to the VibeSilicon project root. Read AGENTS.md before acting.

## Procedure

1. Require exact hardware target/device names, part, artifact hash, local hardware server and an approval bound to the entire request. Use scripts/fpga_board.py; defaults produce a preview only.

2. Volatile program and nonvolatile flash are separate operations and approvals. Flash requires the declared configuration-memory part and a pre-generated reviewed MCS; do not derive offsets or flash geometry.

3. Acquire the exclusive repository board lock, refresh devices and demand exactly one matching target and part. Never pick the first connected target or silently retry a different device.

4. Recheck artifacts/approval immediately before executing. Native batch execution uses only generated fixed Tcl; no arbitrary commands, network endpoints or Python evaluation enter the request.

5. Flash performs program plus tool verification. Tool success does not prove cold-boot behavior. Return execution evidence and pending readback/boot/application checks; no live operation is implied by adapter installation.

## Evidence and handoff

Bind conclusions to current source/configuration, tool version and artifact hashes. Return PASS, FAIL or BLOCKED for each declared check, with assumptions and the next owner. Keep golden inputs read-only and preserve independent review boundaries.
