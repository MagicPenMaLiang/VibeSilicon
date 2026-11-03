# Safe timing constraints

## Base constraints

Clocks and I/O delays must come from the board/interface specification. Declare
both minimum and maximum I/O delays. Generated clocks must identify their real
source pin or port. Confirm the system frequency target before changing a period.

```tcl
create_clock -name core_clk -period $reviewed_period [get_ports core_clk_i]
set_input_delay -clock core_clk -max $reviewed_input_max [get_ports data_i]
set_input_delay -clock core_clk -min $reviewed_input_min [get_ports data_i]
set_output_delay -clock core_clk -max $reviewed_output_max [get_ports data_o]
set_output_delay -clock core_clk -min $reviewed_output_min [get_ports data_o]
```

## Exceptions require evidence

Treat `set_false_path`, `set_clock_groups -asynchronous` and `set_multicycle_path`
as sensitive changes. Use an `fpga-timing-closure` proposal with exact from/to
objects, match counts and content-addressed CDC/protocol/interface proof.

- Do not apply broad exceptions to `*`, `all_registers` or `all_clocks`.
- Pair multicycle setup N with the corresponding hold N-1 under the reviewed clock semantics.
- Justify asynchronous clock groups with the actual CDC architecture.
- A reset or debug signal name alone does not justify a false path.

After a change, run `report_timing_summary`, `report_clock_interaction`,
`report_exceptions -coverage` and `report_cdc -all_checks_per_endpoint`. Recheck
functional/protocol behavior, hold and unconstrained paths.
