# 时序指标汇总与路由

本参考只负责解释 canonical `report_timing_summary` 指标，不做关键路径深度诊断或设计修改。

| 指标 | 判定 |
|---|---|
| WNS | `< 0` setup FAIL；`0~0.5ns` WARN |
| TNS | `< 0` 表示存在 setup 违例集合 |
| WHS/THS | `< 0` 或 hold failing endpoints 非零即 FAIL |
| unconstrained paths | 非零时不能签核 timing PASS |

路由规则：

1. 只需资源/功耗/汇总时序趋势：留在 `fpga-ppa-analysis`。
2. 已有 `.dcp`，需要查看关键路径、时钟交互或根因：转 `fpga-dcp-analysis`，仅 R0。
3. 需要改 RTL、XDC 或实现策略：必须先完成 DCP 分析，再转 `fpga-timing-closure`，按 R2 批准与优化实验闭环执行。

禁止从 WNS 单值推断“加流水”“放宽时钟”或“加 false path”。这些结论至少需要关键路径、clock interaction、CDC/协议证据和功能不变量。
