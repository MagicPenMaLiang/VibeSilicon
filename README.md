# VibeSilicon

VibeSilicon is an open, evidence-driven toolkit for agent-assisted FPGA and ASIC engineering. It combines reusable engineering skills, constrained MCP tool adapters, RTL quality gates, verification contracts, and ASIC PPA reporting without embedding a specific product design or proprietary process kit.

## Quick install

```bash
git clone https://github.com/MagicPenMaLiang/VibeSilicon.git
cd VibeSilicon
./scripts/setup_env.sh        # Linux, macOS, WSL
# scripts\setup_env.cmd       # Windows cmd
# pwsh -File scripts\setup_env.ps1   # Windows PowerShell
```

The wrapper creates `.venv`, installs locked dependencies, runs the import
smoke, the unit-test suite, and probes seven optional EDA tools on `PATH`.
Use `--json` for a machine-readable report, `--audit` to opt in to the
source-tree gate. See [docs/setup_env.md](docs/setup_env.md) for the full
exit code table.

## What is included

- Four shared hardware roles: architect-hw, coder-rtl, reviewer-hw and orchestrator-hw, with previous role names retained as compatibility aliases.
- 31 canonical skills: 11 shared hardware/RTL skills, 12 FPGA-specific skills and 8 ASIC-specific skills. Ten previous skill names remain compatibility entries, for 41 discoverable entries in total.
- Local MCP servers for Python simulation, Vitis HLS, and Vivado, plus the separate hosted AMD documentation search service.
- Deterministic RTL manifest, lint, readability, waiver, protocol, and smoke-test gates.
- ASIC synthesis, STA, physical-flow evidence, and PPA report contracts.
- Templates and schemas for starting a new FPGA or ASIC project.

## What is not included

- Customer or product RTL, specifications, golden models, PDK files, or test data.
- EDA binaries, license files, generated IP, bitstreams, checkpoints, GDS, or rule decks.
- Private runner configuration, machine inventory, approval records, or local paths.
- Results that claim production sign-off. VibeSilicon structures evidence; qualified engineers retain sign-off authority.

## Quick start

Requirements: Python 3.10–3.12. Verilator, Yosys/SymbiYosys, Vivado, Vitis HLS, OpenROAD, and KLayout are optional and only required for the flows that use them.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python scripts/public_release_audit.py
python -m unittest discover -s tests -p "test_*.py"
```

Or run the cross-platform wrapper that does the same plus optional EDA probing
and emits a stable exit code:

```bash
scripts/setup_env.sh                # Linux, macOS, WSL
scripts/setup_env.cmd               # Windows cmd
pwsh -File scripts\setup_env.ps1    # Windows PowerShell
python scripts/setup_env_core.py --json   # direct, CI-friendly
```

See [docs/setup_env.md](docs/setup_env.md) for the full exit code table.

Create a project outside this repository or copy the neutral templates into a new directory. Start with [docs/new_project_inputs.md](docs/new_project_inputs.md).

## Core workflows

Start with `hw-flow` and select `fpga`, `asic`, or `both`. Shared architecture,
RTL and verification use `hw-*` and `rtl-*`; implementation stages use
`fpga-flow` or `asic-flow`. See [project map](docs/project_map.md) for roles,
the complete skill classification, tools, evidence limits and migration mapping.

The default FPGA path is algorithm -> reviewed microarchitecture -> handwritten
RTL -> simulation/verification -> synthesis/implementation -> hardware validation.
HLS is an explicitly selected alternative or sub-block. Start with
`fpga-algorithm-to-rtl` and the cheap `python -m scripts.fpga_feasibility` planning
check before an expensive FPGA build. ASIC and dual-target flows retain their
separate contracts. See [FPGA upstream adoption](docs/fpga_upstream_adoption.md)
for what was added, what remains a playbook, and what is outside the current scope.

The native Vivado backend remains the execution default. It covers selected
tasks, not the full official Ross MCP interface; see
[backend coverage and selection](docs/ross_backend_coverage.md). Useful Ross FPGA
practices are adapted into existing skills without requiring its execution server.

### RTL project gate

```bash
python -m scripts.quality_gate.rtl_project_gate path/to/rtl_project_manifest.json
```

The gate validates the selected source manifest, performs configured lint/readability checks, verifies waivers, and records machine-readable evidence. A skipped or unavailable required tool is not reported as PASS.

### ASIC PPA flow

The ASIC adapters consume a reviewed manifest and external PDK views. They emit content-addressed synthesis, STA, physical-flow, and PPA evidence. PDK and design assets remain outside the repository. See [docs/asic_ppa.md](docs/asic_ppa.md).

Start with `asic-flow`; focused skills cover PDK intake, synthesis, STA,
physical design, DRC/LVS, PPA and signoff handoff. These skills route existing
CLI adapters; no ASIC MCP server or foundry-qualified signoff flow is implied.

### FPGA report, coverage and board adapters

Use the fixed `collect_reports` Vivado MCP tool for a source-bound DCP report
bundle and `python -m scripts.quality_gate.rtl_coverage` for declared Verilator
line coverage with preserved logs. Board requests default to preview and require
exact device/artifact binding plus external operation-specific approval for
execution. PS7/MPSoC support currently validates bring-up inputs; board checks
remain explicit. See [docs/fpga_skill_rollout.md](docs/fpga_skill_rollout.md).

### Agent integrations

The FPGA roles share `fpga-doc-search` through the remote `amd-doc-search`
service. It searches release-specific documentation without starting EDA; results
still require relevance and edition checks. Reload the client's MCP configuration
after adding it. See [FPGA documentation service](docs/fpga_documentation_service.md)
for client setup, live validation and limitations. ASIC work does not require it.

Canonical instructions live in `AGENTS.md`, `skills/`, and `subagents/catalog.json`.
The catalog generates readable role contracts and Claude Code, Codex and OpenCode
role adapters. Target-specific skills are loaded after intake; ASIC routing has
no Vivado, Vitis or AMD documentation dependency. MCP configuration uses environment
variables or commands available on `PATH`; no machine-specific path is committed.

Native Codex/Claude skill copies include the complete supporting resources.
Run `python scripts/sync_skills.py --write` after canonical edits, followed by
`--check`; CI rejects missing or divergent resources.
After role-catalog edits, run `python -m scripts.sync_agents --write`, followed
by `--check`. Preview any role/target without executing EDA:

```bash
python -m scripts.sync_agents --plan orchestrator-hw --target asic
python -m scripts.sync_agents --plan coder-fpga --target both
```

## Security model

- Tool calls are bounded to a declared project root.
- Arbitrary shell, Python evaluation, remote fetch, and unconstrained Tcl are not exposed.
- High-risk operations require explicit human approval and attributable evidence.
- Proprietary inputs and tool licenses stay outside version control.

Read [SECURITY.md](SECURITY.md) before attaching a licensed EDA installation or a self-hosted runner.

## Status

Before updating GitHub, follow [release preparation](docs/release_preparation.md)
to audit publishable source and prepare a hash-bound snapshot without copying local
designs or changing the Git index.

This public repository is an alpha distribution. Open-source CI validates portable contracts and pure-Python behavior; it does not constitute FPGA hardware validation or ASIC sign-off.

## License

Apache License 2.0. See [LICENSE](LICENSE). Third-party tools and dependencies retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
