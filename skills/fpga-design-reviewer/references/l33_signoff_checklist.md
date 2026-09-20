# L3.3 高风险 RTL 与工程结果人工签核

> 规范真源：仓库根目录 `docs/rtl_coding_standard.md` 和 `config/rtl_quality_rules.json`。下方旧 JSON 示例仅供字段迁移参考，不能作为已批准的签核证据。签核人必须是真实责任人并与提出人分离，Agent 不得代签。

## 当前签核合同

正式记录须符合 `schemas/rtl_quality_signoff.schema.json`，绑定源码 commit、FPGA/ASIC 与 handwritten/generated Profile、规范/策略版本、规则 ID、范围、原始证据 ID、风险结论、批准人和 UTC 批准时间。PHY、上电/跨域复位、安全/密钥、时钟/时序例外、ASIC DFT/低功耗及发布结论按适用性签核。源码、约束或证据变化后重新评估；缺证据或未批准为 BLOCKED，不得将普通 RTL lint PASS 当成签名。豁免另按 `schemas/rtl_quality_waiver.schema.json` 登记 owner、期限、补偿验证和移除条件。

## 责任与判定

RTL/架构 owner 对接口、数值和流水线负责；CDC/复位/时序 owner 对跨域、复位、时钟和时序例外负责；FPGA owner 对器件原语、实现和板级结论负责；ASIC owner 对 PDK、宏、DFT/低功耗及 STA/DRC/LVS 负责；安全/PHY 专家对对应高风险项负责。项目可合并授权角色，但提出者与批准者必须分离。

记录状态只有绑定证据的 PASS、明确阻塞的 BLOCKED、附原因的 NOT_APPLICABLE。不得用 `signed: true` 或文件存在与否判定已签核。签名验证和审批身份复验的自动化属第二轮，当前必须人工核对。

## 上游引用

- `SKILL.md` → "L3.3 关键结果签字" 操作规范
- 计划 §1.11 半自动化工作流（L3.3 1-2 小时/项目）
- 计划 §6.3.2 reviewer-fpga L3.3 职责
- 红线 5：不跳过 L3.3 关键结果签字
