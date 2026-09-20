# VibeSilicon agent entry point

VibeSilicon supports FPGA and ASIC work through four roles and evidence-based gates.

## Roles

- `architect-fpga`: turns requirements into interfaces, clock/reset domains, data flow, memory architecture, numeric contracts, budgets, and verification plans.
- `coder-fpga`: implements the smallest reviewed RTL or HLS change and runs the required local gates.
- `reviewer-fpga`: independently checks architecture, RTL, CDC, formal, timing, PPA, and evidence. It does not modify the design under review.
- `orchestrator-fpga`: selects the target flow, enforces dependencies, and stops on missing evidence or approval.

## Required project inputs

Every project must declare:

1. target flow: `fpga`, `asic`, or `both`;
2. functional specification and fixed-point/numeric contract;
3. interfaces, clocks, resets, throughput, latency, and backpressure;
4. source manifest and top module;
5. golden model and verification vectors where applicable;
6. FPGA device/constraints or external ASIC PDK view manifest;
7. PPA targets and non-regression limits;
8. ownership, third-party license status, and required human approvals.

Use `docs/new_project_inputs.md` and the files under `templates/`.

## Non-negotiable rules

- Do not invent or silently change numeric widths, scaling, clock constraints, or protocol behavior.
- Keep synthesizable logic separate from technology-specific memory wrappers. Infer generic memory only when the target flow supports it; otherwise instantiate a reviewed wrapper behind a neutral interface.
- Keep golden models and accepted test vectors read-only during implementation.
- Do not treat missing tools, skipped checks, inconclusive formal runs, or absent evidence as PASS.
- Do not expose arbitrary shell commands, unrestricted Tcl, Python evaluation, or network access through an agent tool.
- Do not commit PDKs, EDA licenses, generated vendor IP, customer assets, personal paths, credentials, bitstreams, checkpoints, GDS, or raw run directories.
- Architecture, reset/CDC exceptions, security-sensitive logic, PDK selection, and production sign-off require independent human review.

## Flow selection

- FPGA: architecture → RTL/HLS → G0 manifest → G1 static/readability → G2 simulation/protocol/formal as applicable → synthesis/implementation → hardware validation.
- ASIC: architecture → RTL → G0/G1/G2 → reviewed PDK input evidence → synthesis/STA → physical flow → DRC/LVS evidence → PPA report → sign-off handoff.
- Both: maintain one behavioral/numeric contract, but use separate target manifests, constraints, memory wrappers, evidence, and acceptance decisions.

## Canonical assets

- Skills: `skills/`
- Agent contracts: `subagents/`
- MCP servers: `mcp/`
- Quality gates and adapters: `scripts/`
- Schemas and policies: `schemas/`, `config/`
- Project templates: `templates/`

Only claim results supported by the current run's content-addressed evidence.
