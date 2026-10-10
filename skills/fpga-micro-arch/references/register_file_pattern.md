# CSR semantics and implementation boundaries

Define register behavior before choosing a bus shell. The bus owns accepted
transactions and responses; the CSR bank owns state, side effects and datapath
configuration. Read `references/axi4_lite_slave.md` for AXI4-Lite transport.

## Register contract

For each register and field, declare offset, width, access class, reset value,
reserved-bit policy, valid values, clock domain and read/write side effects.
Use byte offsets for the system map and declare any conversion to a word index.
Check aperture bounds before indexing storage.

| Access class | Contract to record |
|---|---|
| RW | Writable byte lanes, reserved bits and update timing |
| RO | Source of status and response to a write |
| WO | Write side effect and value/response returned by a read |
| W1C / W1S | Mask semantics and precedence of simultaneous hardware events |
| Read-clear | Exact accepted operation that triggers clearing |

Choose error behavior for invalid, misaligned or prohibited accesses. Define
same-cycle read/write visibility and whether hardware or software wins collisions.
Interrupt status must specify event capture, masking, clearing and set/clear
precedence so a coincident new event cannot silently disappear.

## Configuration and status transfer

Declare immediate, frame-boundary or explicit-commit configuration updates.
For multi-field configuration, document shadow storage and atomic commit behavior.
Provide a coherent snapshot for multi-bit status crossing clock domains, with
ownership and acknowledgments defined. Reset must establish legal configuration
and interrupt state and define the handling of pending bus operations.

Keep register state separate from algorithm memory and isolate target-specific
storage behind reviewed wrappers. Avoid resetting every inferred memory cell
without checking the target memory contract and synthesis result.

## Reusable example and validation

The neutral example is
`skills/fpga-rtl-system/references/verilog_templates/csr_template.v`.
It is an unfinished interface scaffold: register state, read data and interrupts
are not implemented. It does not implement AXI4-Lite. Define and verify the
register contract and bus shell before using it in a design.

Verify permissions, all supported byte masks, reset, illegal addresses, collision
precedence, interrupt races and configuration atomicity. Preserve source-bound
simulation evidence and review the synthesized storage. Do not substitute an
illustrative register map for the project's accepted interface contract.
