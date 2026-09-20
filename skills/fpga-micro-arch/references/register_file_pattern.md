# Register File Pattern — CSR Address Map & Read/Write Handshake

> **Purpose**: 教 architect-fpga 设计寄存器堆 / CSR（路线一变体核心模式）。
> **Reference**: skills/fpga-rtl-system/references/cdc_primitives.md + counter.v 案例
> **Audience**: architect-fpga + coder-fpga（phy/timing + mixed 路线）

## 1. CSR 寄存器堆概念

**CSR** (Control and Status Registers) 是 IP 与外部交互的标准方式：
- **PS 端 Python** 通过 AXI4-Lite 读写
- **硬件逻辑** 在 IP 内部更新
- **协议支持**：AXI4-Lite（推荐）/ APB（ARM）/ Custom（简单）

## 2. 地址映射设计

### 2.1 表格形式（推荐）

| Offset | Name | R/W | Width | Reset | Description |
|---|---|---|---|---|---|
| 0x00 | REG_CTRL | RW | 32 | 0x0000_0000 | 控制寄存器：bit 0 enable, bit 1 reset, bit 2 mode |
| 0x04 | REG_STATUS | RO | 32 | 0x0000_0001 | 状态寄存器：bit 0 ready, bit 1 busy, bit 2 error |
| 0x08 | REG_TX_DATA | WO | 32 | 0x0000_0000 | 发送数据（写触发发送） |
| 0x0C | REG_RX_DATA | RO | 32 | 0x0000_0000 | 接收数据（读清零） |
| 0x10 | REG_IRQ_EN | RW | 32 | 0x0000_0000 | 中断使能 |
| 0x14 | REG_IRQ_STATUS | W1C | 32 | 0x0000_0000 | 中断状态（写 1 清零） |
| ... | | | | | |

**关键**：
- **R/W**：可读可写
- **RO**：只读（写忽略）
- **WO**：只写（读返回 0）
- **W1C**：Write 1 to Clear（特殊，写 1 清零 bit）
- **W1S**：Write 1 to Set（特殊，写 1 置位 bit）

### 2.2 Phase 1 SPI Slave 案例

```verilog
// 32 个寄存器（控制 + 状态 + 数据 + IRQ）
reg [31:0] regs [0:31];

// 地址映射
localparam REG_CTRL       = 5'd0;   // 0x00: 控制
localparam REG_STATUS     = 5'd1;   // 0x04: 状态
localparam REG_TX_DATA    = 5'd2;   // 0x08: 发送
localparam REG_RX_DATA    = 5'd3;   // 0x0C: 接收
localparam REG_IRQ_EN     = 5'd4;   // 0x10: 中断使能
localparam REG_IRQ_STATUS = 5'd5;   // 0x14: 中断状态
// 0x06-0x1F: 用户自定义或保留
```

## 3. 读写握手协议

### 3.1 Strobe + Data（最简单，推荐）

```verilog
// 写：写地址 + 数据 + strobe（单 cycle 脉冲）
always @(posedge clk_i) begin
    if (wr_strobe_i) begin
        regs[wr_addr_i] <= wr_data_i;
    end
end

// 读：给地址，下一个 cycle 返回数据
always @(posedge clk_i) begin
    if (!rst_n_i) begin
        rd_data_o <= '0;
    end else if (rd_valid_i) begin
        rd_data_o <= regs[rd_addr_i];  // 1 cycle 延迟
    end
end
```

**优势**：
- 简单，1-2 cycle 延迟
- 适合内部 CSR

### 3.2 Valid + Ready（流式，需要 backpressure）

```verilog
// 写：valid + ready 握手
always @(posedge clk_i) begin
    if (wr_valid_i && wr_ready_o) begin
        regs[wr_addr_i] <= wr_data_i;
    end
end
always @(*) wr_ready_o = 1'b1;  // 总 ready

// 读：valid + ready
always @(posedge clk_i) begin
    if (!rst_n_i) rd_data_o <= '0;
    else if (rd_valid_i && rd_ready_i) begin
        rd_data_o <= regs[rd_addr_i];
    end
end
```

**适用**：AXI4-Stream 风格（高频数据路径）

### 3.3 AXI4-Lite（PS-PL 标准）

详见 `references/axi4_lite_slave.md`

## 4. AXI4-Lite CSR 接口（推荐方案）

### 4.1 时序图

```
AW通道（写地址）：
    AWADDR[11:0] ─────┐
    AWVALID ──────────┼──┐
    AWREADY ──────────┘  │ (1 cycle)

W通道（写数据）：
    WDATA[31:0] ──────┐
    WSTRB[3:0] ───────┼──┐
    WVALID ───────────┘  │
    WREADY ──────────────┘ (1 cycle)

B通道（写响应）：
    BRESP[1:0] ─────┐
    BVALID ─────────┼──┐
    BREADY ─────────┘  │
                     ──┘ (1 cycle)

AR通道（读地址）：
    ARADDR[11:0] ──┐
    ARVALID ────────┼──┐
    ARREADY ────────┘  │
                     ──┘

R通道（读数据）：
    RDATA[31:0] ──┐
    RRESP[1:0] ────┼──┐
    RVALID ────────┘  │
    RREADY ──────────┘
```

### 4.2 Verilog 实现（简化版）

```verilog
module csr_slave #(
    parameter ADDR_WIDTH = 12,
    parameter DATA_WIDTH = 32,
    parameter N_REGS = 32
) (
    input  wire                    clk_i,
    input  wire                    rst_n_i,

    // AXI4-Lite AW
    input  wire [ADDR_WIDTH-1:0]   s_awaddr_i,
    input  wire                    s_awvalid_i,
    output reg                     s_awready_o,

    // AXI4-Lite W
    input  wire [DATA_WIDTH-1:0]   s_wdata_i,
    input  wire [3:0]              s_wstrb_i,
    input  wire                    s_wvalid_i,
    output reg                     s_wready_o,

    // AXI4-Lite B
    output reg  [1:0]              s_bresp_o,
    output reg                     s_bvalid_o,
    input  wire                    s_bready_i,

    // AXI4-Lite AR
    input  wire [ADDR_WIDTH-1:0]   s_araddr_i,
    input  wire                    s_arvalid_i,
    output reg                     s_arready_o,

    // AXI4-Lite R
    output reg  [DATA_WIDTH-1:0]   s_rdata_o,
    output reg  [1:0]              s_rresp_o,
    output reg                     s_rvalid_o,
    input  wire                    s_rready_i,

    // User logic
    output wire [DATA_WIDTH-1:0]   reg_q [0:N_REGS-1]
);

reg [DATA_WIDTH-1:0] regs [0:N_REGS-1];

// Write logic
always @(posedge clk_i) begin
    if (!rst_n_i) begin
        s_awready_o <= 1'b0;
        s_wready_o  <= 1'b0;
        s_bvalid_o  <= 1'b0;
    end else begin
        // AW + W ready
        if (s_awvalid_i && !s_awready_o) s_awready_o <= 1'b1;
        else if (s_awready_o)            s_awready_o <= 1'b0;

        if (s_wvalid_i && !s_wready_o) s_wready_o <= 1'b1;
        else if (s_wready_o)            s_wready_o  <= 1'b0;

        // B response after both AW + W accepted
        if (s_awvalid_i && s_wvalid_i && !s_bvalid_o) begin
            s_bvalid_o <= 1'b1;
        end else if (s_bvalid_o && s_bready_i) begin
            s_bvalid_o <= 1'b0;
        end

        // Write data
        if (s_awvalid_i && s_wvalid_i && s_awready_o && s_wready_o) begin
            case (s_awaddr_i[ADDR_WIDTH-1:2])
                4'h0: regs[ 0] <= ... // byte-strobe write
                // ...
            endcase
        end
    end
end

// Read logic
always @(posedge clk_i) begin
    if (!rst_n_i) begin
        s_arready_o <= 1'b0;
        s_rvalid_o  <= 1'b0;
    end else begin
        if (s_arvalid_i && !s_arready_o) s_arready_o <= 1'b1;
        else if (s_arready_o)            s_arready_o <= 1'b0;

        if (s_arvalid_i && s_arready_o && !s_rvalid_o) s_rvalid_o <= 1'b1;
        else if (s_rvalid_o && s_rready_i)             s_rvalid_o <= 1'b0;

        if (s_arvalid_i && s_arready_o) begin
            s_rdata_o <= regs[s_araddr_i[ADDR_WIDTH-1:2]];
        end
    end
end

endmodule
```

## 5. micro-arch doc 中的 CSR 章节

```markdown
## 3. 寄存器堆设计（路线一变体）

### 3.1 地址映射

| Offset | Name | R/W | Reset | Description |
|---|---|---|---|---|
| 0x00 | REG_CTRL | RW | 0x0 | bit 0: enable; bit 1: reset; bit 2-3: mode |
| 0x04 | REG_STATUS | RO | 0x1 | bit 0: ready; bit 1: busy; bit 2: error |
| 0x08 | REG_TX_DATA | WO | 0x0 | 触发发送 |
| 0x0C | REG_RX_DATA | RO | 0x0 | 读取清零 |
| 0x10 | REG_IRQ_EN | RW | 0x0 | 中断使能 |
| 0x14 | REG_IRQ_STATUS | W1C | 0x0 | 写 1 清中断 |

### 3.2 读写握手

- **写协议**：AXI4-Lite（AW + W + B 三通道）
- **读协议**：AXI4-Lite（AR + R 两通道）
- **延迟**：写 2 cycle（AW+W → B），读 2 cycle（AR → R）

### 3.3 寄存器位定义（位域）

| Register | Bits | Field | R/W | Reset | Description |
|---|---|---|---|---|---|
| REG_CTRL | 0 | enable | RW | 0 | 模块使能 |
| REG_CTRL | 1 | soft_rst | RW | 0 | 软件复位（自清零） |
| REG_CTRL | 2-3 | mode | RW | 0 | 工作模式（0/1/2/3） |
| REG_CTRL | 31:4 | reserved | - | 0 | 保留（写 0） |
```

## 6. 与 Python 黄金参考的位宽一致性

**红线 2**：位宽严格对应

```python
# Python golden
CTRL_REG_ENABLE = 0x01  # bit 0
CTRL_REG_RESET  = 0x02  # bit 1
```

```verilog
// RTL
localparam CTRL_REG_ENABLE = 32'h0000_0001;  // bit 0
localparam CTRL_REG_RESET  = 32'h0000_0002;  // bit 1
```

**红线 1**：不修改位宽、不修改 Q_FRAC（如果涉及小数）

## 7. 与 PS 端 Python 验证脚本

```python
# PS 端读写 CSR
from pynq import MMIO

# 基地址由 Vivado Address Editor 分配
mmio = MMIO(base_addr, length=0x10000)

# 写：触发发送
mmio.write(0x00, 0x01)  # REG_CTRL = enable
mmio.write(0x08, 0xDEADBEEF)  # REG_TX_DATA = 0xDEADBEEF

# 读：等待完成
while (mmio.read(0x04) & 0x01) == 0:  # REG_STATUS ready?
    pass

rx = mmio.read(0x0C)  # REG_RX_DATA
assert rx == expected, f"FAIL: rx=0x{rx:08x} expected=0x{expected:08x}"
print("PASS")
```

## 8. 常见错误

❌ **读返回组合逻辑（无寄存器）** → 时序违例
❌ **写 strobe 缺位选（byte-enable）** → 写错位
❌ **RO 寄存器被 PS 写** → 状态被覆盖
❌ **W1C 写 0 时不清零** → 误解协议
❌ **AXI4-Lite 不支持 burst** → 必须 single beat

## 9. AXI4-Lite vs Custom 寄存器接口

| 方案 | 优势 | 劣势 |
|---|---|---|
| **AXI4-Lite** | Vivado IP-Integrator 标准，PS 端 Python 直接访问 | 5 通道，代码多 |
| **APB** | ARM SoC 标准，代码少 | 不通用 |
| **Custom** | 简单，1-2 通道 | 非标准，PS 端需自定义驱动 |

**推荐**：Phase 1-2 用 AXI4-Lite（Zynq 集成友好）

---

**Maintainer**: VibeSilicon Phase Owner
**Date**: 2026-06-28