`default_nettype none

module counter_selfcheck_tb;
    logic clk_i;
    logic rst_ni;
    logic enable_i;
    logic [7:0] count_o;

    counter dut (
        .clk_i,
        .rst_ni,
        .enable_i,
        .count_o
    );

    initial clk_i = 1'b0;
    always #5 clk_i = ~clk_i;

    initial begin
        rst_ni = 1'b0;
        enable_i = 1'b0;
        repeat (2) @(posedge clk_i);
        @(negedge clk_i);
        rst_ni = 1'b1;
        enable_i = 1'b1;
        repeat (4) @(posedge clk_i);
        @(negedge clk_i);
        if (count_o !== 8'd4) begin
            $fatal(1, "counter mismatch: expected 4, got %0d", count_o);
        end
        $display("COUNTER_SELF_CHECK_PASS");
        $finish;
    end
endmodule

`default_nettype wire
