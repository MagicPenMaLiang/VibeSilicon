// Neutral register bank; this interface is not AXI-Lite or APB.
// ADDR_WIDTH>=1 and DATA_WIDTH>=1. Addresses are word selectors.
// Address 0: configuration RW. Address 1 bit 0: sticky IRQ, write-one-clear.
// irq_set_i wins over simultaneous clear. Reads are combinational when re_i.
// Reset is synchronous active-low. A reviewed bus adapter supplies we_i/re_i.
module csr_template #(
    parameter ADDR_WIDTH = 8,
    parameter DATA_WIDTH = 32
) (
    input wire clk_i,
    input wire rst_n_i,
    input wire [ADDR_WIDTH-1:0] addr_i,
    input wire [DATA_WIDTH-1:0] wdata_i,
    input wire we_i,
    input wire re_i,
    input wire irq_set_i,
    output reg [DATA_WIDTH-1:0] rdata_o,
    output reg irq_o,
    output wire [DATA_WIDTH-1:0] config_o
);
    localparam [ADDR_WIDTH-1:0] CONFIG_ADDR = {ADDR_WIDTH{1'b0}};
    localparam [ADDR_WIDTH-1:0] IRQ_ADDR = {{(ADDR_WIDTH-1){1'b0}}, 1'b1};
    reg [DATA_WIDTH-1:0] config_q;
    assign config_o = config_q;
    always @(posedge clk_i) begin
        if (!rst_n_i) begin
            config_q <= {DATA_WIDTH{1'b0}};
            irq_o <= 1'b0;
        end else begin
            if (we_i && addr_i == CONFIG_ADDR) config_q <= wdata_i;
            if (irq_set_i) irq_o <= 1'b1;
            else if (we_i && addr_i == IRQ_ADDR && wdata_i[0]) irq_o <= 1'b0;
        end
    end
    always @* begin
        rdata_o = {DATA_WIDTH{1'b0}};
        if (re_i) begin
            case (addr_i)
                CONFIG_ADDR: rdata_o = config_q;
                IRQ_ADDR: rdata_o[0] = irq_o;
                default: rdata_o = {DATA_WIDTH{1'b0}};
            endcase
        end
    end
endmodule
