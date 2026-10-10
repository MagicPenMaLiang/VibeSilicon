# Algorithm Profiling — Extract Hardware Info from Python

> **Purpose**: 教 architect-fpga 从 Python 定点代码中提取 FPGA 硬件微架构所需信息。
> **Reference**: skills/fpga-micro-arch/SKILL.md §"Algorithm Profiling"

## 1. 位宽提取

### 1.1 numpy 类型 → ap_uint<N>

| Python 代码 | 硬件对应 |
|---|---|
| `np.uint8` | `ap_uint<8>` |
| `np.uint10` | `ap_uint<10>` |
| `np.uint12` | `ap_uint<12>` |
| `np.uint16` | `ap_uint<16>` |
| `np.int8` | `ap_int<8>` |
| `np.int16` | `ap_int<16>` |

**红线 2**：位宽必须严格对应。**不要**在翻译时调整位宽。

### 1.2 Q_FRAC 提取

```python
# Python Q0.8 量化（8-bit 小数）
x = np.uint8(round(x_float * 256))  # Q0.8
y = (x * k) >> 8  # 恢复 Q0.8

# HLS 等价
ap_uint<8> x = (ap_uint<8>)(x_float * 256);
ap_uint<8> y = (x * k) >> 8;
```

| Python 模式 | HLS 等价 |
|---|---|
| `* 256` | `<< 8` 或乘 256 |
| `>> 8` | `>> 8`（硬件 shift 1 cycle）|
| `round()` | 需要额外 LUT 实现 round-to-nearest |
| `int()` | truncation（默认 0 LSB 丢弃）|

## 2. 循环边界提取

### 2.1 嵌套循环 → HLS loop

```python
# Python
for y in range(H):
    for x in range(W):
        pix = img[x][y]  # 行优先
```

```cpp
// HLS 等价
ROW: for (int y = 0; y < H; y++) {
    #pragma HLS LOOP_TRIPCOUNT min=1080 max=2160
    COL: for (int x = 0; x < W; x++) {
        #pragma HLS PIPELINE II=1
        ap_uint<8> pix = img[x][y];
    }
}
```

### 2.2 循环类型 → Pragma

| Python 模式 | HLS Pragma | 说明 |
|---|---|---|
| 内层 `for x in range(W)` | `#pragma HLS PIPELINE II=1` | 行内并行 |
| 卷积核 3×3 | `#pragma HLS UNROLL` | 全部展开 |
| 帧间循环 | `#pragma HLS DATAFLOW` | task-level 并行 |
| 边界循环（y=0 或 y=H-1）| `#pragma HLS PIPELINE off` | 边界无流水 |

### 2.3 循环依赖分析

```python
# 无依赖 → UNROLL
for i in range(N):
    out[i] = in[i] * gain

# 有依赖（累加）→ 不能 UNROLL
for i in range(N):
    sum += in[i] * weight[i]
```

**架构决策**：
- 无依赖 → 空间并行（UNROLL factor=N）
- 有依赖 → 时间并行（PIPELINE II=1，N 周期完成）

## 3. 数组访问模式

### 3.1 行扫描（最常见）

```python
for y in range(H):
    for x in range(W):
        pix = img[x][y]  # 顺序读
```

→ **Partition 策略**：`partition dim=2`（内层 dim 完全展开）

### 3.2 窗口访问（卷积）

```python
# 3×3 窗口
for y in range(H):
    for x in range(W):
        for ky in range(3):
            for kx in range(3):
                pix = img[x+kx-1][y+ky-1]
```

→ **Line buffer + 滑动窗口**：
- 当前行 + 前一行 + 前两行 = 3 行 buffer
- 每行 W 个像素 = 3 × W × 8-bit

### 3.3 跨步访问（downsample）

```python
for y in range(0, H, 2):  # 步长 2
    for x in range(0, W, 2):
        pix = img[x][y]
```

→ **Stride 2** → 简单丢弃，**无**特殊硬件

### 3.4 随机访问（矩阵转置）

```python
# out[y][x] = in[x][y]  # 转置
```

→ **需要 frame buffer**（BRAM 大缓冲）→ latency 显著增加

## 4. 数学运算识别

### 4.1 加法 / 减法

- 8-bit + 8-bit = 9-bit（carry）→ 自动 free
- 16-bit + 16-bit = 17-bit → 自动 free
- 多 bit 加法 → LUT 实现（CARRY8 chain），**不**消耗 DSP

### 4.2 乘法

- 8×8 → 16-bit → 1 DSP（KV260 上）
- 16×16 → 32-bit → 1 DSP
- 24×24 → 48-bit → 2 DSP（KV260 上 27×18 limit）
- **量化**：如果有 Q_FRAC，乘法结果需要左移 Q_FRAC 恢复整数

### 4.3 除法

- **整数除法**：消耗 30+ cycles + LUT（不推荐）→ **避免在 critical path**
- **位移替代**：`/ 256` → `>> 8`（1 cycle）
- **乘倒数**：`/ x` → `* (1/x)`，1/x 预计算（1 DSP）
- **流水线除法器**：Vitis HLS 提供 `#pragma HLS PIPELINE` 可接受，~30 cycles latency

### 4.4 三角函数（sqrt/sin/cos）

- **hls::sqrt / hls::sin / hls::cos**（自带，迭代实现，~30 cycles）
- **CORDIC**（旋转算法，纯移位加法，~20 cycles/iter）
- **Lookup table**（小角度精度足够，2-3 BRAM）

## 5. 条件分支

### 5.1 简单饱和

```python
if pix > 255: pix = 255
```

→ HLS：`pix = max(pix, 255)`（1 cycle，1 LUT）

### 5.2 多分支

```python
if mode == 0:
    gain = 1
elif mode == 1:
    gain = 2
else:
    gain = 4
```

→ HLS FSM（2-3 cycles latency，多 LUT）

### 5.3 数据相关分支

避免 HLS critical path → 用 select instead of branch：
```cpp
ap_uint<8> gain = (mode == 0) ? 1 : (mode == 1) ? 2 : 4;
```

## 6. 输入输出模式

### 6.1 函数输入

| 模式 | 硬件接口 |
|---|---|
| `def f(x, y): return z` | `ap_ctrl_hs` + `ap_none` ports |
| `def f(in_stream, out_stream):` | AXI4-Stream |
| `def f(ctrl_reg, status_reg, ...):` | AXI4-Lite + multiple regs |
| `def f(dma_in, dma_out):` | AXI4 + DMA + 内存映射 |

### 6.2 数据格式

- **Scalar**：`int` → `ap_uint<N>`
- **Vector**：`np.array([N])` → `ap_uint<N> arr[N]` 或 hls::stream
- **Matrix**：`np.array([H][W])` → `ap_uint<N> arr[H][W]` + partition
- **Image**：`np.array([H][W][C])` → 同上，C 维通常 partition complete

## 7. 性能需求提取

```python
# Python 注释
# 4K @ 120fps = 3840 × 2160 × 120 = 995M pixels/s
# Latency < 1 frame = < 8.3 ms
```

→ 硬件目标：
- **Throughput**：≥ 1 pixel / cycle @ 150 MHz = 150 MSamples/s（**不**够 4K@120）
- → 必须 **2-3 pixel / cycle** parallelism @ 300-500 MHz

## 8. 资源约束

从 `kpi_target.yaml` 提取：
```yaml
resources:
  lut_max: 300
  ff_max: 400
  bram_max: 0
  dsp_max: 0
```

→ 架构决策必须**严格**满足这些约束（无 KPI 不优化）。

---

**Maintainer**: VibeSilicon Phase Owner
**Date**: 2026-06-28
