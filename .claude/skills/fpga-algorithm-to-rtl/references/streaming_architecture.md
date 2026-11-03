# Converting algorithm structure into RTL

## Numeric mapping

Keep a row per operation: model expression and ordering, mathematical range,
input width/signedness/fractional bits, full intermediate width, cast point,
rounding/overflow, RTL stage and comparison vector. A storage dtype does not
specify logical width. Quantization is a reviewed model decision, not an
optimization pragma or an incidental assignment truncation.

A reduction may be reassociated only when its numeric contract permits it.
Saturation at each addition differs from saturation after the complete sum.
Floating-point associativity and signed division/shift equivalence also require
explicit treatment. Preserve the accepted order or prove the proposed mapping.
Record coefficient/lookup initialization and whether updates are atomic per frame.

## Scheduling and storage

| Algorithm pattern | RTL mapping decision | Evidence before accepting it |
|---|---|---|
| Independent point operation | Pipeline or bounded lane replication | Accepted items/cycle, alignment and resource estimate |
| Loop-carried recurrence | Dependency distance and available feedback cycles | Recurrence latency / distance lower bound; interleave only independent contexts |
| Reduction | Serial accumulator or reviewed adder tree | Width/order equivalence and exact rounding points |
| Image stencil | Window registers plus line storage | Row length, border/padding, stride and valid region |
| Repeated local accesses | Banked storage or explicit reuse | Bank/port-by-cycle schedule including simultaneous writes |
| Transpose, gather or random lookup | Tile/frame store or bounded address engine | Storage lifetime, collision/read latency, worst-case accesses |
| External memory | Separate bounded load/compute/store engines | Aggregate read + write traffic, burst evidence and controller contention |

Do not assign a fixed DSP cost per algorithm operation. Width, signedness,
mapping, sharing and device features change inference. Use estimates to reject
infeasible candidates and implementation reports to measure the surviving ones.

For each memory list bit width, depth, copies, live intervals, ports, bank function,
read latency, collision behavior, initialization/reset and technology wrapper.
Average bandwidth can fit while two same-cycle accesses collide. Capacity in
bits also omits BRAM fragmentation and port-limited replication.

## Channels and backpressure

Draw producer/consumer edges with token type, tokens per transaction/frame,
rate, startup delay, packet termination and ownership. Every queue needs a
bounded depth and a writer/reader schedule. A preliminary occupancy estimate is
the maximum cumulative production minus consumption for the assumed schedule;
it is not a deadlock proof when tasks stall or share resources. Feedback cycles
also need an explicit initial-token/reset contract.

State exactly which valid/ready handshake advances each stage. Propagate stalls
through data, addresses, valid bits and frame/line markers together. If upstream
cannot stop, budget worst-case bursts and the specified downstream stall bound;
finite buffering cannot absorb an indefinitely stalled output. Test bursty traffic,
back-to-back frames, reset during a transaction and FIFO full/empty transitions.

## Planning contract semantics

The feasibility tool uses declared values, never a default device or clock:

- Peak items/s = clock_hz * items_per_initiation / initiation_interval_cycles.
- Sustained items/s = peak * sustained_fraction, including planned overhead/stalls.
- Latency seconds = declared latency_cycles / clock_hz. Include the bounded stall
  model in latency_cycles or leave the latency conclusion unresolved in review.
- Memory bits = width_bits * depth * copies, checked per named allocation.
- External bytes/s = required items/s * total read/write bytes per item, including
  repeated passes and declared traffic overhead, against a sustainable shared budget.

Resource estimates and budgets must use the same units and account for reserved
system resources. Memory budgets must be disjoint allocations; the tool does not
detect overlapping budget assignments. For shared read/write channels, provide a
joint sustainable bandwidth. Empty memories and zero external traffic explicitly
declare that no such storage is planned; they do not discover omitted storage.

The tool verifies hashes of the three declared input files. Those files should be
complete manifests when a reference spans multiple dependencies; transitive
dependency closure and numeric semantics still require review. No feasibility
output replaces G0/G1/G2, timing closure, architecture approval or hardware tests.
