# Optional HLS branch: diagnose before optimizing

Use only when HLS was selected for a component. The default FPGA route remains
algorithm to handwritten RTL; it does not require these tools or reports.

## Read evidence first

Use Vitis HLS MCP `analyze_csynth` with an explicit `report_path` and optional
`log_path`, or `python -m scripts.hls_reports REPORT.xml --root PROJECT_ROOT
--log COMPILE.log`. The reader supports profile-style synthesis XML, including
the Vitis HLS 2024.2 layout. Unknown layouts are BLOCKED; undefined numeric values
remain null and appear in missing_metrics. It does not discover components,
execute HLS, or parse arbitrary tool scripts.

COLLECTED describes extraction, not successful synthesis or target acceptance.
Report fingerprints bind report bytes, not source freshness. Check the run receipt,
source/configuration manifests, tool version, top, part and flow before comparing
reports. Module transaction intervals are not necessarily the inner-loop II.
Estimated HLS clock period is not routed timing or the measured board clock.

Preserve the raw synthesis log. Pipeline start/result INFO lines identify the
loop context; filtering all INFO messages can destroy diagnostic evidence.
The reader returns bounded line-numbered diagnostics with truncation flags.
Inspect the relevant full scheduling block and schedule report when needed.

## II bottleneck decision

| Evidence | Possible limiter | Next diagnostic |
|---|---|---|
| Carried dependency and producer/consumer operations | Recurrence latency / dependence distance | Trace schedule stages through calls, arithmetic and memory |
| Too many accesses in one iteration | Memory ports or bank conflicts | Write a bank/port-by-cycle schedule at the actual unroll factor |
| Shared arithmetic cannot accept every cycle | Allocation/resource sharing | Check operator initiation interval and mux/register scheduling |
| Target/final II differ with timing warnings | Timing pressure plus structural dependencies | Inspect critical operations and target clock; do not relax clocks silently |
| Pragma ignored or target absent | Requested transformation not established | Read inferred directives and release-specific pragma scope |

An array named by a dependency warning does not prove a port shortage. More than
one limiter may coexist. Do not erase a real dependency with a directive or
change the requested II merely to relabel the violation as solved.

## Dataflow and off-chip access

Inventory processes and channels, one writer/reader ownership where applicable,
token counts, startup/control dependencies, PIPO/FIFO storage and stall paths.
Check that the compiler actually created the intended process graph. Test finite
buffer depth and deadlock in RTL co-simulation; C streams can conceal bounded
FIFO behavior. A line-buffer transformation must preserve borders and frame state.

For m_axi bursts inspect interface selection, contiguous access regions, ordering,
alignment, length, aliasing, volatile accesses, shared bundles and traffic overlap.
The selected Vivado/Vitis flow affects default interfaces; do not infer m_axi
from a pointer alone. A source pattern suggests burst eligibility; only the
selected release's reports/co-simulation establish actual transactions.

## Bounded experiments

Reuse scripts/optimization_experiment.py with one hypothesis and unchanged
numeric/reference inputs. Inner exploration can use C simulation plus synthesis
estimates. An accepted RTL candidate still requires applicable G0/G1/G2 and RTL
co-simulation; do not impose a universal percentage-improvement threshold to skip
correctness. Implementation and board evidence remain distinct later stages.
Keep failed attempts and their evidence without compulsory repository commits.

The existing HLS build entrypoints are separate legacy project runners. Verify
their source/solution layout and explicitly provide the reviewed device/clock;
this report reader does not qualify arbitrary projects or add a manifest-based
HLS build flow.
