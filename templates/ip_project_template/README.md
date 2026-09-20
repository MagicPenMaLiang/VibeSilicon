# IP Project Template — VibeSilicon

> **使用**：新 IP 项目复制此目录，替换占位符即可。

如果项目包含 RTL，还须从 `templates/rtl/project_manifest.json.template` 和 `templates/rtl/quality_waivers.json.template` 分别建立项目根目录下的 `rtl_project_manifest.json`、`rtl_quality_waivers.json`。填写完整文件清单后运行 `python -B -m scripts.quality_gate.rtl_waiver_registry <manifest>` 和 `python -B -m scripts.quality_gate.rtl_project_lint <manifest>`；零豁免也要保留空登记文件。模板 README 不等于可直接运行的 manifest。

## 目录结构

```
ip_project_template/
├── README.md                          # ⭐ 项目入口（复制后改占位符）
├── reproduction.json                 # 干净 checkout 复现合同（复制后必须填写）
├── src/
│   ├── rtl/
│   │   └── <IP_NAME>.v               # Verilog RTL 模板
│   ├── constraints/
│   │   └── <IP_NAME>.xdc             # XDC 约束模板
│   ├── sim/
│   │   └── <IP_NAME>_tb.py           # cocotb testbench 模板
│   ├── testbenches/
│   │   └── <IP_NAME>_board_test.tcl  # 板上测试模板
│   └── build/                         # ⭐ Vivado / Vitis build 脚本
│       └── create_<IP_NAME>_project.tcl
├── build/                             # ⭐ 重要 build 输出（项目根级，不在 src/ 下）
│   ├── bitstream/                     # *.bit - 烧录用 bitstream
│   ├── ip/                            # *.xci / *.xpr - 打包好的 IP
│   └── probes/                        # *.ltx - ILA probe 文件
├── specs/
│   └── <IP_NAME>.md                  # IP spec 模板
├── tests/
│   └── <IP_NAME>.yaml                # test vector 模板
├── golden/
│   └── <IP_NAME>.py                  # Python golden reference 模板
├── reports/                           # Vivado / sim 自动生成报告
│   ├── hls/                           # Vitis HLS csim + csynth
│   ├── synth/                         # Vivado synth
│   ├── impl/                          # Vivado impl
│   ├── board/                         # 板级测试
│   └── review/                        # L3 review
├── signatures/                        # L3.3 签字
├── docs/                              # phase-specific 报告
├── micro_arch/                        # architect-fpga 微架构输出
└── tutorials/                         # 教程
```

### `build/` 目录说明

**重要**：`build/` 位于**项目根级**（不在 `src/build/` 下），用于存放 IP 重要的 build 输出物：

| 子目录 | 内容 | 入库策略 |
|---|---|---|
| `build/bitstream/` | `*.bit` Vivado bitstream | ✅ 入库（force-add） |
| `build/ip/` | `*.xci` IP-XACT 打包 / HLS 导出的 IP | ✅ 入库 |
| `build/probes/` | `*.ltx` ILA probe 文件 | ✅ 入库（debug 必备） |

vs `src/build/` 存放 **build 脚本**（.tcl 模板），**不**存放输出物。

详见 `project/README.md` §"`build/` vs `src/build/` vs `reports/`"。

## 使用流程

```bash
# 1. 复制模板
cp -r templates/ip_project_template/ project/phase<N>_<new_ip>/

# 2. 替换占位符
cd project/phase<N>_<new_ip>
find . -type f -exec sed -i 's/<IP_NAME>/<new_ip>/g; s/<PHASE>/<N>/g; s/<NEW_IP>/<new_ip>/g' {} \;

# 3. 编辑 README.md 填 KPI
# 4. 写 specs/<IP_NAME>.md
# 5. 写 golden/<IP_NAME>.py
# 6. 跑 QA
python tools/qa/board_regression/run.py project/phase<N>_<new_ip>/

# 7. 填 reproduction.json 并注册到 config/project_reproduction_catalog.json
# 8. 跑 scripts/project_reproduction.py 验证 catalog
```

## 占位符

| 占位符 | 替换为 | 示例 |
|---|---|---|
| `<IP_NAME>` | snake_case IP 名 | `i2c_slave`, `uart_tx`, `axi_ddr` |
| `<PHASE>` | phase 数字 | `2`, `3` |
| `<NEW_IP>` | 用户定义的 IP 名 | `stream_processing`, `upsampler` |

## 文件模板

### `src/rtl/<IP_NAME>.v`

```verilog
// =============================================================================
// <IP_NAME> - VibeSilicon Phase <PHASE> RTL Template
// =============================================================================
`timescale 1ns / 1ps

module <IP_NAME> #(
    parameter WIDTH = 8
) (
    input  wire             clk_i,
    input  wire             rst_n_i,
    input  wire [WIDTH-1:0] data_i,
    input  wire             valid_i,
    output reg  [WIDTH-1:0] data_o,
    output reg              valid_o
);
    // TODO: implement
    always @(posedge clk_i) begin
        if (!rst_n_i) begin
            data_o  <= {WIDTH{1'b0}};
            valid_o <= 1'b0;
        end else if (valid_i) begin
            data_o  <= data_i;
            valid_o <= 1'b1;
        end
    end
endmodule
```

### `specs/<IP_NAME>.md`

```markdown
# <IP_NAME> Spec

> Phase: <PHASE>
> Status: Draft

## Interface
...

## Timing
...

## Resource Budget
- LUT: <X>
- FF: <X>
- BRAM: <X>
- DSP: <X>

## Test Vectors
See tests/<IP_NAME>.yaml
```

### `tests/<IP_NAME>.yaml`

```yaml
test_cases:
  - name: tc_01_basic
    inputs: { data_i: 0xAA, valid_i: 1 }
    expected: { data_o: 0xAA, valid_o: 1 }
  - name: tc_02_reset
    inputs: { data_i: 0x00, valid_i: 0 }
    expected: { data_o: 0x00, valid_o: 0 }
```

### `golden/<IP_NAME>.py`

```python
"""Python golden reference for <IP_NAME>."""
from dataclasses import dataclass


@dataclass
class <IP_NAME>Ref:
    data_o: int = 0
    valid_o: bool = False

    def reset(self):
        self.data_o = 0
        self.valid_o = False

    def step(self, data_i: int, valid_i: bool):
        if valid_i:
            self.data_o = data_i
            self.valid_o = True
        else:
            self.valid_o = False


def self_test():
    ref = <IP_NAME>Ref()
    ref.reset()
    ref.step(0xAA, True)
    assert ref.data_o == 0xAA
    assert ref.valid_o == True
    print("PASS")


if __name__ == "__main__":
    self_test()
```

### `src/testbenches/<IP_NAME>_board_test.tcl`

```tcl
# <IP_NAME> Board Test
puts "============================================================"
puts "  <IP_NAME> Board Test"
puts "============================================================"

set xck26 [lindex [get_hw_devices xck26*] 0]
set vio [lindex [get_hw_vios -of_objects $xck26] 0]
# ... (参考 examples/rtl/counter/src/testbenches/counter_board_test.tcl)
```

### `src/build/create_<IP_NAME>_project.tcl`

```tcl
# Vivado build script template
set part "xck26-sfvc784-2LV-c"
set project_name "<IP_NAME>_test"
set project_dir "./${project_name}"

create_project $project_name $project_dir -part $part -force
add_files [file dirname [info script]]/<IP_NAME>.v
# ... (参考 examples/rtl/counter/create_vio_ila_project.tcl)
```

### `README.md`

```markdown
# <IP_NAME>

> Phase: <PHASE>
> Status: Draft / In Progress / Completed

## Quick Start

\`\`\`bash
python tools/qa/board_regression/run.py project/phase<N>_<IP_NAME>/
\`\`\`

## Spec
See specs/<IP_NAME>.md

## Status
[ ] L1 lint
[ ] L2 sim (12/12 PASS)
[ ] L3.1 auto-review
[ ] L3.2 multi-scheme
[ ] L3.3 sign-off
[ ] Board loopback (data = expected)
```

---

**Maintainer**: VibeSilicon Phase Owner
**Version**: v1.0
**Date**: 2026-06-27
