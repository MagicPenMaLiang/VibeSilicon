# HLS scheduling decisions

Read the selected Vitis HLS version's directive documentation. Record each pragma's intent, target loop/function and observed report result; a requested pipeline II is not an achieved II.

| Intent | Candidate technique | Required evidence |
|---|---|---|
| Sustained throughput | Pipeline reviewed loop | Achieved II, recurrence/port constraints, latency |
| Parallel arithmetic | Bounded unroll | Resource growth, bandwidth, timing, exact results |
| Concurrent stages | Dataflow with explicit FIFOs | Token rates, depth/deadlock, backpressure |
| Memory bandwidth | Reviewed partition/banking | Port demand, RAM inference, neutral memory contract |
| Resource sharing | Allocation/scheduling | II and latency guardrails |

Do not erase real dependencies to satisfy scheduling. Do not partition all memories blindly or force DSP binding without target/resource evidence. Validate C simulation, synthesis reports, RTL co-simulation and appropriate implementation stages. Keep implementation-specific storage behind reviewed boundaries and record tool/version/configuration hashes.
