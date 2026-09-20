# HLS Pragma Cheatsheet

> **Purpose**: 教 architect-fpga 在 micro-arch doc 中正确使用 HLS Pragma。
> **Reference**: skills/fpga-ip-design/references/pragma_cheatsheet.md

## 1. Pipeline 类

### `#pragma HLS PIPELINE II=N`
- 启动间隔（initiation interval）
- II=1 → 每 cycle 处理一个数据
- II=N → 每 N cycle 处理一个数据
- 默认 II 由综合器决定

### `#pragma HLS LOOP_TRIPCOUNT min=N max=M avg=K`
- 告知综合器循环边界（无此 pragma 综合器假设 loop=infinite）
- 用于 latency 估算

### `#pragma HLS PIPELINE off`
- 显式关闭 pipeline（如边界循环）

## 2. Parallelism 类

### `#pragma HLS UNROLL [factor=N]`
- 空间展开
- `factor=N`：部分展开（每 N 次循环 1 次迭代）
- 不指定 factor：完全展开

### `#pragma HLS DATAFLOW`
- 任务级并行
- 多个函数/循环可同时执行
- 自动插入 ping-pong buffer

## 3. Array 类

### `#pragma HLS ARRAY_PARTITION variable=X complete`
- 全展开（每个元素独立 register）
- 适用：< 64 元素的小数组

### `#pragma HLS ARRAY_PARTITION variable=X cyclic factor=N`
- 周期性展开
- factor=N：每 N 个一组

### `#pragma HLS ARRAY_PARTITION variable=X block factor=N`
- 块状展开
- factor=N：每 N 个一块

### `#pragma HLS ARRAY_RESHAPE variable=X complete dim=0`
- 合并多个 dim 为一个
- 例：`int arr[2][3]` → `int arr[6]`

## 4. Resource 类

### `#pragma HLS RESOURCE variable=X core=RAM_2P`
- 强制用 BRAM 双口 RAM

### `#pragma HLS RESOURCE variable=X core=RAM_2P_URAM`
- 强制用 URAM

### `#pragma HLS RESOURCE variable=X core=RAM_2P_LUTRAM`
- 强制用 LUTRAM（分布式 RAM）

### `#pragma HLS RESOURCE variable=X core=MUL`
- 强制用 DSP 乘法器

### `#pragma HLS RESOURCE variable=X latency=4`
- 强制资源 latency

## 5. Interface 类

### `#pragma HLS INTERFACE s_axilite port=reg`
- AXI4-Lite slave（CSR 寄存器）
- 访问：PS 端 Python `ip.write(0x10, value)`

### `#pragma HLS INTERFACE axis port=in_stream`
- AXI4-Stream input
- 含 tdata/tkeep/tlast/tvalid/tready

### `#pragma HLS INTERFACE m_axi port=dma_buf depth=1024`
- AXI4 master（DMA）
- 访问 DDR4 buffer

### `#pragma HLS INTERFACE ap_none port=port_name`
- Native port（无协议）

### `#pragma HLS INTERFACE ap_ctrl_hs port=return`
- 标准 control：ap_start, ap_done, ap_idle, ap_ready

## 6. Stream 类

### `#pragma HLS STREAM variable=s depth=N`
- 显式声明 stream depth
- depth=1：FIFO
- depth=N：N 元素缓冲

### `#pragma HLS DATA_PACK variable=struct`
- struct 字段打包为 1 个 stream word

## 7. Function 类

### `#pragma HLS INLINE`
- 函数内联（消除函数调用开销）

### `#pragma HLS INLINE off`
- 函数不内联

### `#pragma HLS FUNCTION_INSTANTIATE variable=N`
- 函数多实例化（每 N 1 份）

## 8. Loop 嵌套示例

```cpp
for (y = 0; y < H; y++) {
    #pragma HLS LOOP_TRIPCOUNT min=1080 max=2160
    for (x = 0; x < W; x++) {
        #pragma HLS PIPELINE II=1

        for (ky = 0; ky < 3; ky++) {
            #pragma HLS UNROLL
            for (kx = 0; kx < 3; kx++) {
                #pragma HLS UNROLL
                sum += buf[y+ky][x+kx] * kernel[ky][kx];
            }
        }
    }
}
```

**资源估算**：
- 外层：2D loop，无 unroll
- 中层：3-iter, unroll → 3 × body
- 内层：3-iter, unroll → 3 × body
- 总 body = 9 × (multiply + add) = 9 DSP
- 1 cycle latency per outer iteration（II=1）

## 9. 常见错误

❌ **UNROLL 嵌套但 memory port 不够** → 加 `ARRAY_PARTITION`
❌ **PIPELINE II=1 在 feedback loop** → 综合失败
❌ **DATAFLOW 在依赖 task** → 编译错误
❌ **INTERFACE s_axilite port=arr[0]** → 必须用 s_axilite 包装单个寄存器

## 10. 综合报告解读

```
INFO: [HLS 200-111] Finished RTL generation
INFO: [HLS 200-789] Estimated Fmax: <N> MHz
```

**Fmax < target** → 减 UNROLL factor 或 加寄存器 retiming

```
INFO: [HLS 200-1510] Pipelining result: Target II = 1, Final II = 4
```

**Final II > Target** → 检查 memory port 限制

---

**Maintainer**: VibeSilicon Phase Owner
**Date**: 2026-06-28
