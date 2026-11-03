# Linux and FPGA video diagnosis

Use only sections relevant to the observed failure. Commands and trace facilities must match the installed kernel/BSP; the linked current documentation is not proof a vendor kernel implements them. This reference specifies measurements, not permission to alter a board.

## Pipeline and frame identity

Sketch the actual path: compressed input -> parser/decoder -> decoded buffer -> PL -> display submission -> scanout -> external receiver. Draw snapshot and golden-check branches, plus their buffer lifetimes. Include software queues and every copy; the production path may use a native decoder API rather than V4L2 or GStreamer. Inspect that API instead of inventing a different pipeline.

Record coded/visible dimensions, rational frame rate, NV12/NV12M or other fourcc, planes, strides, offsets, modifiers, crop, bit depth, color range/matrix and buffer count. Do not assume tightly packed storage. Map compressed decode order to presentation order, PTS/DTS, application sequence, buffer identity/generation and display sequence. Reordering means one compressed buffer need not correspond directly to the next displayed frame. Check drain/EOS and source-change behavior using the actual decoder interface.

For each buffer establish who may read/write it, what completion or fence transfers ownership, when CPU access starts/ends, and when it may be reused. A fence completion and CPU cache synchronization solve different problems; DMA_BUF_IOCTL_SYNC is not a mutual exclusion mechanism. Apply it only to actual dma-buf mappings under the driver's contract, not arbitrary physical memory. Snapshot the declared immutable frame, not a buffer being decoded or scanned out. Preserve the original golden layout and rounding.

Separate sustained throughput from deadline feasibility. Compute bytes/frame from actual stride/layout and count DDR reads/writes, copies and concurrent snapshot traffic. For illustration only, tightly packed 3840x2160 NV12 is 12,441,600 bytes; one pass at 30 fps is 373,248,000 bytes/s. This is not a measured bandwidth result and excludes alignment and other masters. Queue growth diagnoses a service-rate or backpressure problem; an empty queue can diagnose starvation. Average bandwidth and fps do not bound individual stalls.

## Deadline accounting

For one activation use named events (all converted to one proven time domain):

| Event | Meaning |
| --- | --- |
| r | Contractual absolute release |
| w | Matching runnable/wakeup observation; distinguish sched_waking from sched_wakeup |
| s | First matching scheduled-in after that wake |
| u | Application's first return/guard observation |
| c | Declared work completion |
| a/e | Display commit request/driver completion event, if submission occurred |

Where those boundaries exist, release lateness is u-r and decomposes into (w-r)+(s-w)+(u-s). This is endpoint accounting, not a proof of uninterrupted CPU execution. Account for intervening switches, migration, IRQ/softirq and lock/IO waits separately. Work wall time c-u includes preemption; thread CPU time can help distinguish waiting from computation but is not a root-cause proof. Never add overlapping intervals such as a total thread latency and the IRQ time already inside it.

Record requested sleep target, actual clock ID, absolute/relative mode, syscall result/interruption, deadline and failure stage. Preserve the first rejected activation even if no completed-frame record was published. Check commit window, phase and end-to-end delay separately; a correct average fps can coexist with a missed commit window.

## Clocks and trace validity

Inventory CLOCK_MONOTONIC, CLOCK_MONOTONIC_RAW, application/video counters, kernel trace clock and DRM event timestamps. A time adjustment can change clock-rate relationships; a one-time offset is not automatically valid over the run. Retain the mapping/calibration and error over the relevant interval. Check DRM timestamp capability and target driver behavior rather than assuming every event clock is identical. ftrace local clocks may be unsuitable for cross-CPU ordering; use an available reviewed clock or limit the inference. Do not change the trace clock mid-run and merge the epochs.

Record kernel release/config, available tracers/events and each event's format. Bind PID/TID/start/boot identity and use context-switch/migration events appropriate to the exact thread. Distinguish sched_waking (wake initiation) from sched_wakeup (runnable notification). Report trace filters, start/end coverage, per-CPU overrun/drop statistics and ring truncation. Filtering out other tasks can make continuity impossible to prove. Do not infer a syscall, continuous execution or unique blocker from equal task names at two endpoints.

Match parser expectations to actual failure stage. A snapshot-thread failure may leave the main record at the last completed frame and may prevent any terminal page flip. Replaying a parser on raw retained bytes is cheaper than repeating the board run. A corrected interpretation belongs in a new analysis record; the original failure remains intact.

## Scheduling and observer interference

Inventory task creation order and inheritance: controller, log reader, log helper, monitor/query helper, player, feeder, snapshot and IRQ threads. Capture actual per-thread policy/priority/mask and session/autogroup where relevant. Confirm masks after creation and restoration. Per-thread nice, autogroup weights and real-time priority are distinct mechanisms; do not substitute one readback for another.

Examine scheduling delay, IRQ/softirq interference, non-preemptible sections, RT throttling, page faults, allocation, IO, thermal/frequency behavior and memory contention as competing hypotheses. Select observations based on evidence; do not run a whole-system tuning checklist. SCHED_FIFO cannot preempt a kernel section with preemption disabled. Changing priority above a display IRQ can impair the pipeline it is meant to help.

Timerlat can distinguish IRQ-context latency from thread-context latency and correlate activations, but it creates its own workload (documented defaults include a high-priority FIFO thread). Check target support and its interference before proposing a separate diagnostic. cyclictest/timerlat results characterize that test and workload; they do not certify the application's critical path. No finite sampled maximum alone proves a hard deadline. PREEMPT_RT reduces specific blocking sources but retains critical paths; a migration requires compatible drivers, boot/image provenance and validation, not just a config toggle.

For a native player prefer existing fixed-size events. For an actual GStreamer path, use its latency tracer to distinguish pipeline/element latency, inspect negotiated caps, queue levels and QoS dropped/processed counts. Queue leaky mode or sink sync/QoS changes alter behavior; do not use them to hide drops or meet an unchanged contract. High-volume tracing and live console/network queries can be the disturbance. A diagnostic observer-on/off comparison must keep workload and clocks comparable and declare remaining confounders.

## Display and external proof

A successful ioctl/submission is not completion. Associate page-flip/vblank/fence events with the actual CRTC, buffer and sequence under the target driver's semantics. Those events support software-side presentation analysis; they do not prove HDMI receiver pixel order, no tearing or glass-to-glass delay.

If the contract requires physical proof, specify receiver/capture/analyzer capability, frame-identifying pattern, capture losses, timebase alignment and uncertainty. Distinguish capture-device drops from source drops. Software golden snapshots validate their sampled memory frames only. Report missing receiver evidence as BLOCKED, and identify its equipment/owner dependency before lengthy software-only optimization.
