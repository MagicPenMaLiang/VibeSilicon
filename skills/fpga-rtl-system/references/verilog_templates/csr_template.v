// TODO 占位（Phase 0 D5 填）
//
// CSR（Configuration and Status Register）模板
// 适用：APB/AXI-Lite 从机接口的标准寄存器组
// 计划 §6.1.5 4 类常见模式 → CSR

module csr_template #(
    parameter ADDR_WIDTH = 8,
    parameter DATA_WIDTH = 32
) (
    input  wire                    clk_i,
    input  wire                    rst_n_i,
    input  wire [ADDR_WIDTH-1:0]   addr_i,
    input  wire [DATA_WIDTH-1:0]   wdata_i,
    input  wire                    we_i,
    input  wire                    re_i,
    output reg  [DATA_WIDTH-1:0]   rdata_o,
    output reg                     irq_o
);

    // TODO: 寄存器地址映射
    // TODO: 写脉冲 + 读组合
    // TODO: 中断状态寄存器 + 清中断
    // TODO: 位域访问宏（CSRF_FIELD 之类）

endmodule
