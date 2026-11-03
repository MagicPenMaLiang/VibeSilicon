---
name: asic-flow
description: Coordinate the repository ASIC PDK, synthesis/STA, physical, DRC/LVS and PPA evidence chain. Use for an ASIC project or the ASIC branch of a dual-target project.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: orchestration
  routes: [asic, both]
---

# ASIC workflow

Start with hw-flow, repository-root `AGENTS.md` and `docs/new_project_inputs.md`.
Use the same four hardware roles. Keep design/PDK inputs and raw runs external;
retain only permitted sanitized metadata and artifact hashes in this repository.

| Stage | Skill | Existing adapter |
|---|---|---|
| Shared architecture and RTL verification | hw-microarch, rtl-implementation, rtl-lint, rtl-simulation, rtl-coverage, rtl-cdc, rtl-formal | G0/G1 and applicable G2 |
| Backend and PDK intake, A01 | asic-pdk-intake | scripts.asic_backend_contract, scripts.asic_input_evidence |
| Combined synthesis/STA, A02 | asic-synthesis, asic-sta | scripts.asic_synth_sta_adapter |
| Physical run, A03 | asic-physical-design | scripts.asic_physical_artifact |
| DRC/LVS and A03 finalization | asic-drc-lvs | scripts.asic_physical_artifact, scripts.asic_signoff_localization |
| PPA | asic-ppa | scripts.asic_ppa_report |
| Review and reproduction handoff, A04 where applicable | asic-signoff-handoff, hw-design-review | scripts.asic_reproduction_acceptance |

The A02 adapter runs Yosys synthesis and OpenROAD STA together. Two skill names
do not imply independently executable synthesis and STA backends. Inspect each
module's `--help` before constructing a command. Bind backend contract,
capabilities, input evidence, stage-specific approval and tool provenance;
`--authorize-local-execution` is an execution input, not an approval substitute.
Capability discovery reports availability, not design qualification.

Require current RTL verification before downstream claims. Preserve failed
timing, DRC and LVS results even if a process completed and emitted files.
Do not generalize the fixed A04 reference profile to arbitrary designs/PDKs.
Commercial EDA, generic MMMC closure, DFT/ATPG, UPF and foundry-qualified signoff
are not supplied by this workflow. Record required unsupported scope as BLOCKED
or hand it to an explicitly reviewed external flow.

Use `docs/asic_ppa.md` and `docs/project_map.md` for contracts and limitations.
