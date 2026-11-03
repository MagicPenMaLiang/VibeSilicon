# Instrumentation and tool contracts

This reference replaces generic wrapper/Tcl sketches that cannot be reused safely.
Before generating executable code, require matching ports, registers, clocks,
resets, numeric behavior and operating scope. An unconnected algorithm with a
straight-through assignment is not a switchable algorithm bypass; a low-32-bit
sum is not a full-frame CRC32.

## Bounded observability

Select the minimum signals needed for the failure. Do not assume a fixed LUT
overhead or coverage percentage; resource and timing claims require synthesis
and implementation evidence.

| Observation | Required semantics |
|---|---|
| Interface input/output | Only `TVALID && TREADY` accepts a beat; distinguish beats, active pixels, EOL and SOF units |
| Frame statistics | Separate started, completed and aborted; track frame_id/config_epoch, short/long frames and no prior first-frame result |
| Line/frame length | Check valid lanes and frame height, including a one-beat line with simultaneous SOF/EOL; distinguish observational resynchronization from functional reset |
| Stalls | Accumulated/max consecutive `valid&&!ready` and no-data intervals within a required supply window; legal blanking, pause and backpressure are not automatic errors |
| FIFOs/buffers | Peak occupancy, full/empty and actual overflow/under-read; identify wait dependencies and current frame/buffer |
| First error | Latch type, cycle/time, frame/line/column, configuration epoch and state; export evidence before clearing |
| Output comparison | Completeness, sample count, digest algorithm and input sequence; export the smallest differing interval after mismatch |

Thresholds come from the interface/deadline contract and must not be relaxed after
failure. Define counter overflow/saturation. Use reviewed snapshots/handshakes for
CDC export, not independent bit synchronizers. Multiword CPU reads must detect
generation changes. Define W1C/read-clear behavior and the priority between clear
and a new error so that clearing cannot erase new first-error evidence.

## SOF, configuration and bypass

AXI4-Stream Video SOF marks the first active pixel, commonly TUSER[0]; it is not
vertical blanking. TLAST is EOL, not a general EOF. Use the selected IP's actual
sideband contract.

Observational counters may start new statistics on accepted SOF; an unexpected
SOF terminates and marks the old frame incomplete. Do not unconditionally reset
functional line buffers or algorithm state while old pixels remain in flight.
Define stop-accept, drain/discard, resynchronization and recovery if required,
and verify that an old frame cannot contaminate the new frame.

Use shadow/request/ack or an equivalent atomic transaction for dynamic parameters
and record config_epoch. CDC configuration requires a coherent snapshot. If the
update uses a frame boundary, define:

1. Which first pixel uses the new configuration, including same-edge nonblocking assignments.
2. Which configuration remains attached to old pixels in the pipeline/output.
3. Completion or pending status with no new frame, unexpected SOF, hot switching and reset.

Bypass selection governs data, sidebands, valid and ready together. Hold output
stable during `valid&&!ready`. An unselected branch must not block, consume twice
or leak old data. Switch different-latency paths at a controlled empty boundary
or use a verified frame-tag/drain scheme. Display vblank, input SOF and algorithm
idle are distinct conditions.

## Frame digests

Declare CRC polynomial, initial value, reflection, xorout, byte order, lane/plane
order and treatment of padding, invalid lanes and sidebands. Hardware and golden
references consume the same active sequence, including every valid sample in a
multi-pixel beat; checking only low DATA bits is insufficient.

Derive frame completion from verified geometry/protocol state, not TLAST alone.
If the next SOF publishes the previous digest, define a final-frame drain so the
last result is not lost. Records contain valid/complete, frame_id, pixel count and
configuration epoch; initial empty or partial digests are not complete results.

Checksums and CRCs can collide; a sum is especially weak against reordering.
Digests help localize changes, while sample/byte comparisons establish bit-exact
evidence for compared data. A processing algorithm is compared with its golden
output; input and output CRCs need not match.

## Required implementation verification

Use applicable self-checking simulations for the actual interface before board
deployment. This table is a test plan, not a claim that tests have run.

| Scenario | Expected evidence |
|---|---|
| No stalls and random upstream/downstream stalls | No lost/duplicated transfers; stable payload/sidebands; legal stalls do not trigger protocol errors |
| One-beat lines, one-line frames and multi-PPC tails | Correct SOF/EOL accounting and all declared valid lanes compared |
| Missing/early EOL, unexpected/missing SOF and short frames | Complete, partial and unsynchronized states remain distinct; no stale digest published as a new frame |
| First frame, final-frame stop and continuous frames | No false prior result; final frame completes; frame IDs/epochs align |
| Configuration/bypass switches with stalls and in-flight frames | No mixed configuration or changed offered beat; pending requests have explicit state |
| Extremes, cross-lane changes, reorder and bit flips | Actual CRC compared with an independent reference, including high-lane-only changes |
| Counter overflow, CDC reads and concurrent clear/error | Contract behavior, coherent snapshot and retention of new errors |
| Reset/recovery and blocked branches | No hanging handshake, unsafe buffer reuse or uncontrolled frame loss |

Then inspect synthesis resources, critical paths and CDC. Do not mark an
unsimulated example as ready for a board.

## ILA, JTAG-to-AXI and ECO

Prefer first-error, abnormal-length, FIFO-threshold or long-stall triggers, retaining
pre/post windows. Observe related handshakes/state in one clock domain. Arbitrary
cross-domain probes cannot guarantee capture of narrow pulses or asynchronous
signals. An ILA on a stopped clock may provide no later evidence.

A JTAG-to-AXI plan binds exact device/link, actual AXI master, address allowlist,
register widths/access semantics, timeout, transaction limit, initial state and
readback criteria. Check read-clear and start/reset writes and resolve ownership
with existing drivers. Do not use arbitrary-base loops or assume offset zero is
bypass. Use version-matched structured results rather than fixed report columns.

ECO may reduce probe-change cost but has no fixed turnaround guarantee. Bind tool
version, original routed checkpoint, unique netlist objects, widths, probe clock,
routability and debug-core limits. After a supported change, recheck implementation
status, DRC, timing and applicable CDC; bind the new bitstream, probes and checkpoint
hashes. These checks and the applicable artifact approval precede deployment.

For actual capture/configuration use fpga-ila-debug and fpga-programming. This
guidance creates no unrestricted Tcl, arbitrary-address writes or shell interface.
