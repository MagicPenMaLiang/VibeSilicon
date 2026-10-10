// TODO: unfinished I2C scaffold; no protocol implementation is provided.
//
// I2C slave scaffold
// Scope: illustrative 7-bit slave interface only; no validated I2C behavior.
// TODO: review the protocol and electrical interface contract.

module i2c_slave #(
    parameter ADDR_WIDTH = 7,
    parameter DATA_WIDTH = 8
) (
    input  wire                   clk_i,
    input  wire                   rst_n_i,
    input  wire                   scl_i,
    inout  wire                   sda_io,    // bidirectional
    output reg  [DATA_WIDTH-1:0]  data_o,
    input  wire [DATA_WIDTH-1:0]  data_i,
    output reg                    irq_o
);

    // TODO: state machine (IDLE / START / ADDR / ACK / DATA / STOP)
    // TODO: implement open-drain behavior for bidirectional sda_io
    // TODO: clock stretching support

endmodule
