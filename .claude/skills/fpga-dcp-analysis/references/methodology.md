# Vivado methodology triage

Use for methodology warnings in a synthesized or implemented FPGA design. This
adapts Ross's rule-specific diagnosis and constraint provenance into the existing
read-only checkpoint flow; it does not add a methodology parser or edit adapter.

## Collect and localize

Use the fixed `collect_reports` tool or `scripts/fpga_reports.py` for the existing
report bundle, including methodology, min/max timing, unconstrained paths,
clocks, clock interactions, exception coverage, CDC and routing evidence. Preserve
the checkpoint, tool release, source/constraint hashes and synthesis/route stage.
The current collector retains raw methodology text; it does not implement Ross's
2026.1 JSON workflow or automatically decide every TIMING rule.

For each finding retain rule ID, instance/name when available, severity, complete
message, implicated cell/pin/net/clock and report locator. Map a reported effective
constraint back to its original XDC file, line, ordering and scope. A merged or
exported XDC is diagnostic evidence, not automatically the maintained source.
If localization is ambiguous, keep that gap explicit before proposing a change.

## Resolve prerequisites first

Prioritize by actual dependency and correctness risk:

1. Establish intended clocks, generated-clock relationships, reset behavior and
   I/O timing requirements from the reviewed interface contract.
2. Check clock definitions/propagation and missing or conflicting constraints.
3. Review crossing topology and exceptions against CDC evidence and design intent.
4. Diagnose remaining logic, routing, fanout and physical limitations from paths.

Consult the exact rule's documentation for the selected tool release through
`fpga-doc-search`. Preserve unsupported or unrecognized rule IDs. Do not copy a
fixed count of supported TIMING rules, a newer release's priorities, or example
clock periods into an older project. Ross's reviewed methodology skill declares
Vivado 2026.1+; that does not qualify its JSON options or remedies on 2024.2.

## Handoff and verification

Return each finding as a measured fact, a suspected cause, missing evidence and
the next owner. Route constraint corrections to `fpga-constraints`, crossing
questions to `rtl-cdc`, and a reviewed timing experiment to `fpga-timing-closure`.
This skill remains read-only. An upstream AUTO classification does not override
the project's contract, independent review or human approval requirements.

After an authorized change, regenerate the affected evidence from the changed
inputs and compare before/after findings by rule and object, not just total count.
Retain unresolved and waived findings separately, with waiver justification and
scope. For implementation-dependent conclusions, obtain matching implementation
evidence; an in-memory constraint edit or stale DCP is insufficient.

Removing a warning does not establish its correctness. Never improve a report by
relaxing the requested period, adding an unproved false path/clock group, dropping
I/O requirements or changing severity. Setup and hold, unconstrained endpoints,
exception coverage, CDC, routing and DRC remain separate acceptance checks.
