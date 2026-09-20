# TODO 占位（Phase 2 W5 填）

## 用途

XPM_CDC / XPM_FIFO_ASYNC 使用示例与实例化模板。

## 待填内容

### XPM_CDC 单 bit 同步

```verilog
xpm_cdc_single #(
    .DEST_SYNC_FF(4),    // 同步级数 2-10
    .INIT_SYNC_FF(0),
    .SIM_ASSERT_CHK(0)
) inst_xpm_cdc_single (
    .src_clk(1'b0),      // 单 bit 可不需要 src_clk
    .src_in(src_sig),
    .dest_clk(dst_clk),
    .dest_out(dst_sig)
);
```

### XPM_FIFO_ASYNC 异步 FIFO

```verilog
xpm_fifo_async #(
    .FIFO_MEMORY_TYPE("auto"),        // auto / block / distributed / ultra
    .FIFO_DEPTH(1024),
    .WRITE_DATA_WIDTH(64),
    .READ_DATA_WIDTH(64),
    .RELATED_CLOCKS(0)                // 0 = 不同时钟
) inst_async_fifo (
    .wr_clk(src_clk),
    .wr_en(wr_en),
    .din(wr_data),
    .full(full),
    .rd_clk(dst_clk),
    .rd_en(rd_en),
    .dout(rd_data),
    .empty(empty),
    .wr_data_count(wr_count),
    .rd_data_count(rd_count)
);
```

### AXI4-Stream Register Slice

```verilog
axis_register_slice #(
    .TDATA_WIDTH(64)
) inst_axis_slice (
    .aclk(aclk),
    .aresetn(aresetn),
    .s_axis_tvalid(s_valid),
    .s_axis_tready(s_ready),
    .s_axis_tdata(s_data),
    .m_axis_tvalid(m_valid),
    .m_axis_tready(m_ready),
    .m_axis_tdata(m_data)
);
```

## 上游引用

- `SKILL.md` → "Vivado 原语使用"
- 计划 §6.1.3 核心内容
- 计划 §4.6 ⑦ 抗亚稳态设计
