---
name: fpga-flow
description: Orchestrate FPGA evidence gates and route focused skills from requirements through implementation and optional hardware validation.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: orchestration
  routes: [fpga]
---

# flow

Repository paths below are relative to the VibeSilicon project root. Read AGENTS.md before acting.

## Procedure

1. Start from hw-flow, AGENTS.md and docs/new_project_inputs.md. Use architect-hw, coder-rtl, reviewer-hw and orchestrator-hw contracts; do not introduce a second role hierarchy. Route ASIC stages to asic-flow rather than loading FPGA tools for them.

2. The default FPGA route is algorithm -> reviewed microarchitecture -> handwritten RTL -> G0 manifest -> G1 static/readability -> G2 simulation/protocol/formal -> synthesis/implementation -> declared hardware validation. Use fpga-algorithm-to-rtl for operation/stage/storage mapping and cheap feasibility checks. HLS is an explicitly selected alternative or sub-block, not a prerequisite. ASIC and both retain their separate target flows in AGENTS.md.

3. Route constraint issues to fpga-constraints, lint to rtl-lint, simulation to rtl-simulation, coverage to rtl-coverage, CDC to rtl-cdc, timing diagnosis to fpga-dcp-analysis.

   Use the configured native execution backend. For a request outside its fixed
   tools, consult docs/ross_backend_coverage.md before proposing an adapter.
   Original Ross skill names or internal backend methods do not establish a
   callable MCP capability; do not install or switch execution servers implicitly.

   Across the FPGA stages, use fpga-doc-search with the separate amd-doc-search
   MCP service for release-sensitive command/IP semantics and known issues.
   Preserve citations and verify relevance/edition; a lookup does not require
   an EDA session and is not a mandatory gate for unrelated RTL or ASIC work.

4. Route reviewed optimization to fpga-timing-closure, fpga-resource-optimization or fpga-power-optimization. Preserve their baselines and rollback criteria.

5. Collect implementation evidence with the fixed collect_reports MCP tool or scripts/fpga_reports.py. Route hardware to fpga-programming/fpga-ila-debug/fpga-soc-bringup only after declared targets and human review. Route Linux/FPGA video jitter, frame loss, deadline failures and non-converging video campaigns to fpga-realtime-video-debug; keep harness and evidence failures separate from video results.

6. Stop at missing evidence or approvals. Keep separate FPGA/ASIC manifests and acceptance; software tests, dry plans and implementation reports never stand in for hardware or production sign-off.

For Vivado project/IP reproduction and requirement-to-parameter readback, read
`references/vivado_reproduction.md`. For optimization-log attribution use the
read-only analyze_opt_log MCP tool; pass evidence to fpga-dcp-analysis before
choosing any RTL, constraint or strategy change.

## Evidence and handoff

Bind conclusions to current source/configuration, tool version and artifact hashes. Return PASS, FAIL or BLOCKED for each declared check, with assumptions and the next owner. Keep golden inputs read-only and preserve independent review boundaries.
