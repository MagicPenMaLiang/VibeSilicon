# AXI4-Lite Slave Interface — PS-PL Standard CSR Bus

> **Purpose**: 教 architect-fpga 设计 AXI4-Lite slave 接口（PS-PL 标准 CSR 总线）。
> **Reference**: skills/fpga-micro-arch/references/register_file_pattern.md
> **Audience**: architect-fpga + coder-fpga（任何含 CSR 的 IP）

## 1. 为什么用 AXI4-Lite

- **Zynq SoC 标准**：PS 端 ARM 通过 AXI 访问 PL 端 IP
- **Vivado IP-Integrator 自动连线**：Address Editor 自动分配地址
- **PS 端 Python 友好**：pynq 库直接 `mmio.write(0x10, value)`

## 2. AXI4-Lite 信号清单

### 2.1 写地址通道（AW）

```verilog
input  wire [11:0] s_axil_awaddr;   // 写地址（byte 地址）
input  wire        s_axil_awvalid;  // 地址 valid
output reg         s_axil_awready;  // IP ready 接收地址
input  wire [2:0]  s_axil_awprot;   // 保护类型（通常忽略）
```

### 2.2 写数据通道（W）

```verilog
input  wire [31:0] s_axil_wdata;    // 写数据
input  wire [3:0]  s_axil_wstrb;    // byte strobe（哪几个 byte 有效）
input  wire        s_axil_wvalid;
output reg         s_axil_wready;
```

### 2.3 写响应通道（B）

```verilog
output reg  [1:0]  s_axil_bresp;    // 响应：OKAY/EXOKAY/SLVERR/DECERR
output reg         s_axil_bvalid;
input  wire        s_axil_bready;
```

### 2.4 读地址通道（AR）

```verilog
input  wire [11:0] s_axil_araddr;
input  wire        s_axil_arvalid;
output reg         s_axil_arready;
input  wire [2:0]  s_axil_arprot;
```

### 2.5 读数据通道（R）

```verilog
output reg  [31:0] s_axil_rdata;
output reg  [1:0]  s_axil_rresp;
output reg         s_axil_rvalid;
input  wire        s_axil_rready;
```

## 3. 时序图

### 3.1 写事务

```
PS                                                PL (IP)
│                                                  │
│  AWADDR + AWVALID ──────┐                        │
│  AWREADY ◄──────────────┤  1 cycle              │
│                          ┘                        │
│  WDATA + WVALID ──────────┐                       │
│  WREADY ◄─────────────────┤  1 cycle              │
│                            ┘                       │
│  (内部写 reg)                                     │
│  BVALID ──┐                                       │
│  BRESP    │                                       │
│  BREADY ──┘  1 cycle                              │
│                                                   │
└─ 3 cycles total ────────────────────────────────┘
```

### 3.2 读事务

```
PS                                                PL (IP)
│                                                  │
│  ARADDR + ARVALID ──────┐                        │
│  ARREADY ◄──────────────┤  1 cycle              │
│                          ┘                        │
│  (内部读 reg)                                     │
│  RDATA + RVALID ──────────┐                       │
│  RRESP                    │                       │
│  RREADY ◄────────────────┘  1 cycle              │
│                                                   │
└─ 3 cycles total ────────────────────────────────┘
```

## 4. 标准实现（AXI4-Lite Slave）

### 4.1 完整 Verilog 模板

```verilog
module axil_csr_slave #(
    parameter ADDR_WIDTH = 12,
    parameter DATA_WIDTH = 32,
    parameter N_REGS     = 32
) (
    input  wire                    clk_i,
    input  wire                    rst_n_i,

    // AXI4-Lite
    input  wire [ADDR_WIDTH-1:0]   s_axil_awaddr_i,
    input  wire                    s_axil_awvalid_i,
    output reg                     s_axil_awready_o,
    input  wire [DATA_WIDTH-1:0]   s_axil_wdata_i,
    input  wire [3:0]              s_axil_wstrb_i,
    input  wire                    s_axil_wvalid_i,
    output reg                     s_axil_wready_o,
    output reg  [1:0]              s_axil_bresp_o,
    output reg                     s_axil_bvalid_o,
    input  wire                    s_axil_bready_i,
    input  wire [ADDR_WIDTH-1:0]   s_axil_araddr_i,
    input  wire                    s_axil_arvalid_i,
    output reg                     s_axil_arready_o,
    output reg  [DATA_WIDTH-1:0]   s_axil_rdata_o,
    output reg  [1:0]              s_axil_rresp_o,
    output reg                     s_axil_rvalid_o,
    input  wire                    s_axil_rready_i,

    // User CSR interface
    output wire [DATA_WIDTH-1:0]   reg_q [0:N_REGS-1]
);

localparam RESP_OKAY = 2'b00;

reg [DATA_WIDTH-1:0] regs [0:N_REGS-1];
reg aw_hs, w_hs, b_pending;
reg ar_hs, r_pending;

// Write address handshake
always @(posedge clk_i) begin
    if (!rst_n_i) aw_hs <= 1'b0;
    else if (s_axil_awvalid_i && !aw_hs) aw_hs <= 1'b1;
    else if (aw_hs) aw_hs <= 1'b0;
end

assign s_axil_awready_o = !aw_hs;

// Write data handshake
always @(posedge clk_i) begin
    if (!rst_n_i) w_hs <= 1'b0;
    else if (s_axil_wvalid_i && !w_hs) w_hs <= 1'b1;
    else if (w_hs) w_hs <= 1'b0;
end

assign s_axil_wready_o = !w_hs;

// Write response
always @(posedge clk_i) begin
    if (!rst_n_i) begin
        b_pending <= 1'b0;
        s_axil_bvalid_o <= 1'b0;
        s_axil_bresp_o  <= RESP_OKAY;
    end else begin
        if (aw_hs && w_hs && !b_pending) begin
            b_pending <= 1'b1;
            s_axil_bvalid_o <= 1'b1;
            s_axil_bresp_o  <= RESP_OKAY;
        end else if (b_pending && s_axil_bready_i) begin
            b_pending <= 1'b0;
            s_axil_bvalid_o <= 1'b0;
        end
    end
end

// Write data capture
always @(posedge clk_i) begin
    if (aw_hs && w_hs) begin
        case (s_axil_wstrb_i)
            4'b0001: regs[s_axil_awaddr_i[ADDR_WIDTH-1:2]][7:0]   <= s_axil_wdata_i[7:0];
            4'b0010: regs[s_axil_awaddr_i[ADDR_WIDTH-1:2]][15:8]  <= s_axil_wdata_i[15:8];
            4'b0100: regs[s_axil_awaddr_i[ADDR_WIDTH-1:2]][23:16] <= s_axil_wdata_i[23:16];
            4'b1000: regs[s_axil_awaddr_i[ADDR_WIDTH-1:2]][31:24] <= s_axil_wdata_i[31:24];
            4'b0011: regs[s_axil_awaddr_i[ADDR_WIDTH-1:2]][15:0]  <= s_axil_wdata_i[15:0];
            4'b1100: regs[s_axil_awaddr_i[ADDR_WIDTH-1:2]][31:16] <= s_axil_wdata_i[31:16];
            4'b1111: regs[s_axil_awaddr_i[ADDR_WIDTH-1:2]]          <= s_axil_wdata_i;
        endcase
    end
end

// Read address handshake
always @(posedge clk_i) begin
    if (!rst_n_i) ar_hs <= 1'b0;
    else if (s_axil_arvalid_i && !ar_hs) ar_hs <= 1'b1;
    else if (ar_hs) ar_hs <= 1'b0;
end

assign s_axil_arready_o = !ar_hs;

// Read data
always @(posedge clk_i) begin
    if (!rst_n_i) begin
        r_pending <= 1'b0;
        s_axil_rvalid_o <= 1'b0;
        s_axil_rdata_o  <= '0;
        s_axil_rresp_o  <= RESP_OKAY;
    end else begin
        if (ar_hs && !r_pending) begin
            r_pending <= 1'b1;
            s_axil_rvalid_o <= 1'b1;
            s_axil_rdata_o  <= regs[s_axil_araddr_i[ADDR_WIDTH-1:2]];
            s_axil_rresp_o  <= RESP_OKAY;
        end else if (r_pending && s_axil_rready_i) begin
            r_pending <= 1'b0;
            s_axil_rvalid_o <= 1'b0;
        end
    end
end

// Export to user logic
genvar i;
generate
    for (i = 0; i < N_REGS; i = i + 1) begin: gen_reg_q
        assign reg_q[i] = regs[i];
    end
endgenerate

endmodule
```

## 5. Vivado IP-Integrator 集成

### 5.1 添加 IP

1. **Tools → Create and Package New IP**
2. 选择 **AXI4 Peripheral** 模板
3. 配置 N_REGS
4. 修改 IP 代码为上面的模板
5. **Package IP** 重新打包

### 5.2 Address Editor 分配

```
Address Map:    0x43C0_0000 - 0x43C0_FFFF  (64 KB region)
Offset 0x00:    REG_CTRL       (RW)
Offset 0x04:    REG_STATUS     (RO)
Offset 0x08:    REG_TX_DATA    (WO)
...
```

## 6. PS 端 Python 访问（pynq）

```python
from pynq import MMIO

# AXI4-Lite 基地址（Vivado Address Editor 分配）
BASE_ADDR = 0x43C00000
RANGE = 0x10000  # 64 KB

mmio = MMIO(BASE_ADDR, RANGE)

# 读
status = mmio.read(0x04)  # REG_STATUS
print(f"status = 0x{status:08x}")

# 写
mmio.write(0x00, 0x00000001)  # REG_CTRL = enable
mmio.write(0x08, 0xDEADBEEF)  # REG_TX_DATA

# 等待
import time
timeout = 1.0
start = time.time()
while not (mmio.read(0x04) & 0x01):  # ready?
    if time.time() - start > timeout:
        raise TimeoutError("Not ready")
    time.sleep(0.01)

rx = mmio.read(0x0C)  # REG_RX_DATA
```

## 7. micro-arch doc 中的 AXI4-Lite 章节

```markdown
## 1.4 PS-PL 接口

### 接口协议

- **PS 端**：Python via pynq.MMIO
- **PL 端**：AXI4-Lite Slave
- **时钟域**：`s_axil_aclk` (PS AXI 时钟) → `clk_i` (PL fabric)
- **跨时钟域**：需 AXI clock-to-fabric 同步（XPM_CDC 或单 bit）

### 寄存器地址映射

| Offset | Name | R/W | Reset | Description |
|---|---|---|---|---|
| 0x00 | REG_CTRL | RW | 0x0 | 控制 |
| 0x04 | REG_STATUS | RO | 0x1 | 状态 |

### 读写延迟

- 写：3 cycles（AW + W + B）
- 读：3 cycles（AR + R）
```

## 8. 与 HLS ap_ctrl_hs 对比

| 特性 | AXI4-Lite (手写) | ap_ctrl_hs (HLS) |
|---|---|---|
| 适用 | CSR（少寄存器）| 数据流（多输入输出）|
| 延迟 | 3 cycle | 1 cycle (ap_start/ap_done) |
| 复杂度 | 中（5 通道）| 低（自动生成）|
| Vivado 集成 | IP-Integrator 标准 | HLS IP-XACT 标准 |
| Python 访问 | pynq.MMIO | pynq.Overlay |

**选择**：
- CSR（< 32 寄存器）+ PS 端 Python → **AXI4-Lite 手写**
- 流式数据 + 大 block → HLS ap_ctrl_hs / AXI4-Stream

## 9. 时序约束

```tcl
# Vivado XDC
create_clock -name s_axil_aclk -period 10.0 [get_ports s_axil_aclk_i]
create_clock -name clk_i -period 10.0 [get_ports clk_i]

# CDC: AXI → fabric
set_false_path -from [get_clocks s_axil_aclk] -to [get_clocks clk_i]
set_false_path -from [get_clocks clk_i] -to [get_clocks s_axil_aclk]
```

## 10. 常见错误

❌ **AWREADY 和 WREADY 不同步** → AXI 协议违例
❌ **b_resp_o 漏 BRESP_OKAY** → PS 端报错
❌ **不处理 wstrb** → byte 写错位
❌ **rdata 组合逻辑输出** → 时序违例
❌ **bvalid 不等 bready** → 数据丢失

---

**Maintainer**: VibeSilicon Phase Owner
**Date**: 2026-06-28