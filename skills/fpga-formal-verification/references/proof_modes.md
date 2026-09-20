# 证明模式与适用边界

| 变更 | 首选证明 | 仍需保留的验证 |
|---|---|---|
| 组合表达式、常量、位宽、signedness | combinational equivalence | lint、bit-exact golden |
| 寄存器重构、流水、状态编码 | sequential equivalence | latency/协议断言、仿真 |
| FSM、FIFO、仲裁、握手 | property checking | cover、仿真、综合 |
| CDC、异步 reset | property checking + CDC analysis | 结构 CDC、实现报告 |
| XDC only | 不做 RTL equivalence | timing、CDC、exception coverage |
| vendor IP/加密网表 | boundary property/blackbox contract | vendor 仿真模型、实现 |

Bounded proof 只能声称“在 depth N 内未发现反例”，不能表述为无限深度证明。Sequential equivalence 必须说明 reset 映射、初态、输出对齐和允许的 latency 差异。Assumption 必须来自接口、协议或环境证据，并逐条带内容寻址 evidence ID。
