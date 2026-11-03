---
name: fpga-realtime-video-debug
description: Diagnose FPGA real-time video input or decode, custom RTL/HLS image processing, DMA/DDR and display pipelines. Use for black screens, tearing, pixel errors, AXI stream stalls, frame loss, Linux deadline misses or board-debug campaigns that fail to converge. Separate datapath, test-harness, evidence and physical-link failures.
license: Apache-2.0
metadata:
  version: "1.1.0"
  category: hardware
  routes: [fpga]
---

# Real-time FPGA video debugging

Use for a live input/decode, custom RTL/HLS processing, DMA/DDR and display path;
the actual component order is project-specific. Select the smallest experiment
that distinguishes a cause and verifies a repair. More run IDs, logs or an
occasional success do not establish convergence.

Read the project's AGENTS.md and current interface/acceptance contracts. Examples,
previous approvals and this skill do not expand current authorization. Reuse valid
approvals without asking again solely because a skill is invoked. A skill update
does not authorize changes to RTL, timing, kernels or frozen board packages.

## Locate the failing layer

Read the latest result and its bound primary records. Track these dimensions
separately:

| Dimension | Question |
|---|---|
| Pixels and protocol | Are data, line/frame boundaries, format and fixed-point values correct? |
| Throughput and deadlines | Is supply sustained, and which event exceeded which deadline? |
| Test harness | Did startup, threads, monitors and collectors work as designed? |
| Evidence | Are raw records complete, and does the parser support the actual stop path? |
| Recovery | Are CPU, scheduling, device and process states known and restored? |
| Physical display | Does the external receiver meet the contract? |

Separate the first observed failure, protective stop and root cause. A harness
failure before video starts is not an FPGA performance result; successful recovery
does not change a failed run's outcome.

Freeze source/binary/media/configuration hashes, bitstream/probe pairing, boot
identity, kernel/BSP/driver versions, original limits and approved scope. Draw the
real path and snapshot/golden/log/monitor branches. Mark clocks, queues, copies,
buffer owners and the external receiver. Do not assume GStreamer, V4L2 or a
particular DMA IP.

## Choose the shortest discriminating experiment

Load references for the observed failure rather than repeating every stage:

- Black screens, tearing, formats, AXI/HLS, DDR or clocks: [pipeline isolation](references/pipeline-isolation.md).
- Counters, CRC, bypass, configuration switching, ILA/JTAG/ECO: [instrumentation contracts](references/instrumentation-contract.md). Establish interfaces and verification before implementation.
- Decode, buffer synchronization, DRM or scheduling tails: [Linux timelines](references/linux-video-diagnosis.md).
- Repeated non-converging runs: [experiment card](references/experiment-card.md) and [reusable lessons](references/recent-lessons.md).
- Technical sources and version limits: [primary references](references/sources.md).

Replay existing records and reproduce the real startup combination first. Then
select authorized device-free diagnostics or a bounded path experiment before
fixed acceptance. Reuse boundaries already established by valid evidence. A TPG,
bypass, alternate output or disabled snapshot changes the experiment boundary;
declare it and do not treat it as the original full acceptance test.

Each expensive experiment tests one primary causal variable. State competing
explanations, distinguishable outcomes, data/time/CPU budgets and stop conditions
before execution. Treat instrumentation changes as possible confounders. If the
same failure recurs without excluding a hypothesis, revise measurement or the
experiment; do not search priorities, CPU masks or kernel settings until a run
happens to pass.

## Connect evidence through frame identity and time

Record frame/slice identity, buffer generation, configuration epoch, units, clock
domain, precision and conversion error for each event. Distinguish planned release,
wakeup, dispatch, userspace return, processing completion, display submission,
driver completion and external presentation. Uncorrelated intervals remain unknown.

Reconstruct the failed frame before comparing neighboring successful frames from
the same run. Count started, completed, published and verified frames separately;
instantaneous input/output differences in a pipeline need not mean loss. Record
trace windows, filters, coverage and dropped events. Apply limits to original
integer timestamps without rounding a violation into PASS.

The same thread at two endpoints does not prove continuous execution or a specific
system call. A pre-submit stop may have no final DRM event; retain any captured
snapshot failure. Matching CRCs support consistency but do not replace required
pixel comparisons or physical output measurements.

## Verify the observer before interpreting the target

Reproduce production startup order, real log-reader threads, helpers, READY
handshakes, property inheritance and recovery. Read back actual policy, priority,
CPU set and session identity for every relevant thread rather than only requested
values. Exercise pre-existing threads, partial initialization, child failure,
record exhaustion and unknown recovery. Isolated unit success is not integrated
startup success; identify which board facilities a host fixture replaces.

Budget fixed record storage separately from process RSS. Include polling,
formatting, syscalls, network/disk and memory bandwidth. Prefer existing bounded
records and first-error windows. Do not add unplanned SSH, verbose logging, perf,
strace or timerlat to fixed acceptance; some tools create real-time threads and
change scheduling.

## Close against the original contract

A FIFO, CPU affinity or SCHED_FIFO alone does not prove a hard deadline. A sample
maximum is not a worst-case bound. If the platform cannot support the required
timing argument, propose an evidence-based architecture decision involving the
driver/kernel, hardware timing or reviewed requirements. Do not relax deadlines
or promise that PREEMPT_RT will necessarily pass.

Implement only evidence-supported changes, verify the failure mechanism, then
execute within current authorization. Apply the relevant review to changed
artifacts; do not request approval again for unchanged artifacts with valid
approval. If recovery is unknown, preserve evidence and follow the approved
exception path rather than automatically continuing, unloading or rebooting.

Deliver the failure boundary, evidence summary, excluded/open hypotheses, repair
or next-experiment criteria and each acceptance dimension. Claim completion only
when required media, frame count, duration, numeric, deadline, monitoring, recovery
and physical measurements all have corresponding evidence. Identify external
instrument dependencies early.
