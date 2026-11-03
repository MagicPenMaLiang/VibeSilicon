# DCP diagnostic criteria

Distinguish observations from inferences. WNS/TNS/WHS, endpoints, path groups,
logic levels and cell/net delays are observations. Root-cause categories are
inferences and require supporting and contradictory evidence.

| Category | Minimum evidence | Action when insufficient |
|---|---|---|
| LOGIC_DEPTH | Critical-path logic levels and cell-delay fraction | Mark UNKNOWN |
| ROUTE_DOMINATED | Net/route-delay fraction, physical and fanout information | Do not suggest blind pipelining |
| HIGH_FANOUT | Fanout values and multiple affected paths | Do not recommend replication without evidence |
| CLOCK_OR_CONSTRAINT_SUSPECT | Clock interaction, exceptions and unconstrained paths | Request human constraint review |
| HOLD | WHS/THS, failing endpoints and minimum-delay paths | Do not substitute a setup optimization |

Include the checkpoint hash, timing evidence ID, Vivado version/design state,
setup/hold metrics, three critical paths, category, confidence, supporting and
contradictory evidence, and next action. Preserve raw `.rpt` files alongside any summary.
