# HLS scheduling decisions

Read the selected Vitis HLS version's directive documentation. Record each pragma's intent, target loop/function and observed report result; a requested pipeline II is not an achieved II.

| Intent | Candidate technique | Required evidence |
|---|---|---|
| Sustained throughput | Pipeline reviewed loop | Achieved II, recurrence/port constraints, latency |
| Parallel arithmetic | Bounded unroll | Resource growth, bandwidth, timing, exact results |
| Concurrent stages | Dataflow with explicit FIFOs | Token rates, depth/deadlock, backpressure |
| Memory bandwidth | Reviewed partition/banking | Port demand, RAM inference, neutral memory contract |
| Resource sharing | Allocation/scheduling | II and latency guardrails |

## Architecture record

For each candidate directive, record the target loop/function, work per iteration,
recurrence distance, required memory ports, resource budget, intended II/latency
and tool version. In the report, distinguish requested values from achieved
values and bind the measured result to the source/configuration hashes.

- `PIPELINE` requests overlapped scheduling; dependencies and port pressure can
  prevent the requested II. II and end-to-end latency are separate quantities.
- `UNROLL` increases spatial work; confirm arithmetic and memory bandwidth costs
  before selecting a factor. Reductions require a reviewed numeric and scheduling plan.
- `DATAFLOW` requires compatible producer/consumer rates and bounded buffering;
  test stalls, reset and deadlock rather than assuming automatic FIFOs suffice.
- `ARRAY_PARTITION` or banking changes memory organization. Check port demand,
  inferred storage and the FPGA/ASIC wrapper boundary.
- `LOOP_TRIPCOUNT` supplies reporting information for loop bounds; it does not
  replace the functional bound or prove latency.
- Storage/operator binding and interface directives are tool/version dependent.
  Use the selected release's documentation and preserve the reviewed contract.

Do not erase real dependencies to satisfy scheduling. Do not partition all memories blindly or force DSP binding without target/resource evidence. Validate C simulation, synthesis reports, RTL co-simulation and appropriate implementation stages. Keep implementation-specific storage behind reviewed boundaries and record tool/version/configuration hashes.

Consult the selected release of [AMD UG1399](https://docs.amd.com/r/en-US/ug1399-vitis-hls/Loop_tripcount)
for directive semantics; the linked LOOP_TRIPCOUNT entry explicitly distinguishes
analysis information from synthesis behavior.
