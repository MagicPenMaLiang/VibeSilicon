# TODO 占位（Phase 0 D5 填）

## 用途

资源分析详细流程 + 阈值表（Phase 2 stream-processing 99.6% 危机处理用）。

## 待填内容

### 资源类型与关注点

| 资源 | 关注点 | 典型阈值 | 优化策略 |
|---|---|---|---|
| BRAM | 18Kb/36Kb 双口存储 | < 60% 预警，< 80% 报警 | URAM 迁移、ARRAY_PARTITION |
| URAM | 大容量 Line Buffer | 越多越好 | BIND_STORAGE impl=URAM |
| DSP | 乘加密集算法 | < 90% PASS | 降精度、改用 LUT 实现 |
| LUT | 控制逻辑 + 分布式 RAM | < 90% PASS | FSM 编码优化、状态压缩 |
| FF | 流水线深度参考 | < 90% PASS | 寄存器合并、复位优化 |

### csynth 报告解析

```bash
# 触发 csynth
cd hls_build && vitis_hls -f csynth.tcl 2>&1 | tee ../reports/csynth.log

# 解析 BRAM 使用率
grep "BRAM" reports/csynth.log
# 预期：BRAM_18K = X / 445 (X%)
# 阈值：< 60% PASS
```

### impl_1 报告解析

```bash
# 触发 vivado impl
vivado -mode batch -source scripts/vivado_impl.tcl 2>&1 | tee reports/impl.log

# 解析资源
grep -A 20 "Utilization Design" reports/impl.log
```

## 上游引用

- `SKILL.md` → "资源分析（Area）"
- 计划 §6.5.1 ③ 资源估算 + ⑥ 资源真实层
- 计划 §4.6 BRAM 资源危机缓解策略（8 项）
