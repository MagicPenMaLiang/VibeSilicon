# TODO 占位（Phase 0 D5 填）

## 用途

功耗估算方法 + `report_power` 输出解读。

## 待填内容

### 功耗类型

| 类型 | 来源 | 估算方法 |
|---|---|---|
| 动态功耗 | 时钟频率 × 翻转率 × 寄生电容 | `report_power` |
| 静态功耗 | 漏电流 × 工艺参数 | `report_power` |

### 命令模板

```tcl
# scripts/vivado_report_power.tcl
open_project <project>.xpr
open_run impl_1
# 设置 switching activity（未仿真时默认 12.5%）
set_switching_activity -default_static_probability 0.5 -default_static_toggle_rate 12.5
report_power -file reports/power.rpt
```

### 输出解读

```
Power summary:
  Total On-Chip Power: X W
    Dynamic:        Y W (Z%)
    Static:         W W (V%)
  Confidence level:  High / Medium / Low
```

### 优化策略

- **动态功耗高**：降低时钟频率、Clock Gating、关闭未用模块
- **静态功耗高**：工艺选择（28nm → 16nm）、Power Gating

## 上游引用

- `SKILL.md` → "功耗分析（Power）"
- 计划 §6.1.4 契约接口
