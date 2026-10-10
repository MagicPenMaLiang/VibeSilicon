# Timing summaries and task routing

This reference interprets canonical `report_timing_summary` metrics. Critical-path
diagnosis and design changes belong to the focused skills below.

| Metric | Interpretation |
|---|---|
| WNS | Negative values indicate a setup failure |
| TNS | Negative values indicate a set of setup violations |
| WHS/THS | Negative values or nonzero failing hold endpoints mean FAIL |
| Unconstrained paths | Nonzero paths prevent timing sign-off as PASS |

1. Resource, power and summary timing trends: use `fpga-ppa-analysis`.
2. Existing `.dcp` with critical-path, clock-interaction or root-cause questions:
   use read-only `fpga-dcp-analysis` (R0).
3. RTL, XDC or implementation changes: complete DCP diagnosis first, then use
   `fpga-timing-closure` with R2 approval and a controlled optimization experiment.

Do not infer pipelining, clock relaxation or false paths from WNS alone. These
proposals require critical-path, clock-interaction, CDC/protocol evidence and
explicit functional invariants.
