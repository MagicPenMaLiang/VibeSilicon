// TODO 占位（Phase 3 W8 填，I2C 推广时实例驱动）
//
// I2C 从机模板（I2C Slave）
// 适用：标准 I2C 协议，7-bit 地址，从机模式
// 计划 §5.3 推广清单（接口协议：SPI/I2C/UART/Ethernet MAC）

module i2c_slave #(
    parameter ADDR_WIDTH = 7,
    parameter DATA_WIDTH = 8
) (
    input  wire                   clk_i,
    input  wire                   rst_n_i,
    input  wire                   scl_i,
    inout  wire                   sda_io,    // 双向
    output reg  [DATA_WIDTH-1:0]  data_o,
    input  wire [DATA_WIDTH-1:0]  data_i,
    output reg                    irq_o
);

    // TODO: 状态机（IDLE / START / ADDR / ACK / DATA / STOP）
    // TODO: 双向 sda_io 用三态门实现
    // TODO: 时钟拉伸（clock stretching）支持

endmodule
