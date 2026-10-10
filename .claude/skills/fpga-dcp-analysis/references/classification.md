# DCP 诊断判据

诊断必须区分“观测”和“推断”。WNS/TNS/WHS、起终点、path group、logic levels、cell/net delay 是观测；根因类别是推断，必须列出支持和反证。

| 类别 | 最少证据 | 不足时处理 |
|---|---|---|
| LOGIC_DEPTH | 关键路径逻辑级数 + cell delay 占比 | 标记 UNKNOWN |
| ROUTE_DOMINATED | net/route delay 占比 + 物理/扇出信息 | 不建议盲目加流水 |
| HIGH_FANOUT | fanout 数值 + 多条受影响路径 | 不建议复制寄存器 |
| CLOCK_OR_CONSTRAINT_SUSPECT | clock interaction/exception/未约束路径证据 | 转人工约束评审 |
| HOLD | WHS/THS/hold endpoints + min-delay 路径 | 不用 setup 优化代替 |

输出至少包含：checkpoint hash、timing evidence ID、Vivado/design state、setup/hold 指标、前三条关键路径、类别、confidence、支持证据、反证、下一步建议。不得只保存 LLM 摘要而丢弃原始 `.rpt`。
