# Primary references

Researched 2026-10-20. These are technical references, not target capability evidence. Match API/kernel/BSP versions before applying details. Do not copy examples into a live run without checking its authority and measurement plan.

| Source | Decision it supports | Applicability limit |
| --- | --- | --- |
| [Linux timerlat tracer](https://www.kernel.org/doc/html/latest/trace/timerlat-tracer.html) | Separate timer IRQ delay from scheduled-thread latency; correlate activation IDs; account for observer workload | Target tracer/config may be absent; enabling it changes workload and scheduling |
| [Linux PREEMPT_RT theory](https://docs.kernel.org/core-api/real-time/theory.html) | Consider non-preemptible sections and threaded interrupts when analyzing wake-to-run delay | Does not establish the application's deadline or certify a vendor kernel |
| [Linux ftrace](https://docs.kernel.org/trace/ftrace.html) | Check trace clocks, event context, bounded buffers and loss before causal ordering | A ring tail or filtered trace can omit relevant execution |
| [DRM userland interfaces](https://docs.kernel.org/gpu/drm-uapi.html) | Distinguish submission, page-flip/vblank events and timestamp capabilities | Driver events are not physical receiver measurements |
| [dma-buf sharing and synchronization](https://docs.kernel.org/driver-api/dma-buf.html) | Separate fence completion, CPU cache coherency and exclusive access | Use only for matching dma-buf mappings and the actual synchronization contract |
| [V4L2 stateful decoder interface](https://docs.kernel.org/userspace-api/media/v4l/dev-decoder.html) | Interpret OUTPUT/CAPTURE queues, decode/display order, drain and format changes | Native vendor decoder APIs may differ; this is not evidence the project uses V4L2 |
| [GStreamer latency tracer](https://gstreamer.freedesktop.org/documentation/coretracers/latency.html) | Inspect pipeline and element latency on a real GStreamer path | Not a direct instrument for an unrelated native player; overhead must be bounded |
| [GStreamer queue](https://gstreamer.freedesktop.org/documentation/coreelements/queue.html), [QoS design](https://gstreamer.freedesktop.org/documentation/additional/design/qos.html) | Inspect buffering/backpressure, lateness and drop accounting | Changing leakage, synchronization or QoS can change accepted behavior |

Project experience is intentionally kept in the project analysis, not generalized into board-specific masks, priorities, clock compensation values or mandatory kernels here.

## Hardware and implementation references

These references support the hardware guidance. A current web edition does not
replace the manual for the installed IP/tool release. Verify register offsets,
reset sequences and debug Tcl against the actual version.

| Primary source | Supported decision | Applicability limit |
|---|---|---|
| [AMD UG934: SOF](https://docs.amd.com/r/en-US/ug934_axi_videoIP/Start-of-Frame-Signal) | SOF identifies the first active pixel of a frame/field, not vertical blanking | Declare progressive/interlaced mode and sideband mapping |
| [AMD UG934: bandwidth](https://docs.amd.com/r/en-US/ug934_axi_videoIP/Video-Subsystem-Bandwidth-Requirements) | Separate active-pixel throughput, blanking and instantaneous supply | Estimates do not prove available board DDR bandwidth or service latency |
| [AMD PG043: AXI4-Stream](https://docs.amd.com/r/en-US/pg043_v_vid_in_axi4s/AXI4-Stream-Interface) | Interpret transfers and line/frame markers through accepted handshakes | Custom streams may use different semantics |
| [AMD PG044: output buffering](https://docs.amd.com/r/en-US/pg044_v_axis_vid_out/Buffer-Requirements) | Account for clocks, phase and supply behavior | Buffer depth cannot indefinitely correct a persistent rate mismatch |
| [AMD PG020: VDMA hardware debug](https://docs.amd.com/r/en-US/pg020_axi_vdma/Hardware-Debug) | Diagnose dimensions, stride, status and SOF/EOL together | Apply only to the matching VDMA; preserve first-error evidence before clearing state |
| [AMD Vitis: FIFO sizing/deadlocks](https://xilinx.github.io/Vitis-Tutorials/2020-2/docs/build/html/docs/Hardware_Accelerators/Feature_Tutorials/03-dataflow_debug_and_optimization/fifo_sizing_and_deadlocks.html) | Explain DATAFLOW deadlock through production/consumption order and blocked channels | Historical tool example; do not copy FIFO constants to another algorithm |
| [AMD UG908: ECO probe replacement](https://docs.amd.com/r/en-US/ug908-vivado-programming-debugging/Using-Vivado-ECO-Flow-to-Replace-Existing-Debug-Probes) | Use supported post-implementation probe changes and recheck artifacts | Web editions can change; no promise of arbitrary replacement, runtime or preserved timing |
## Hardware and implementation references

These references support the hardware guidance. A current web edition does not
replace the manual for the installed IP/tool release. Verify register offsets,
reset sequences and debug Tcl against the actual version.

| Primary source | Supported decision | Applicability limit |
|---|---|---|
| [AMD UG934: SOF](https://docs.amd.com/r/en-US/ug934_axi_videoIP/Start-of-Frame-Signal) | SOF identifies the first active pixel of a frame/field, not vertical blanking | Declare progressive/interlaced mode and sideband mapping |
| [AMD UG934: bandwidth](https://docs.amd.com/r/en-US/ug934_axi_videoIP/Video-Subsystem-Bandwidth-Requirements) | Separate active-pixel throughput, blanking and instantaneous supply | Estimates do not prove available board DDR bandwidth or service latency |
| [AMD PG043: AXI4-Stream](https://docs.amd.com/r/en-US/pg043_v_vid_in_axi4s/AXI4-Stream-Interface) | Interpret transfers and line/frame markers through accepted handshakes | Custom streams may use different semantics |
| [AMD PG044: output buffering](https://docs.amd.com/r/en-US/pg044_v_axis_vid_out/Buffer-Requirements) | Account for clocks, phase and supply behavior | Buffer depth cannot indefinitely correct a persistent rate mismatch |
| [AMD PG020: VDMA hardware debug](https://docs.amd.com/r/en-US/pg020_axi_vdma/Hardware-Debug) | Diagnose dimensions, stride, status and SOF/EOL together | Apply only to the matching VDMA; preserve first-error evidence before clearing state |
| [AMD Vitis: FIFO sizing/deadlocks](https://xilinx.github.io/Vitis-Tutorials/2020-2/docs/build/html/docs/Hardware_Accelerators/Feature_Tutorials/03-dataflow_debug_and_optimization/fifo_sizing_and_deadlocks.html) | Explain DATAFLOW deadlock through production/consumption order and blocked channels | Historical tool example; do not copy FIFO constants to another algorithm |
| [AMD UG908: ECO probe replacement](https://docs.amd.com/r/en-US/ug908-vivado-programming-debugging/Using-Vivado-ECO-Flow-to-Replace-Existing-Debug-Probes) | Use supported post-implementation probe changes and recheck artifacts | Web editions can change; no promise of arbitrary replacement, runtime or preserved timing |
