# Vivado project and IP reproduction

Apply this on the FPGA branch when a project includes vendor IP or block designs.
Core RTL and the ASIC memory/constraint contracts keep their independent ownership.

## Rebuild inventory

Record tool release, exact part, top, ordered HDL sources, includes/defines,
language standards, simulation sources, XDC order/scope, generated clocks and
implementation strategy. Bind source/configuration bytes, not only an XPR name.
Inventory each IP's exact VLNV/version, repository dependencies and BD connectivity,
address map, clocks, resets and wrapper-generation steps. A current catalog's
newest version is not automatically equivalent to the reviewed baseline.

Use a reviewed project-local reconstruction entrypoint with explicit inputs.
Do not expose arbitrary Tcl through MCP to implement this playbook. Existing
fixed MCP build tools and normal reviewed repository scripts have distinct scopes.
Recreate in an isolated output directory, then compare elaborated top/ports,
compile order, IP status, constraints and addresses before using implementation
results. Missing licensed/catalog IP leaves reproduction BLOCKED.

Include non-default project/run and per-file settings, such as VHDL libraries,
global includes, file type, synthesis/implementation use, simulation use and
pre/post hooks. Classify source ownership as local, external or mixed; an export
must not silently copy or flatten externally owned sources. Record the expected
BDs, managed wrappers and runs before export and compare them in the recreation.
Matching file counts or merely creating an XPR does not prove reconstruction.

Keep generated vendor output, caches, XPRs, XSA, checkpoints and bitstreams outside
public version control. If exact reproduction depends on an external generated
artifact, record its hash and retrieval owner and fail when absent; do not silently
regenerate or upgrade it. Audit exported Tcl for local paths before distribution.

## IP intent ledger

For each requested feature record its requirement ID, documented meaning, selected
IP/version, requested value, configuration mechanism and observed value. Classify
the mechanism as design-time CONFIG, connection-propagated, or software runtime.
Record the product-guide revision and the tool/catalog version used to resolve it.

Apply only the reviewed configuration. Read back requested properties and inspect
warnings even if the Tcl call returned zero. For gated values check documented
prerequisites and read back again. After BD validation, recheck propagated widths,
clock/reset polarity, addresses and enabled ports. A default that happens to match
needs a recorded value source; a changed property is not proof of functional intent.

Decompose intent into one row per feature, count, width, rate or mode. For each
row retain expected CONFIG readback and expected observable interface behavior.
Distinguish exact matches, documented defaults, propagated values, runtime-only
work, unsupported values and unresolved requirements. Tolerances need a reviewed
meaning and unit; a nearest legal value is not an exact match by default.

Treat successful Tcl return plus ignored-parameter warnings as a failed or partial
application. Inspect dependencies, legal values and value sources, then verify
again after validation/automation. Record preset changes and added cells/ports;
automation defaults can overwrite an earlier setting. Keep corrective attempts
bounded by the project's experiment plan and stop repeated no-progress changes.
Do not assume failed configuration was atomic: compare against the saved baseline
and verify restoration before another attempt. These steps require a reviewed
project script or future bounded adapter; no `ipcfg::` helper is installed here.

Runtime features belong in a software register-write/test plan, not an invented
CONFIG property. Record unsupported requests and dependencies explicitly. Do not
substitute the closest supported width/mode, switch parts, remove clocks or add
dummy connections to claim completion. Resolve the discrepancy within the existing
bounded experiment/review process.

Successful creation/configuration is distinct from elaboration, protocol checks,
timing, implementation and hardware behavior. Preserve each result separately.
