# RTL FSM Design — State Machine Patterns for Hand-Coded Verilog

> **Purpose**: 教 architect-fpga 在 micro-arch doc 中设计 RTL FSM（用于路线一 pure RTL 和混合路线的 RTL 部分）。
> **Reference**: skills/fpga-rtl-system/SKILL.md §"Verilog/SV 编码规范"
> **Audience**: architect-fpga + coder-fpga（路线一/混合路线 RTL 部分）

## 1. Moore vs Mealy

### 1.1 Moore FSM — 输出只依赖当前状态

```verilog
// 输出寄存器（next_state 时赋值）
always @(posedge clk_i) begin
    if (!rst_n_i)
        state <= S_IDLE;
    else
        state <= next_state;

    // Moore output: 依赖 state
    case (state)
        S_IDLE:    ready_o = 1'b1;
        S_ACTIVE:  ready_o = 1'b0;
        S_DONE:    ready_o = 1'b1;
    endcase
end
```

**优势**：
- 输出**严格 1 cycle 延迟**
- 无 glitch（异步信号不会影响输出）

**劣势**：
- 状态多（每个输出组合都要独立状态）

### 1.2 Mealy FSM — 输出依赖当前状态 + 输入

```verilog
// 组合输出（依赖 state + input）
always @(*) begin
    case (state)
        S_IDLE: ready_o = cs_n_i;  // 输入影响
        S_ACTIVE: ready_o = 1'b0;
    endcase
end
```

**优势**：
- 状态少（输入参与决策）

**劣势**：
- 输出有 glitch（输入异步变化会立即反映）
- 延迟 0 或 1 cycle（不固定）

### 1.3 推荐：Moore 用于控制路径，Mealy 用于数据路径

| 路径 | 推荐 | 理由 |
|---|---|---|
| 控制 FSM（cmd/addr 解析）| **Moore** | 无 glitch，延迟固定 |
| 数据通路（data_valid + state）| **Mealy** | 输入即输出，低延迟 |

### 1.4 Phase 1 SPI Slave 案例

```verilog
// Moore FSM for state machine
always @(posedge clk_i) begin
    if (!rst_n_i) begin
        fsm_state <= S_IDLE;
        cmd_buf   <= 8'h00;
        // ...
    end else begin
        fsm_state <= fsm_next;  // Moore
    end
end

// Mealy for ready/data output (depends on cs_n_i)
always @(*) begin
    data_o_int = (fsm_state == S_DATA_XFER) ? rx_data_buf : 8'h00;
    ready_o   = (fsm_state == S_IDLE);  // No CS = ready
end
```

## 2. 状态编码

### 2.1 Binary 编码

```verilog
localparam S_IDLE    = 2'd0;
localparam S_ACTIVE  = 2'd1;
localparam S_DONE    = 2'd2;
localparam S_ERROR   = 2'd3;
```

**优势**：
- 最少 FF（log₂N 个）
- 综合简单

**劣势**：
- 状态转移时多位变化 → glitch 风险
- 不易于单 bit debug

### 2.2 One-Hot 编码

```verilog
localparam S_IDLE    = 4'b0001;
localparam S_ACTIVE  = 4'b0010;
localparam S_DONE    = 4'b0100;
localparam S_ERROR   = 4'b1000;
```

**优势**：
- 单 bit 变化 → 无 glitch
- 易于 debug（ILA 看一个 bit 就够）
- 综合器识别后 FF 复用多（面积不一定大）
- **FPGA 推荐**（FF 充足）

**劣势**：
- 状态多时 FF 占用大（但 FPGA 上不严重）

### 2.3 Gray 编码

```verilog
localparam S_IDLE    = 2'b00;
localparam S_ACTIVE  = 2'b01;
localparam S_DONE    = 2'b11;
localparam S_ERROR   = 2'b10;
```

**优势**：
- 状态转移时**只有 1 bit 变化**
- 跨时钟域时安全

**劣势**：
- 难以手动理解

### 2.4 推荐

| 场景 | 编码 |
|---|---|
| ≤ 4 状态 | Binary |
| 4-16 状态 | One-Hot（FPGA） |
| > 16 状态 | Binary（节省 FF） |
| 跨时钟域状态传递 | Gray |

## 3. 进程风格

### 3.1 单进程（推荐）

```verilog
always @(posedge clk_i) begin
    if (!rst_n_i) begin
        state <= S_IDLE;
        data_o <= '0;
        valid_o <= 1'b0;
    end else begin
        state <= next_state;
        data_o <= data_next;
        valid_o <= valid_next;
    end
end

always @(*) begin
    next_state = state;
    data_next = data_o;
    valid_next = valid_o;
    case (state)
        S_IDLE: begin
            if (start_i) next_state = S_ACTIVE;
        end
        S_ACTIVE: begin
            data_next = compute(input_i);
            valid_next = 1'b1;
            if (done_compute) next_state = S_DONE;
        end
        // ...
    endcase
end
```

**优势**：
- 易于阅读
- 综合器易优化

### 3.2 双进程（state + output 分离）

```verilog
// Process 1: state register
always @(posedge clk_i) begin
    if (!rst_n_i) state <= S_IDLE;
    else state <= next_state;
end

// Process 2: next_state logic
always @(*) begin
    next_state = state;
    case (state)
        // ...
    endcase
end

// Process 3: output logic
always @(*) begin
    case (state)
        S_IDLE: ready_o = 1'b1;
        // ...
    endcase
end
```

**优势**：
- Moore 输出独立 process（清晰）
- 时序约束独立

**劣势**：
- 多 process 易出错（race condition）

### 3.3 三进程（state + next_state + output 分离）

```verilog
// 三个 always 块
always @(posedge clk_i) state <= (rst_n_i) ? next_state : S_IDLE;
always @(*) next_state = ...;
always @(*) case (state) ... endcase
```

**优势**：
- Moore 输出严格 1 cycle 延迟

**劣势**：
- 容易出现 latch（default case 必须完整）

## 4. 复位策略

### 4.1 异步复位

```verilog
always @(posedge clk_i or negedge rst_n_i) begin
    if (!rst_n_i) begin
        state <= S_IDLE;
        // ...
    end else begin
        // ...
    end
end
```

**优势**：
- 复位**不**依赖时钟
- 上电后立即生效

**劣势**：
- 跨时钟域时**需要同步器**（3-FF chain）
- 时序约束：异步复位路径需 set_false_path

### 4.2 同步复位

```verilog
always @(posedge clk_i) begin
    if (!rst_n_i) begin  // 同步
        state <= S_IDLE;
    end else begin
        // ...
    end
end
```

**优势**：
- 无异步路径 → 时序收敛
- 跨时钟域安全

**劣势**：
- 上电到第一个 clock 之间不可控（需要 POR）

### 4.3 推荐

| 场景 | 复位类型 |
|---|---|
| 单时钟域 + 上电复位 | **异步复位**（配合同步器）|
| 多时钟域 + PHY 接口 | **同步复位**（避免异步路径）|
| Xilinx 7-series / UltraScale | 两种都支持，**优先同步复位**（vivado 推荐）|

### 4.4 多状态复位区分

```verilog
always @(posedge clk_i or negedge rst_n_i) begin
    if (!rst_n_i) begin
        state    <= S_IDLE;
        data_reg <= '0;
    end else if (soft_rst_i) begin
        state    <= S_IDLE;
        // data_reg 保持（部分复位）
    end else begin
        // 正常运行
    end
end
```

## 5. micro-arch doc 中的 FSM 章节

在 `micro_arch/<module>_arch.md` §2 Dataflow & Pipeline 改为：

```markdown
## 2. FSM 设计（路线一变体）

### 2.1 状态转移表

| 当前状态 | 输入条件 | 下一状态 | 输出（Moore）|
|---|---|---|---|
| S_IDLE | start_i | S_ACTIVE | ready_o=1 |
| S_IDLE | !start_i | S_IDLE | ready_o=1 |
| S_ACTIVE | done_compute | S_DONE | valid_o=1 |
| S_ACTIVE | !done_compute | S_ACTIVE | valid_o=0 |
| S_DONE | ack_i | S_IDLE | valid_o=0 |

### 2.2 状态编码

One-Hot（FPGA 推荐）：
- S_IDLE = 4'b0001
- S_ACTIVE = 4'b0010
- S_DONE = 4'b0100
- S_ERROR = 4'b1000

### 2.3 复位策略

异步低有效复位 rst_n_i，3-FF 同步器链

### 2.4 时序分析

| 路径 | 估算延迟 |
|---|---|
| state → output (Moore) | 1 cycle |
| input → next_state | < 5 ns @ 100 MHz |
| state → next_state | < 5 ns |
```

## 6. Phase 1 SPI Slave FSM 案例（实际代码）

```verilog
// 4-state FSM (one-hot)
localparam S_IDLE      = 2'b00;
localparam S_CMD_RX    = 2'b01;
localparam S_ADDR_RX   = 2'b10;
localparam S_DATA_XFER = 2'b11;

reg [1:0] fsm_state, fsm_next;

always @(posedge clk_i or negedge rst_n_i) begin
    if (!rst_n_i) fsm_state <= S_IDLE;
    else fsm_state <= fsm_next;
end

always @(*) begin
    fsm_next = fsm_state;
    case (fsm_state)
        S_IDLE: if (cs_n_sync == 1'b0) fsm_next = S_CMD_RX;
        S_CMD_RX: if (bit_count == 3'd8) fsm_next = S_ADDR_RX;
        // ...
    endcase
end
```

**L005 教训**：
- case 用 `cmd_buf[6:0] + mosi_s`（最新 8 bit），不是 OLD `cmd_buf`
- 边界处理：bit_count==8 触发，但 S_IDLE 消耗 1 SCK → 实际 shift 7 bit

## 7. FSM 性能 vs HLS 对比

| 指标 | HLS (UNROLL/PIPELINE) | 手写 FSM |
|---|---|---|
| 开发时间 | 分钟 | 小时 |
| II | 1（自动）| 手动优化 |
| 资源 | 综合器决定 | 手动控制 |
| 可读性 | 一般 | 高（明确状态机） |
| 适用 | 算法密集（图像/信号）| 控制密集（FSM、PHY）|

## 8. 错误模式

❌ **未声明 default case** → 综合出 latch
❌ **组合逻辑使用 `<=`** → 语法错误
❌ **状态转移 case 缺状态** → 死锁（永远在初始状态）
❌ **异步复位无同步器** → 亚稳态
❌ **状态寄存器变量名冲突** → 综合错误

---

**Maintainer**: VibeSilicon Phase Owner
**Date**: 2026-06-28