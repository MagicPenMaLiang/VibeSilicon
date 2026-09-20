# 时序约束安全指南

## 基础约束

时钟和 I/O delay 必须来自板级/接口规范，并显式使用 `-min` 与 `-max`。生成时钟必须指向实际源引脚或端口，修改周期前先确认系统频率目标。

```tcl
create_clock -name clk_100m -period 10.0 [get_ports clk_i]
set_input_delay  -clock [get_clocks clk_100m] -min 2.0 [get_ports data_i]
set_input_delay  -clock [get_clocks clk_100m] -max 4.0 [get_ports data_i]
set_output_delay -clock [get_clocks clk_100m] -min 1.0 [get_ports data_o]
set_output_delay -clock [get_clocks clk_100m] -max 3.0 [get_ports data_o]
```

## Exception 不是修复手段

`set_false_path`、`set_clock_groups -asynchronous` 和 `set_multicycle_path` 属于敏感变更。它们必须进入 `fpga-timing-closure` 提案，并带明确 from/to、对象命中数量及内容寻址的 CDC/协议/接口证明。

- 禁止对 `*`、`all_registers`、`all_clocks` 等宽泛对象添加 exception。
- multicycle 必须成对设置 setup N 和 hold N-1。
- 异步 clock group 必须由真实 CDC 架构证明，不能因为跨域报告难处理就添加。
- 复位和 debug 信号也不能仅凭名称设为 false path。

每次变更后运行 `report_timing_summary`、`report_clock_interaction`、`report_exceptions -coverage` 和 `report_cdc -all_checks_per_endpoint`，并复验功能、协议、hold 与 unconstrained paths。
