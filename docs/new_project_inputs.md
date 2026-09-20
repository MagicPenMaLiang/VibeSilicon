# New project inputs

VibeSilicon distinguishes FPGA and ASIC targets at project intake. Use separate target manifests even when both targets share one RTL source set.

## Common inputs

- Project ID and version with no customer-identifying information in the public repository.
- Functional specification, supported modes, error behavior, and acceptance criteria.
- Port, protocol, clock, reset, latency, throughput, and backpressure contracts.
- Numeric widths, signedness, scaling, rounding, saturation, and overflow behavior.
- Read-only golden model and representative, boundary, reset, and error vectors.
- Source file manifest, top module, language standard, parameters, macros, and generated-code provenance.
- PPA target, non-regression limits, and the measurements required for acceptance.
- Third-party ownership and license review.

## FPGA target

- Device/part, board only if hardware replay is required, and tool version range.
- Clock definitions, generated clocks, I/O constraints, and explicitly justified exceptions.
- Memory implementation policy and allowed vendor primitives.
- Synthesis/implementation strategy and required reports.
- Hardware test plan, safe programming procedure, and human approval boundary.

## ASIC target

- External PDK root and an allowlisted manifest of liberty, LEF, RC, SDC, GDS, and rule-deck views.
- Process corner, voltage, temperature, RC corner, derates, clock uncertainty, and load assumptions.
- Standard-cell and macro policy, memory compiler interface, tie/filler/endcap/tap requirements.
- Synthesis/STA target and physical-flow configuration.
- DRC/LVS handoff requirements and sign-off ownership.
- Power activity source or explicitly identified vectorless assumptions.

PDK files and proprietary design inputs must remain outside this repository. Store only sanitized metadata and content hashes in version control.

## Target split

For a dual-target design, keep these items separate:

- constraints and tool manifests;
- memory wrappers and technology cells;
- synthesis and physical evidence;
- PPA thresholds and acceptance decisions.

Behavioral interfaces and numeric contracts may be shared only when independently verified for both targets.
