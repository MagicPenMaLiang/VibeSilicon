# TODO 占位（Phase 0 D5 填）

## 用途

HLS Pragma 速查手册。覆盖常用 Pragma 与适用场景。

## 待填内容

| Pragma | 用途 | 适用 |
|---|---|---|
| `#pragma HLS PIPELINE II=N` | 函数级流水线 | 计算密集循环 |
| `#pragma HLS UNROLL factor=N` | 循环展开 | 小循环 + 资源充裕 |
| `#pragma HLS ARRAY_PARTITION` | 数组分块 | 大数组 BRAM→LUTRAM |
| `#pragma HLS RESOURCE variable=X core=RAM_1P` | 指定资源类型 | BRAM/URAM/LUTRAM 选择 |
| `#pragma HLS DATA_PACK` | 结构体打包 | AXI 接口优化 |
| `#pragma HLS INLINE` | 函数内联 | 减少调用开销 |
| `#pragma HLS INTERFACE` | 接口协议 | m_axi / axis / bram 等 |

## 上游引用

- `SKILL.md` → "核心内容" 第 1 项"HLS C++ 编写规范"
- 计划 §4.5 HLS C++ 输出要求
