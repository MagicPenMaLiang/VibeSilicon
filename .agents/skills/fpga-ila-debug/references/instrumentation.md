# Instrumentation design before capture

Choose probes from a falsifiable hardware hypothesis: transaction handshakes,
frame/packet markers, error counters, FIFO occupancy and relevant state. Record
exact hierarchy, widths, sample clock, reset and trigger/capture window. Probe
names and IP parameters must come from the actual tool/catalog release.

Use passive observation where possible. Account for trace memory, probe width,
fanout, debug clocks and routing pressure. Multiple asynchronous domains need
appropriate independent observation or reviewed synchronization; a shared ILA
does not make asynchronous values coherent. MARK_DEBUG/DONT_TOUCH can prevent
optimization, so limit protection to justified nets and bind it to debug intent.

Preserve a reproducible, reviewed instrumentation change and its IP configuration.
Validate BD connectivity, rerun implementation/CDC/timing and compare against the
uninstrumented baseline before generating the matching bitstream/LTX pair.
Insertion and capture are different stages; the current board adapter captures
an already-instrumented image and does not automatically insert IP.

Check Vivado/hw_server version compatibility before live operations. A mismatch
is an environment failure, not a reason to restart an unrelated hardware server
or retry a different target. Keep exact identity and exclusive ownership checks.

VIO input observation and output driving have different effects. Output writes
can change reset, enables or mux selection and need an explicit drive contract,
safe value/restore behavior and an exact-device bounded operation adapter. No
VIO execution adapter exists here; do not emulate it through arbitrary Tcl or
reuse an ILA approval for a control write. This reference supports probe planning.

After capture, retain raw samples and a compact record of core/probe identity,
sample depth, clock assumptions, capture mode, device/image hashes and observations
at specific sample indexes. A screenshot or "signal is high" is insufficient.
When the raw capture already exists, analyze/export those bytes rather than
re-arming merely to recreate a report. Keep trigger timeout separate from a
functional mismatch. Current execution supports immediate capture only; advanced
trigger syntax, storage qualifiers and TSM compilation need a separate adapter.

For any future VIO adapter, refresh software output state after programming,
preserve all unaffected outputs and verify the requested effect through independent
input activity. An output-property readback is not proof that the circuit reacted.
Treat reset-to-initial as a write, not harmless discovery. Host-side set/commit
calls do not guarantee a one-cycle pulse; a cycle-precise pulse requires reviewed
clocked hardware support. Do not adopt upstream examples that assume otherwise.
