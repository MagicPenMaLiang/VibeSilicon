# TODO 占位（Phase 0 D5 填）

## 用途

3 级 CDC 检查详细流程与命令模板。

## 待填内容

### L1 静态扫描（每次保存触发）

```bash
# verilator lint
verilator --lint-only -Wall -Wno-DECLFILENAME src/*.v src/*.sv 2>&1 | tee reports/lint.log
# 机器判据：grep -c '^%Error' reports/lint.log == 0

# ASYNC_REG 扫描
python scripts/quality_gate/scan_async_reg.py src/*.v src/*.sv
# 预期输出：{"missing": [], "count": 0}
```

### L2 综合后（Vivado report_cdc）

```tcl
# scripts/vivado_report_cdc.tcl
open_project <project>.xpr
open_run synth_1
report_cdc -all_checks_per_endpoint -file reports/cdc.txt
```

### L3 实现后（report_methodology）

```tcl
open_run impl_1
report_methodology -all_checks_per_endpoint
```

## 阈值与失败处理

| 级别 | 阈值 | 失败处理 |
|---|---|---|
| L1 | ASYNC_REG 缺失数 = 0 | 阻塞 + Coder 加属性 |
| L2 | critical 违例 = 0 | 阻塞 + 人工 review |
| L3 | 无新违例 | PASS |

## 上游引用

- `SKILL.md` → "3 级 CDC 检查方案"
- 计划 §6.1.3 契约接口
- 计划 §6.5.1 ⑤ CDC 拓扑
