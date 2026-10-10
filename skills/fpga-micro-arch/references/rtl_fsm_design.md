# RTL state-machine architecture

Use an FSM for reviewed control sequencing, not to hide an unspecified protocol.
Record legal states, transitions, state-owned outputs and datapath actions before
implementation. Keep state encoding separate from externally visible behavior.

## Transition and output contract

| Item | Required declaration |
|---|---|
| Reset | Polarity, assertion/release behavior and initial legal state |
| Transition | Condition, priority and accepted handshake/event |
| Output | Registered/combinational ownership, validity and stall behavior |
| Data action | Capture, update or retire event and associated payload |
| Error/timeout | Legal recovery path, status and bounded waiting assumptions |
| Illegal state | Recovery or fail-safe behavior and verification method |

For valid/ready transport, advance transaction state only on the accepted
handshake. Keep pending data and response outputs stable under backpressure.
Define concurrent events explicitly, including reset, cancellation, timeout and
completion; do not resolve their priority by incidental statement order.

## RTL structure

Use explicit widths and state constants or a supported enum. Give combinational
next-state/output logic complete defaults to avoid latches. Use nonblocking
assignments for clocked state and data. Give each register one owning process and
keep counters, arithmetic and memory accesses visible in the datapath contract.

Choose binary, one-hot or other encodings from target/report evidence. One-hot
encoding does not automatically make a design faster, and changing encoding must
preserve reset, illegal-state handling, output alignment and numeric behavior.
Synchronize asynchronous events before they drive state transitions; a state
machine is not a CDC synchronizer.

## Latency and verification

Record minimum/maximum latency and sustained throughput separately. Waiting
states may be unbounded unless the environment contract supplies a progress
guarantee. Tie timeout values to a reviewed clock and interface requirement.

Check every legal transition, concurrent-event priority, reset from each state,
stall/resume behavior, counter limits, illegal-state recovery and bounded error
paths. Use assertions for legal transitions, stable stalled payloads and progress
under justified assumptions. Functional state/transition coverage and formal
cover traces complement simulation; code coverage alone does not prove correctness.

After restructuring state or pipeline registers, choose the proof mode in
`skills/fpga-formal-verification/references/proof_modes.md`, run the applicable
gates and compare timing/resources under matching configurations.
