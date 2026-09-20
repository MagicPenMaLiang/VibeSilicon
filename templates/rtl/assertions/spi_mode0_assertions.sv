`default_nettype none

// Module       : spi_mode0_assertions
// Purpose      : Bindable SPI Mode 0 framing and idle-level assertions.
// Clocks       : monitor_clk_i for idle checks; sck_i for transfer bit count.
// Resets       : rst_ni, active-low assertion disable sampled by monitor_clk_i.
// Interfaces   : SPI CSn/SCK/MOSI/MISO observation only.
// Numeric      : MOSI/MISO are uninterpreted serial payload bits.
// Latency      : No DUT latency assumption.
// Throughput   : CSn may cover one or more complete eight-bit words.
// Invariants   : SCK is idle-low; CSn deasserts only on a byte boundary.
// Generated    : false; maintained verification template.
module spi_mode0_assertions (
    input wire monitor_clk_i,
    input wire rst_ni,
    input wire cs_n_i,
    input wire sck_i,
    input wire mosi_i,
    input wire miso_i
);

`ifndef SYNTHESIS
    logic [2:0] bit_count_q;
    logic       sck_q;

    always_ff @(posedge monitor_clk_i) begin
        if (!rst_ni) begin
            bit_count_q <= 3'd0;
            sck_q       <= 1'b0;
        end else if (cs_n_i) begin
            bit_count_q <= 3'd0;
            sck_q       <= sck_i;
        end else if (!sck_q && sck_i) begin
            bit_count_q <= bit_count_q + 3'd1;
            sck_q       <= sck_i;
        end else begin
            sck_q       <= sck_i;
        end
    end

    spi_idle_low_p: assert property (
        @(posedge monitor_clk_i) disable iff (!rst_ni)
        cs_n_i |-> !sck_i
    );

    spi_complete_byte_p: assert property (
        @(posedge monitor_clk_i) disable iff (!rst_ni)
        $rose(cs_n_i) |-> bit_count_q == 3'd0
    );

    spi_no_unknown_control_p: assert property (
        @(posedge monitor_clk_i) disable iff (!rst_ni)
        !$isunknown({cs_n_i, sck_i, mosi_i, miso_i})
    );
`endif

endmodule

`default_nettype wire
