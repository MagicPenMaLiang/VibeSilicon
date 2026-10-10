# Power evidence quality

Identify measured board power, routed activity-based tool estimates, or vectorless estimates explicitly. Record target, source/configuration hashes, voltage, temperature, operating mode, tool version, stage, static/dynamic breakdown and activity-file hash/annotation coverage.

Check that activity represents reset, idle, active throughput and realistic backpressure. Preserve the measured interval and clock assumptions. Unannotated nets or default toggle rates introduce uncertainty; do not infer precision from decimal formatting.

Compare candidates under the same corner, activity, design contract and tool settings. Board rail totals can include PS, DRAM and peripherals; do not equate them to isolated PL power. ASIC leakage/internal/switching reports belong to separate corners and library views.

Optimization needs a hypothesis and functional/timing/resource guardrails. Clock-enable or operand-isolation changes require startup and wakeup tests. Never add fabric combinational clock gates, silently alter throughput, or treat an estimate as board validation.
