// TODO: unfinished scaffold; review and verify before use.
//
// Configuration and status register scaffold
// Scope: register-bank interface only; outputs and bus behavior are not implemented.
// TODO: define the register and transaction contract.

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

    // TODO: register address map
    // TODO: write strobes and read behavior
    // TODO: interrupt status and clearing semantics
    // TODO: reviewed field access definitions

endmodule
