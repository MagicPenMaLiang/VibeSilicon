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

1. Start from AGENTS.md and docs/new_project_inputs.md. Assign architect-fpga, coder-fpga, reviewer-fpga and orchestrator-fpga contracts; do not introduce a second role hierarchy.

2. Architecture precedes implementation. Then G0 manifest, G1 static/readability, G2 simulation/protocol/formal, synthesis and implementation, followed by declared hardware validation.

3. Route constraint issues to fpga-constraints, lint to fpga-lint-triage, simulation to fpga-simulation, coverage to fpga-coverage, CDC to fpga-cdc-check, timing diagnosis to fpga-dcp-analysis.

4. Route reviewed optimization to fpga-timing-closure, fpga-resource-optimization or fpga-power-optimization. Preserve their baselines and rollback criteria.

5. Collect implementation evidence with the fixed collect_reports MCP tool or scripts/fpga_reports.py. Route hardware to fpga-programming/fpga-ila-debug/fpga-soc-bringup only after declared targets and human review.

6. Stop at missing evidence or approvals. Keep separate FPGA/ASIC manifests and acceptance; software tests, dry plans and implementation reports never stand in for hardware or production sign-off.

## Evidence and handoff

Bind conclusions to current source/configuration, tool version and artifact hashes. Return PASS, FAIL or BLOCKED for each declared check, with assumptions and the next owner. Keep golden inputs read-only and preserve independent review boundaries.
