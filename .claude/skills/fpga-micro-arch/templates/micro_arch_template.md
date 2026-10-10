# Micro-Architecture Document Template
# ===========================================
#
# Purpose:  architect-fpga 输出的微架构文档模板
# Usage:    复制此文件到 project/<phase>_<ip>/micro_arch/<module>_arch.md
#           然后填写 6 大章节
# Reference: skills/fpga-micro-arch/SKILL.md
#
# 6 个章节（必填）：
# 1. System Interface — 端口、时钟、复位
# 2. Dataflow & Pipeline — 流水线、II、latency、block diagram
# 3. Memory Architecture — Array partition、BRAM/URAM、line buffer
# 4. Compute & Pragma Plan — 每个 loop → pragma 映射
# 5. Resource Budget — LUT/FF/DSP/BRAM 估算 vs KPI
# 6. Validation Strategy — C-Sim test、边界条件

# <module> Micro-Architecture

> **Phase**: <N>
> **IP Type**: <algorithm | phy | timing | mixed | ai_model>
> **Route**: <route-1-rtl | route-2-hls | route-mixed>
> **Target Device**: <part, e.g. xck26-sfvc784-2LV-c>
> **Author**: architect-fpga (opus)
> **Date**: <ISO8601>
> **Version**: v0.1 (draft, 等待 L3.3 签字)

---

## 1. System Interface

### 1.1 端口定义

| 端口 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| `clk_i` | input | 1 | 主时钟（PL fabric clock from CFGMCLK） |
| `rst_n_i` | input | 1 | 异步低有效复位 |
| `<data_i>` | input | <N> | 数据输入 |
| `<data_o>` | output | <M> | 数据输出 |
| `<valid_i>` | input | 1 | 输入 valid |
| `<valid_o>` | output | 1 | 输出 valid |
| `tlast_i` | input | 1 | AXI-Stream last（行结束） |
| ... | ... | ... | ... |

**接口协议**：
- **Native ports**（无 AXI）：用于 IP 内部连接
- **AXI4-Stream**（如有视频流）：8/16/24/32-bit data + tkeep + tlast
- **AXI4-Lite**（如有 CSR）：32-bit addr/data + aw/w/b channels

### 1.2 时钟域

| 时钟域 | 频率 | 源 | 用途 |
|---|---|---|---|
| `clk_i` | <N> MHz | CFGMCLK / external PLL | PL fabric 主时钟 |
| `sck_i` | <M> MHz | SPI master | 仅 Phase 1 SPI Slave 案例 |
| `pclk_i` | <K> MHz | PS AXI | PS ↔ PL 桥接 |

**CDC 策略**：
- 跨时钟域信号：`sck_i`, `cs_n_i`, `mosi_i`（Phase 1）
- 同步器：2-FF + `(* ASYNC_REG = "TRUE" *)`
- XDC：`set_false_path -from [get_clocks sck_i] -to [get_clocks clk_i]`

### 1.3 复位策略

| 复位类型 | 来源 | 范围 | 时序 |
|---|---|---|---|
| `rst_n_i` | 异步低有效 | 全局 | 至少 100μs 上电后释放 |
| `vio_rst_n` | VIO 控制（仅 debug） | 测试 wrapper | 0 → 1 单次释放 |
| `ap_rst_n` | HLS 内部 | 算法模块 | 同步于 clk_i |

---

## 2. Dataflow & Pipeline

### 2.1 流水线级数 & 吞吐

| 指标 | 值 | 来源 |
|---|---|---|
| II（Initiation Interval）| 1 | 目标 1 pixel/cycle |
| Latency | <N> cycles | 从 input valid 到 output valid |
| Throughput | <N> MSamples/s | 1 / II × clk_freq |
| Pixel rate | 4K@120fps = <N> MPixels/s | Phase 2 目标 |
| Total data per frame | 3840 × 2160 = 8.3M pixels | 4K 标准 |

### 2.2 Block Diagram

> 用 `drawio-skill` 生成。导出到 `micro_arch/<module>_arch.drawio` + `micro_arch/<module>_arch.png`

```
[Input] → [Pre-process] → [Compute] → [Post-process] → [Output]
              ↓              ↓             ↓
         [Line buffer]  [DSP array]   [Saturation]
```

### 2.3 数据依赖图

- **依赖 1**：pre-process 输出 → compute 输入（1 cycle 延迟）
- **依赖 2**：compute 输出 → post-process 输入（2 cycles 延迟）
- **并行机会**：pre-process 下一个 frame 与 compute 当前 frame 可并行（Dataflow）

### 2.4 Dataflow 区域

| 区域 | 启动条件 | 任务 | 缓冲 |
|---|---|---|---|
| pre-process | ap_start | 行扫描 + 边界填充 | h_size line buffer |
| compute | line ready | DSP multiply-add | <N>×<M> window |
| post-process | ap_done | 饱和 + 量化输出 | double buffer |

---

## 3. Memory Architecture

### 3.1 Array Partition 策略

| Python 数组 | 访问模式 | Partition 策略 | 资源估算 |
|---|---|---|---|
| `img_in[1920][1080]` | 行扫描 (row) | `complete dim=2` | 4 BRAM36 + 4 BRAM18 |
| `img_out[1920][1080]` | 行写入 | `complete dim=2` | 4 BRAM36 + 4 BRAM18 |
| `kernel[3][3]` | 3×3 窗口 | `complete` | 0 (LUT/FF) |
| `linebuf[2][1920]` | 滑动窗口 | `cyclic factor=2` | 2 BRAM18 |

### 3.2 BRAM / URAM / LUTRAM 分配

| 存储类型 | 使用场景 | Phase 2 估算 |
|---|---|---|
| BRAM 36K | 中小 buffer（line buffer）| <X> |
| BRAM 18K | 小 buffer（window / FIFO）| <X> |
| URAM | 大 buffer（frame buffer）| <X> |
| LUTRAM | 分布式 RAM（小于 64 元素）| <X> |

### 3.3 Line Buffer Sizing

```
当前行 + 前一行 + 前两行 = 3 × 1920 × 8-bit = 4.5 KB
→ 1 个 BRAM18 足够（每个 18Kbit = 2.25 KB）
```

### 3.4 Stream vs Random Access

- **Stream**（推荐）：pixel-by-pixel 流动 → 适合 pipelined HLS
- **Random access**：需要 frame buffer → 适合 image processing 但 latency 高

**本设计选择**：Stream（input AXIS）+ 内部 line buffer（random access 局部）

---

## 4. Compute & Pragma Plan

### 4.1 Python → HLS Pragma 映射

| Python 代码 | HLS 代码 | Pragma | 资源 |
|---|---|---|---|
| `for y in range(H): for x in range(W):` | `ROW_LOOP: for(int y=0; y<H; y++)` | `#pragma HLS PIPELINE II=1` | — |
| `for ky in range(3): for kx in range(3):` | `KERNEL_LOOP: for(int ky=0; ky<3; ky++)` | `#pragma HLS UNROLL` | DSP × 9 |
| `out[x] = in[x] * gain` | `out = in * gain` | (内联) | DSP × 1 |
| `if pix > 255: pix = 255` | `pix = max(pix, 255)` | (内联) | LUT × 1 |

### 4.2 DSP 分配

| 操作 | DSP 数量 | 说明 |
|---|---|---|
| 3×3 卷积核 | 9 | 完全展开（UNROLL）|
| 1×1 标量乘 | 1 | 简单 multiply |
| 累加器 | 1 | 跨周期累加 |
| **总计** | **<N>** | vs KPI：DSP ≤ <M> |

### 4.3 关键路径

| 路径 | 延迟估算 | 优化手段 |
|---|---|---|
| pixel_in → multiply → add → register | 8 ns @ 100 MHz | Pipeline, register retiming |
| BRAM read → register | 5 ns | BRAM 内部 pipeline |
| 3×3 kernel sum | 12 ns | Tree sum（log₂N 级数）|

### 4.4 Pragma 完整清单

```cpp
void compute(...) {
    #pragma HLS INTERFACE s_axilite port=return
    #pragma HLS INTERFACE axis port=in_stream
    #pragma HLS INTERFACE axis port=out_stream

    #pragma HLS DATAFLOW

    hls::stream<ap_uint<24>> pix_buf;
    #pragma HLS STREAM variable=pix_buf depth=2

    for (int y = 0; y < H; y++) {
        #pragma HLS PIPELINE II=1
        for (int x = 0; x < W; x++) {
            #pragma HLS UNROLL factor=4  // 4-way spatial parallelism

            ap_uint<24> in_pix = pix_in[x][y];
            ap_uint<24> kernel[3][3] = {{...}};
            ap_uint<24> sum = 0;
            for (int ky = 0; ky < 3; ky++) {
                #pragma HLS UNROLL
                for (int kx = 0; kx < 3; kx++) {
                    #pragma HLS UNROLL
                    sum += pix_buf[ky][x+kx-1] * kernel[ky][kx];
                }
            }
            pix_out[x][y] = clip(sum, 0, 255);
        }
    }
}
```

---

## 5. Resource Budget

### 5.1 资源估算

| 资源 | IP 估算 | Wrapper (debug) | KPI 阈值 | 状态 |
|---|---|---|---|---|
| CLB LUTs | <N> | <M> | ≤ <X> | ✅ / ⚠️ |
| CLB Registers | <N> | <M> | ≤ <X> | ✅ / ⚠️ |
| Block RAM 36K | <N> | <M> | ≤ <X> | ✅ / ⚠️ |
| Block RAM 18K | <N> | <M> | ≤ <X> | ✅ / ⚠️ |
| URAM | <N> | <M> | ≤ <X> | ✅ / ⚠️ |
| DSP | <N> | <M> | ≤ <X> | ✅ / ⚠️ |

### 5.2 时序估算

| 指标 | 目标 | 估算 | 状态 |
|---|---|---|---|
| Target Fmax | <N> MHz | <M> MHz | ✅ / ⚠️ |
| Critical path | <N> ns | <M> ns | ✅ / ⚠️ |

### 5.3 与 KPI 对齐

如果估算超 KPI，标注缓解措施：

| 超限资源 | 超限 | 缓解策略（按 plan §4.6）|
|---|---|---|
| BRAM > 80% | <原因> | URAM 替代 / Array partition 改 cyclic |
| DSP > 90% | <原因> | 减少并行度 / 复用 DSP over time |
| LUT > 90% | <原因> | 拆分模块 / 状态机精简 |

---

## 6. Validation Strategy

### 6.1 C-Sim Test Plan

| Test # | 输入 | 期望输出 | 边界条件 |
|---|---|---|---|
| TC-01 | 全 0 图像 | 全 0 输出 | 零值 |
| TC-02 | 全 255 图像 | 全 255 输出 | 饱和值 |
| TC-03 | 棋盘格 | 棋盘格输出 | 边界保持 |
| TC-04 | 8×8 patch | patch 输出一致 | 局部性 |
| ... | ... | ... | ... |

### 6.2 边界条件

| 边界 | 行为 | Python golden 一致性 |
|---|---|---|
| 行首（x=0） | 左边界像素 = 原值 | ✅ |
| 行尾（x=W-1） | 右边界像素 = 原值 | ✅ |
| 图像首尾 | 第一行/最后一行 = 边界扩展 | ✅ |
| 整数饱和 | 像素 < 0 → 0; > 255 → 255 | ✅ |
| 整数溢出 | 16-bit 中间结果截位 | ✅ |

### 6.3 PSNR / SSIM 目标（图像类 IP）

| 指标 | Target | Hard Min |
|---|---|---|
| PSNR (vs Python golden) | ≥ 45 dB | ≥ 40 dB |
| SSIM | ≥ 0.99 | ≥ 0.95 |

**测量方法**：`python-sim-mcp` 加载 `img_in.npy` + `img_out_python.npy` + `img_out_hls.npy` → 计算 PSNR/SSIM。

### 6.4 板级验证（Phase 2）

- **Self-contained**（推荐）：CFGMCLK + VIO 驱动，无需外部 SPI/I2C
- **External**：需要 jumper + 外部 100 MHz + 外部协议 master
- **ILA probes**：11+ signals (count, state, addr, data, valid, ready)

---

## 7. 签字清单（L3.3 人工检查点）

待 Phase Owner 签字（在 `docs/signatures/<module>.arch.signed`）：

- [ ] **接口设计**：端口/时钟/复位 合理性
- [ ] **资源预算**：估算 vs KPI 合理性（避免超限）
- [ ] **Pragma 计划**：每个 Python loop 对应显式 pragma

---

## 8. 关联文档

- `specs/<module>.md` — 算法 spec 输入
- `golden/<module>.py` — 定点 Python 黄金参考
- `docs/kpi_target.yaml` — 资源/时序 KPI 预算
- `config/target.yaml` — 目标器件
- `skills/fpga-ip-design/SKILL.md` — 后续 coder 用
- `skills/fpga-ppa-analysis/SKILL.md` — 后续 reviewer 验证

---

# 附录 A：路线一变体（Pure RTL / Python→RTL）

> **适用场景**：`module.type = phy | timing | mixed`（控制密集、PHY 接口、CDC 桥接）
> **工具**：手写 Verilog/SystemVerilog，或 Amaranth / MyHDL（Python→RTL 变体）
> **与 HLS 路线（§1-§6）区别**：无 HLS pragma，章节内容不同

## A.1 System Interface

### A.1.1 FSM 时序图

```
        ┌────────┐  start_i  ┌────────┐  done  ┌────────┐  ack_i  ┌────────┐
        │        │ ────────→ │        │ ─────→ │        │ ─────→ │        │
        │ S_IDLE │           │S_ACTIVE │        │ S_DONE │        │ S_IDLE │
        │        │           │        │ ←───── │        │         │        │
        └────────┘           └────────┘  ack   └────────┘         └────────┘
```

### A.1.2 寄存器堆接口

| 接口 | 类型 | 用途 |
|---|---|---|
| `s_axil_*` | AXI4-Lite slave | PS 端 CSR 访问 |
| `data_i/o` | Native | 数据路径 |
| `valid_i/o`, `ready_i/o` | Stream handshake | 数据流 |

详见 `references/axi4_lite_slave.md`。

## A.2 FSM 设计

### A.2.1 状态转移表

| 当前状态 | 输入条件 | 下一状态 | 输出（Moore）|
|---|---|---|---|
| S_IDLE | `start_i && ready_i` | S_ACTIVE | `ready_o=1, valid_o=0` |
| S_ACTIVE | `done_compute` | S_DONE | `ready_o=0, valid_o=0` |
| S_ACTIVE | `!done_compute` | S_ACTIVE | `ready_o=0, valid_o=0` |
| S_DONE | `ack_i` | S_IDLE | `ready_o=1, valid_o=1` |

### A.2.2 状态编码

选择（按状态数）：
- ≤ 4 状态：**Binary**（节省 FF）
- 4-16 状态：**One-Hot**（FPGA 推荐，无 glitch）
- > 16 状态：Binary
- 跨时钟域：Gray

### A.2.3 复位策略

- **同步复位**（推荐）：避免异步路径，简化 XDC
- **异步复位**（需 3-FF 同步器）：上电立即生效

详见 `references/rtl_fsm_design.md`。

## A.3 寄存器堆设计

### A.3.1 地址映射

| Offset | Name | R/W | Reset | Description |
|---|---|---|---|---|
| 0x00 | REG_CTRL | RW | 0x0 | bit 0 enable; bit 1 reset; bit 2-3 mode |
| 0x04 | REG_STATUS | RO | 0x1 | bit 0 ready; bit 1 busy; bit 2 error |
| 0x08 | REG_TX_DATA | WO | 0x0 | 触发发送 |
| 0x0C | REG_RX_DATA | RO | 0x0 | 读取清零 |
| 0x10 | REG_IRQ_EN | RW | 0x0 | 中断使能 |
| 0x14 | REG_IRQ_STATUS | W1C | 0x0 | 写 1 清中断 |

### A.3.2 位域定义

| Register | Bits | Field | R/W | Reset | Description |
|---|---|---|---|---|---|
| REG_CTRL | 0 | enable | RW | 0 | 模块使能 |
| REG_CTRL | 1 | soft_rst | RW | 0 | 软件复位 |
| REG_CTRL | 2-3 | mode | RW | 0 | 工作模式 |
| REG_CTRL | 31:4 | reserved | - | 0 | 保留（写 0） |

### A.3.3 AXI4-Lite 接口时序

- **写延迟**：3 cycles（AW + W → B）
- **读延迟**：3 cycles（AR → R）

详见 `references/register_file_pattern.md` + `references/axi4_lite_slave.md`。

## A.4 Compute & RTL 实现（替代 HLS pragma）

### A.4.1 Python→RTL 工具选择

| 工具 | 推荐场景 |
|---|---|
| 手写 Verilog/SV | PHY 接口、超高频控制 |
| **Amaranth**（推荐）| 控制 FSM + 简单数据路径（Python 测试友好）|
| MyHDL | 学习/快速原型 |
| migen | 与 migen 现有代码集成 |

### A.4.2 Amaranth 翻译示例（SPI Slave FSM）

```python
from amaranth import *

class SPISlaveFSM(Elaboratable):
    def __init__(self):
        self.sck_i = Signal()
        self.cs_n_i = Signal()
        self.mosi_i = Signal()
        self.data_o = Signal(8)

        # CDC synchronizers
        self.sck_sync = Signal(2)
        self.cs_n_sync = Signal(2, reset=3)

    def elaborate(self, platform):
        m = Module()
        fsm_state = Signal(2, reset=0)
        bit_count = Signal(4, reset=0)
        cmd_buf = Signal(8)

        # CDC: 2-FF synchronizer
        m.d.sync += self.sck_sync.eq(Cat(self.sck_sync[1], self.sck_i))
        m.d.sync += self.cs_n_sync.eq(Cat(self.cs_n_sync[1], self.cs_n_i))

        # Moore FSM
        with m.FSM():
            with m.State("IDLE"):
                with m.If(~self.cs_n_sync[1]):
                    m.next = "CMD_RX"
            with m.State("CMD_RX"):
                with m.If(self.sck_sync[1] & ~self.sck_sync[0]):
                    m.d.sync += cmd_buf.eq(Cat(cmd_buf[1:], self.mosi_i))
                    m.d.sync += bit_count.eq(bit_count + 1)
                    with m.If(bit_count == 8):
                        m.d.sync += fsm_state.eq("ADDR_RX")
                        m.d.sync += bit_count.eq(0)
        return m
```

详见 `references/python_to_rtl_tools.md`。

## A.5 Resource Budget（手写 vs HLS 对比）

| 方案 | LUT | FF | DSP | BRAM |
|---|---|---|---|---|
| 手写 RTL（路线一）| ~150-300 | ~200-400 | 0 | 0 |
| HLS 综合（路线二）| ~150-300 | ~200-400 | 0 | 0 |
| Python→RTL (Amaranth) | ~150-300 | ~200-400 | 0 | 0 |

**差异**：通常 < 20%。

## A.6 Validation Strategy

### A.6.1 RTL 仿真（Verilog testbench）

```systemverilog
module counter_tb;
    reg clk_i, rst_n_i;
    reg sck_i, cs_n_i, mosi_i;
    wire [7:0] data_o;
    wire ready_o, valid_o;

    counter uut (.clk_i(clk_i), .rst_n_i(rst_n_i), ...);

    initial begin
        clk_i = 0;
        forever #5 clk_i = ~clk_i;  // 100 MHz
    end

    initial begin
        rst_n_i = 0;
        #100 rst_n_i = 1;

        // SPI 协议测试
        send_cmd(8'h01);  // WRITE
        send_addr(8'h00);
        send_data(8'hFF);

        #1000 $finish;
    end

    task send_cmd(input [7:0] cmd);
        // 9 SCK: 1 transition + 8 data
        cs_n_i = 0;
        sck_i = 0; #10;
        for (int i = 7; i >= 0; i--) begin
            sck_i = 1; #10; mosi_i = cmd[i]; #10;
            sck_i = 0; #10;
        end
    endtask
endmodule
```

### A.6.2 cocotb（Python testbench，路线一变体推荐）

```python
# cocotb test (Linux only, Windows 不可用)
import cocotb
from cocotb.triggers import RisingEdge, Timer
from cocotb.clock import Clock

@cocotb.test()
async def test_counter(dut):
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    dut.rst_n_i.value = 0
    await Timer(100, units="ns")
    dut.rst_n_i.value = 1

    # SPI 测试
    dut.cs_n_i.value = 0
    for cmd in [0x01, 0x00, 0xFF]:
        for i in range(7, -1, -1):
            dut.sck_i.value = 1
            await Timer(10, units="ns")
            dut.mosi_i.value = (cmd >> i) & 1
            await Timer(10, units="ns")
            dut.sck_i.value = 0
            await Timer(10, units="ns")

    await Timer(100, units="ns")
    assert dut.data_o.value == 0xFF, f"FAIL: data_o=0x{int(dut.data_o.value):02x}"
    dut._log.info("PASS")
```

### A.6.3 板级验证（自包含模式，参考 Phase 1）

- **VIO + ILA**（推荐）：无外部设备
- **外部 master**：需要 jumper + 协议 master

## A.7 关联参考

| 主题 | Reference |
|---|---|
| FSM 设计（Moore/Mealy/状态编码） | `references/rtl_fsm_design.md` |
| 寄存器堆（CSR + AXI4-Lite） | `references/register_file_pattern.md` |
| AXI4-Lite Slave 接口 | `references/axi4_lite_slave.md` |
| Python→RTL 工具链 | `references/python_to_rtl_tools.md` |
| CDC 桥接 | `skills/fpga-cdc-check/SKILL.md` |
| Verilog 编码规范 | `skills/fpga-rtl-system/SKILL.md` |

---

**Maintainer**: VibeSilicon Phase Owner
**Date**: <ISO8601>
**Version**: v0.1 (draft, 等待 L3.3 签字)
