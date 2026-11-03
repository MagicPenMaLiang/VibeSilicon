# Queries for FPGA development and debug

Discover the live tool schema first. On 2026-10-30, AMD Doc Search 0.12.1 exposed
`vivado_doc_search(query, limit, alpha, tool, version, family)`. Only query was
required; filters were arrays of supported enum strings. The service can evolve.

An example for an explicitly declared Vivado 2024.2 project:

```json
{
  "query": "UG835 report_timing_summary report_unconstrained options",
  "tool": ["Vivado Design Suite"],
  "version": ["2024.2"],
  "limit": 3,
  "alpha": 0.2
}
```

Alpha blends keyword (0) and semantic (1) search. Lower keyword-oriented values
can help exact message/command identifiers; retain the actual query and judge
the results rather than assuming one universal value. The tool name still says
Vivado when querying Vitis. A supported Vitis tool filter is `tool: ["Vitis"]`;
HLS is not an invented `"Vitis HLS"` enum. Device-family filters must likewise
match the discovered schema rather than a part-number string.

| Stage | Useful query content | Verify before acting |
|---|---|---|
| Algorithm to RTL | Arithmetic type/cast, RAM collision or DSP inference plus target release | Numeric model and memory contract still govern implementation |
| RTL/elaboration | Exact Synth message ID plus failing construct and language mode | Actual cited source context, first causal error, release-specific semantics |
| Simulation | Simulator/version, assertion ID or crash signature, library mode | Tool/library defect versus a DUT failure; relevant Answer Record release |
| IP/BD | Product guide, exact IP version, CONFIG field, enabled mode | Design-time versus propagated versus runtime controls; property readback |
| Constraints/CDC | Exact clock/exception command and crossing topology | Command edition, exception scope and independent CDC justification |
| Timing/resources | Methodology message, inference or constrained-object diagnostic | Implementation stage and measured report evidence; no blanket protection removal |
| Hardware debug | ILA/probe property, hw_server/tool release, observed error | Device family, matching artifacts and sample clock; existing board-operation gates |
| Optional SoC | Platform/domain/processor, API or boot component and software release | Family-specific boot inputs, actual generated artifacts and boot evidence |
| Optional HLS | Reported loop/II limiter, directive and scope, selected release | Applied directive/schedule, recurrence versus memory ports, RTL co-simulation |

## Result traps observed during service validation

- A query filtered to 2024.2 returned UG835 chunks tagged with several releases
  including 2024.2, but the URL named 2025.1. This is a candidate citation with
  VERSION_UNCONFIRMED until the original source is verified for the target.
- A Vitis/2024.2 query about UG1399 returned an unrelated DS643 memory-controller
  data sheet tagged All. Its successful tool response did not answer the query.
  Narrow the identifier/keywords or use the actual release's original manual;
  do not promote it to a Vitis/HLS recommendation.

Keep an exact message ID for diagnosis, but remove project-specific identifiers
and design content from hosted queries. Summarize only the source passage needed
for the engineering decision; retain provenance and uncertainty rather than
copying a complete manual into the project.
