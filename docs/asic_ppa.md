# ASIC PPA reporting

The ASIC flow converts reviewed external inputs into traceable synthesis, timing, area, and power evidence. It does not redistribute a PDK and does not claim foundry sign-off.

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
