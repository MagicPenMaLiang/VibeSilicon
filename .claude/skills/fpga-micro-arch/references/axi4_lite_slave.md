# AXI4-Lite to CSR interface contract

Use this reference when an accepted architecture requires an AXI4-Lite shell.
Keep transport handling separate from the CSR semantics in
`references/register_file_pattern.md`. The neutral CSR example is not an AXI shell.

## Declare the boundary

Record address/data widths, byte addressing, alignment, register aperture,
access permissions, protection handling, outstanding transaction capacity,
clock/reset domains and error responses. Base addresses come from the reviewed
system address map; do not copy a board-specific address or part from an example.

| Channel | Payload | Required behavior |
|---|---|---|
| AW | Write address and protection | Capture only on AWVALID and AWREADY |
| W | Write data and byte strobes | Capture only on WVALID and WREADY |
| B | Write response | Retain BVALID and BRESP until accepted |
| AR | Read address and protection | Capture only on ARVALID and ARREADY |
| R | Read data and response | Retain RVALID, RDATA and RRESP until accepted |

AW and W are independent. Accept address-before-data, data-before-address and
simultaneous arrivals within the declared capacity. Retain accepted payloads
until paired; do not use the current live inputs after an earlier handshake.
Issue exactly one response for each completed write transaction. Apply each
enabled WSTRB byte lane independently, including zero and noncontiguous masks.

For reads, bind the response to the accepted address. Backpressure must not
overwrite an outstanding response or repeat a read-clear side effect. Define
when a CSR operation takes effect and how reset treats partially accepted writes
and outstanding responses. Latency is implementation dependent, not a fixed
three-cycle property of AXI4-Lite.

## Clock and storage boundaries

An AXI shell and datapath may share a clock. If they do not, use a reviewed
transaction bridge, snapshot handshake or appropriate asynchronous FIFO.
Synchronizing individual bits of a multi-bit register is not a coherent transfer.
Derive clocks and exceptions from the interface contract and CDC evidence;
do not add blanket false paths to make reports quiet.

Store accepted addresses/data and register state with explicit reset behavior.
Keep technology-specific memories behind neutral wrappers as required by the
selected target. AXI4-Lite and HLS block-control protocols serve distinct roles;
neither establishes the throughput of the sample datapath.

## Verification obligations

Test both write-channel arrival orders, long channel gaps, simultaneous read/write,
response stalls, every byte-strobe pattern, invalid/misaligned addresses, reset
during pending work, and register permission/side-effect behavior. Check payload
stability under stalls, response count and association, ordering and capacity.
Use a self-checking scoreboard and protocol assertions with preserved raw logs.
An unverified shell snippet is not a reusable protocol implementation.

For the normative protocol, consult the applicable AXI4-Lite sections of the
[Arm AMBA AXI and ACE specification](https://developer.arm.com/documentation/ihi0022/h).
