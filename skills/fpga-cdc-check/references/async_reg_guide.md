# TODO 占位（Phase 0 D5 填）

## 用途

ASYNC_REG 标注规范 + 扫描脚本输入格式。

## 待填内容

### ASYNC_REG 标注规范

```verilog
// 单 bit 跨时钟域同步（2 级 FF）
(* ASYNC_REG = "TRUE" *) reg sync_d1;
(* ASYNC_REG = "TRUE" *) reg sync_d2;
always @(posedge dst_clk or negedge rst_n) begin
    if (!rst_n) {sync_d2, sync_d1} <= 2'b00;
    else        {sync_d2, sync_d1} <= {sync_d1, src_data};
end
```

### 扫描脚本输入格式

```python
# scan_async_reg.py 解析的源文件示例
# 识别模式：跨时钟域的 reg 变量，但缺少 (* ASYNC_REG = "TRUE" *) 标注

# 输入：源文件列表
# 输出：JSON {"missing": [{"file": "src/cdc.v", "line": 42, "signal": "sync_d1"}], "count": 1}
```

### 检测算法（待实现）

1. 解析 Verilog/SV，识别所有 `reg` 变量
2. 查找跨时钟域赋值（`always @(posedge clkX)` 中读 `clkY` 域信号）
3. 检查每个跨域 reg 是否有 `ASYNC_REG` 属性
4. 缺失的列入 missing[]

## 上游引用

- `SKILL.md` → "CDC 桥接模式" + "L1 静态扫描"
- 计划 §6.5.1 ② ASYNC_REG 静态扫描
- 计划 §11.2 ② ASYNC_REG 静态扫描命令
