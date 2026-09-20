# VibeSilicon

VibeSilicon is an open, evidence-driven toolkit for agent-assisted FPGA and ASIC engineering. It combines reusable engineering skills, constrained MCP tool adapters, RTL quality gates, verification contracts, and ASIC PPA reporting without embedding a specific product design or proprietary process kit.

## What is included

- Agent roles for architecture, implementation, review, and workflow orchestration.
- Skills for RTL/HLS design, CDC, formal verification, timing closure, and PPA analysis.
- MCP servers for Python simulation, Vitis HLS, and Vivado.
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

Create a project outside this repository or copy the neutral templates into a new directory. Start with [docs/new_project_inputs.md](docs/new_project_inputs.md).

## Core workflows

### RTL project gate

```bash
python -m scripts.quality_gate.rtl_project_gate path/to/rtl_project_manifest.json
```

The gate validates the selected source manifest, performs configured lint/readability checks, verifies waivers, and records machine-readable evidence. A skipped or unavailable required tool is not reported as PASS.

### ASIC PPA flow

The ASIC adapters consume a reviewed manifest and external PDK views. They emit content-addressed synthesis, STA, physical-flow, and PPA evidence. PDK and design assets remain outside the repository. See [docs/asic_ppa.md](docs/asic_ppa.md).

### Agent integrations

Canonical instructions live in `AGENTS.md`, `skills/`, and `subagents/`. Thin adapters are provided for Claude Code, Codex, and OpenCode. MCP configuration uses environment variables or commands available on `PATH`; no machine-specific path is committed.

## Security model

- Tool calls are bounded to a declared project root.
- Arbitrary shell, Python evaluation, remote fetch, and unconstrained Tcl are not exposed.
- High-risk operations require explicit human approval and attributable evidence.
- Proprietary inputs and tool licenses stay outside version control.

Read [SECURITY.md](SECURITY.md) before attaching a licensed EDA installation or a self-hosted runner.

## Status

This public repository is an alpha distribution. Open-source CI validates portable contracts and pure-Python behavior; it does not constitute FPGA hardware validation or ASIC sign-off.

## License

Apache License 2.0. See [LICENSE](LICENSE). Third-party tools and dependencies retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
