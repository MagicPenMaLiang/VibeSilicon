# <MODULE_NAME> microarchitecture

Status: DRAFT. Replace placeholders with accepted project inputs. Mark an item
NOT_APPLICABLE only with a reason. This template is not architecture approval.

## 1. Scope and immutable inputs

| Field | Accepted value or evidence |
|---|---|
| Owner and independent reviewer | <names and roles> |
| Target flow | <fpga / asic / both> |
| Requirements and spec revision | <path, hash and requirement IDs> |
| Golden model and vectors | <read-only paths and hashes> |
| Source manifest and top | <paths, versions and top module/function> |
| FPGA device / external ASIC views | <reviewed target identifiers and manifests> |
| Third-party ownership and licenses | <inventory and approved scope> |
| Open inputs and approvals | <blocking items and owners> |

Explain the functional boundary, supported modes and explicit non-goals. Separate
target-specific acceptance decisions when the behavioral contract serves both flows.

## 2. Interfaces, clocks and resets

| Interface/signal | Direction | Width/packing | Protocol/clock | Accepted behavior |
|---|---|---|---|---|
| <name> | <in/out> | <width, order> | <domain> | <valid, stalls, errors> |

Record throughput, latency, backpressure, frame boundaries, alignment and reset
behavior. Declare each clock's source, frequency, relationship and constraints.
Declare reset polarity, assertion/release strategy and power-up dependencies.

| Crossing | Source/destination | Data/event semantics | CDC architecture | Evidence/approval |
|---|---|---|---|---|
| <crossing> | <domains> | <contract> | <synchronizer/handshake/FIFO> | <IDs> |

List timing exceptions with exact endpoints, object counts and justification.
Keep missing CDC/reset approvals explicit; do not infer them from a lint result.

## 3. Numeric contract and dataflow

| Boundary/operation | Signedness | Width/fraction bits | Range | Rounding/overflow |
|---|---|---|---|---|
| <name> | <signed/unsigned> | <W/F> | <limits> | <exact rule and cast point> |

Describe operation ordering, accumulator precision, scaling, saturation/wrap and
illegal input handling. Bind bit-exact expectations to the frozen golden model.
Include a dataflow/block diagram and module hierarchy with ownership boundaries.

| Stage | Work per token | Latency/II | Valid/stall behavior | Numeric boundary |
|---|---|---|---|---|
| <stage> | <operations> | <cycles> | <contract> | <table entry> |

Explain pipeline alignment, buffering and error propagation. For each proposed
transformation, identify the invariant and evidence needed to preserve behavior.

## 4. Memory and configuration

| Storage | Capacity/width | Ports/clock | Read latency | Collision/init/reset | Target wrapper |
|---|---|---|---|---|---|
| <name> | <bits> | <access demand> | <cycles> | <explicit semantics> | <FPGA/ASIC choice> |

Calculate peak/sustained bandwidth, buffering depth and lifetime. Separate
algorithm logic from technology-specific memory implementations. Declare FPGA
inference eligibility and the reviewed ASIC wrapper/view contract separately.

| CSR offset/field | Width/access | Reset | Side effects/update timing | Domain/atomicity |
|---|---|---|---|---|
| <field> | <W, RW/RO/etc.> | <value> | <read/write/event priority> | <contract> |

Record byte strobes, reserved/invalid accesses, interrupts, coherent status
snapshots and frame-boundary configuration commits. Distinguish a bus shell from
the neutral core configuration interface.

## 5. Implementation choice and budgets

Explain the RTL/HLS partition and why it meets the target contract. For HLS,
read `skills/fpga-ip-design/references/pragma_cheatsheet.md`; record directive
intent, target loop/function, recurrence and memory-port limits. Requested II,
latency and resource counts are estimates until bound to measured reports.

| Target/metric | Acceptance target | Baseline | Non-regression limit | Evidence method |
|---|---|---|---|---|
| <frequency/area/resources/power/bandwidth> | <value/unit> | <value/config> | <limit> | <report> |

Include workload and activity assumptions, feasibility calculations and
configuration hashes. Compare like-for-like tool/device/constraint settings.

## 6. Verification, evidence and approvals

| Requirement/invariant | Method | Stimulus/property | Expected outcome | Evidence/gate |
|---|---|---|---|---|
| <ID> | <sim/formal/CDC/etc.> | <case> | <contract> | <artifact/owner> |

Cover nominal, numeric-boundary, reset, backpressure, error and stress behavior.
Declare applicable simulation/protocol/formal coverage and exclusions. Plan G0,
G1 and G2 before synthesis/implementation; add target-specific timing, PPA and
hardware checks as required. Keep missing/skipped checks distinct from PASS.

| Decision | Responsible reviewer | Source/evidence binding | Status/date |
|---|---|---|---|
| Architecture | <independent human> | <hashes/IDs> | <pending/approved> |
| High-risk exceptions and sign-off | <authorized human> | <schema-bound records> | <status> |

Record open items, waiver owners, expiry and compensating checks. Implementation
handoff requires independent human approval of interfaces, numeric behavior,
clock/reset/CDC, memory semantics, target split and acceptance criteria. Agents
must not fill approval fields on behalf of a human reviewer.
