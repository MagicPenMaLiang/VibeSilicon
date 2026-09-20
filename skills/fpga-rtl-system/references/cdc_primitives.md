# TODO 占位（Phase 2 W5 填，stream-processing CDC 桥接实例驱动）

## 用途

CDC 原语使用指南（XPM_CDC / XPM_FIFO_ASYNC）。

## 待填内容

### XPM_CDC 系列

| 原语 | 用途 | 关键参数 |
|---|---|---|
| `xpm_cdc_single` | 单 bit 同步 | `DEST_SYNC_FF` (2-10) |
| `xpm_cdc_handshake` | 握手同步 | `DEST_SYNC_FF`, `DEST_EXT_HSK` |
| `xpm_cdc_gray` | 格雷码同步 | `WIDTH` (2-32) |
| `xpm_cdc_sync_rst` | 异步复位同步 | `DEST_SYNC_FF` (2-10) |
| `xpm_cdc_pulse` | 脉冲同步 | `REG_OUTPUT`, `RST_USED` |

### XPM_FIFO 系列

| 原语 | 用途 | 关键参数 |
|---|---|---|
| `xpm_fifo_sync` | 同步 FIFO | `FIFO_MEMORY_TYPE`, `FIFO_DEPTH` |
| `xpm_fifo_async` | 异步 FIFO | `RELATED_CLOCKS=0` |
| `xpm_fifo_axis` | AXI-Stream FIFO | `TDATA_WIDTH`, `FIFO_DEPTH` |
| `xpm_fifo_AXI4` | AXI4 FIFO | `AXI_DATA_WIDTH` |

### 选择决策

- 单 bit 控制信号 → `xpm_cdc_single`
- 多 bit 数据 + 吞吐高 → `xpm_fifo_async`
- 异步复位 → `xpm_cdc_sync_rst`
- AXI-Stream → `xpm_fifo_axis`

## 上游引用

- `SKILL.md` → "Vivado 原语使用" + "CDC 桥接模式"
- 计划 §6.1.5 4 类内容
- `fpga-cdc-check/references/xpm_primitives.md`（更详细的实例化代码）
