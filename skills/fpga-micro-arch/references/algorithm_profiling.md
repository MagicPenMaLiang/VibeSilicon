# Extracting an architecture contract from a golden model

Read the immutable model and its vectors before choosing RTL or HLS. A Python
storage dtype alone does not define the logical width, scaling or overflow rules.
Record uncertainty as an open item; do not fill it with an implementation assumption.

## Numeric boundaries

For every input, intermediate and output, record signedness, logical width,
fractional bits, valid range, rounding mode, saturation/wrap behavior and cast points.
NumPy storage may be wider than the logical value; arbitrary widths need an
explicit contract rather than an invented NumPy dtype.

Trace multiplication, accumulation and requantization separately. Preserve full
intermediate precision unless the golden contract explicitly truncates it.
Check zero, extrema, negative values, ties and overflow. A shift is equivalent
to division only under the declared signedness and rounding semantics.

## Work, dependencies and memory

| Model feature | Architecture questions | Required record |
|---|---|---|
| Loop nest | Static bounds, work per iteration, recurrence distance? | Operation count and scheduling options |
| Reduction | Reordering allowed by the numeric contract? | Accumulator width, reduction order and latency |
| Image/window access | Layout, borders, strides and padding? | Line/window buffers and exact indexing |
| Random access or transpose | Full-frame storage or bounded tile? | Capacity, bandwidth, ports and latency |
| Lookup | Initialization ownership, contents and index range? | Storage wrapper and out-of-range behavior |
| Conditional path | Output alignment and legal states/modes? | Latency, enables and error behavior |

Calculate capacity from declared dimensions and widths. Estimate port demand
and external-memory bandwidth before partitioning arrays. DSP count and latency
depend on device, widths, scheduling and binding; use synthesis evidence rather
than fixed operation-to-resource ratios.

## Throughput and interfaces

Compute required samples per second from the accepted workload. Compare it with
clock frequency times sustained samples per cycle, including stalls and protocol
overhead. Record latency independently of throughput; an II target is not a result.

Declare scalar, stream or memory-mapped interfaces from project requirements.
Specify packing, ordering, valid/ready behavior, frame markers, reset and error
handling. Keep configuration/status semantics distinct from sample transport.
Do not derive a bus choice or clock target from a Python function signature alone.

## Handoff

Produce the reviewed dataflow, numeric table, memory plan, target budgets and
verification matrix in `templates/micro_arch_template.md`. For HLS, consult the
shared [scheduling reference](../../fpga-ip-design/references/pragma_cheatsheet.md).
Every proposed transformation must preserve the frozen golden boundary or have
an explicitly reviewed contract change before implementation.
