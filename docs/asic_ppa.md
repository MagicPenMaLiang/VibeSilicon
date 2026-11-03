# ASIC PPA reporting

The ASIC flow converts reviewed external inputs into traceable synthesis, timing, area, and power evidence. It does not redistribute a PDK and does not claim foundry sign-off.

Start with `hw-flow` and `asic-flow`. Use the shared architect-hw, coder-rtl,
reviewer-hw and orchestrator-hw roles. The focused ASIC skills map directly to
existing CLI adapters; they do not add an ASIC MCP server. See
[project map](project_map.md) for shared gates, role routing and capability gaps.

| Task | Skill | Adapter module |
|---|---|---|
| Backend and external PDK/design input | asic-pdk-intake | scripts.asic_backend_contract, scripts.asic_input_evidence |
| Combined synthesis/STA | asic-synthesis, asic-sta | scripts.asic_synth_sta_adapter |
| Physical implementation | asic-physical-design | scripts.asic_physical_artifact |
| DRC/LVS/finalization and diagnostics | asic-drc-lvs | scripts.asic_physical_artifact, scripts.asic_signoff_localization |
| Power/activity and PPA | asic-ppa | scripts.asic_ppa_report |
| Evidence and fixed-profile reproduction handoff | asic-signoff-handoff | scripts.asic_toolchain_provenance, scripts.asic_reference_signoff, scripts.asic_reproduction_acceptance |

Inspect each module with `python -m MODULE --help`. A02 combines synthesis and
STA; the two skill names do not create separate execution backends. Its aggregate
WNS/TNS contract is not complete setup/hold, constraint-completeness or MMMC
signoff. A03 run completion is distinct from DRC/LVS final acceptance. Localization
diagnostics can contain design names and coordinates and remain external.
The A04 reproduction profile is fixed to its reference design and PDK.

## Stages

1. Validate the external design/PDK manifest and license review metadata.
2. Bind the permitted backend capabilities and tool versions.
3. Run synthesis and STA with reviewed constraints and process corners.
4. Optionally run floorplan, placement, CTS, routing, DRC, GDS export, and LVS through a constrained backend.
5. Generate a PPA report that binds every metric to its source artifacts and assumptions.

## Required power disclosure

Power must identify the activity source, scope, time window, clock activity, vectorless defaults if used, and whether parasitics are pre-route or extracted. Power without this context is an estimate, not a comparable result.

## Required limitations

- Open-source DRC/LVS is an engineering check unless the selected PDK declares an authoritative sign-off flow.
- Timing from an incomplete corner set is not tape-out sign-off.
- Macro, memory, and analog black boxes require reviewed interface and abstraction contracts.
- A clean flow does not establish functional correctness; RTL verification remains mandatory.
