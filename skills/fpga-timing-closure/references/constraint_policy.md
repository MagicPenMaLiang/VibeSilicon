# 时序约束变更策略

以下做法必须阻塞：

- 为消除 WNS，给全部寄存器或整组端口加 false path；
- 未证明时钟异步就使用 `set_clock_groups -asynchronous`；
- 只写 multicycle setup，不写对应 hold N-1；
- 用通配符命中数量不明的对象；
- 只比较 WNS，不复查 unconstrained paths、hold、CDC、功能和资源。

允许进入批准流程的 exception 必须具备：明确 from/to、对象命中数量、设计意图、CDC/协议/接口 proof evidence ID、前后 `report_exceptions -coverage`、G2/G3/G4 复验。证据不能由提出同一变更的 Coder 自签。
