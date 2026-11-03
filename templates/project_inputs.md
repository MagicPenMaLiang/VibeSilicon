# Project input worksheet

Status: DRAFT

Copy this worksheet into the project and fill every applicable field. `<TBD>` is
an unresolved input. Distinguish reference, candidate and approved values. Missing
tools, skipped checks and absent evidence cannot be recorded as PASS.

## 0. Sources and version boundaries

| ID | Source and version | Content ID/hash | Purpose | Limitations |
|---|---|---|---|---|
| S1 | `<TBD>` | `<TBD>` | `<TBD>` | `<TBD>` |

## 1. Identity and scope

| Field | Input | Status/notes |
|---|---|---|
| Project ID | `<TBD>` | No customer-identifying information |
| Project version | `<TBD>` | |
| Date | `<TBD>` | |
| Project owner | `<TBD>` | |
| Independent reviewer | `<TBD>` | Implementer self-review is insufficient |
| Target flow | `fpga` / `asic` / `both` | Select one |
| Implementation route | `<TBD>` | Handwritten RTL, selected HLS or an explicit combination |
| Objectives | `<TBD>` | |
| Deliverables | `<TBD>` | |
| Excluded scope | `<TBD>` | |
| Requirement tracking IDs | `<TBD>` | |

## 2. Functional and IO contract

| Field | Input | Status/notes |
|---|---|---|
| Functional specification | `<TBD>` | |
| Supported and default modes | `<TBD>` | |
| Input format | `<TBD>` | |
| Output format | `<TBD>` | |
| Configuration/runtime parameters | `<TBD>` | |
| Error detection/reporting | `<TBD>` | |
| Error recovery | `<TBD>` | |
| Acceptance scenarios | `<TBD>` | |

## 3. Numeric and acceptance contract

| Field | Input | Status/notes |
|---|---|---|
| Numeric representation | `<TBD>` | Width, signedness and scaling |
| Rounding, truncation and saturation | `<TBD>` | |
| Overflow and boundary behavior | `<TBD>` | |
| Parameter/LUT update timing | `<TBD>` | |
| Numeric correctness criterion | `<TBD>` | Bit-exact or reviewed tolerance |
| Other acceptance metrics | `<TBD>` | Do not replace correctness criteria |
| Change/reapproval rules | `<TBD>` | |

## 4. Interfaces, clocks, resets and flow control

| Field | Input | Status/notes |
|---|---|---|
| Top module | `<TBD>` | |
| RTL/verification language standard | `<TBD>` | |
| Ports and protocols | `<TBD>` | |
| Packing and bit order | `<TBD>` | |
| Clock domains/frequencies | `<TBD>` | |
| Reset types/sequence | `<TBD>` | |
| CDC scope and exceptions | `<TBD>` | Exceptions need independent review |
| Throughput and latency | `<TBD>` | Identify measurement boundaries |
| Input/output backpressure | `<TBD>` | |
| Buffer capacity/overflow policy | `<TBD>` | |

## 5. Target implementation constraints

### FPGA

| Field | Input | Status/notes |
|---|---|---|
| Full part/package/speed/temperature grade | `<TBD>` | |
| Board and external devices | `<TBD>` | Required for hardware replay |
| Synthesis/implementation tool versions | `<TBD>` | |
| Clock, IO and timing exceptions | `<TBD>` | |
| Memory policy/primitive allowlist | `<TBD>` | |
| Portable RTL/vendor wrapper boundary | `<TBD>` | |
| Build strategy/required reports | `<TBD>` | |
| Hardware tests/programming procedure | `<TBD>` | Separate operation-specific approval |

### ASIC

| Field | Input | Status/notes |
|---|---|---|
| External PDK root/view manifest | `<TBD>` | Do not commit PDK data |
| PVT and RC corners | `<TBD>` | |
| Standard-cell, macro and memory compiler policy | `<TBD>` | |
| Synthesis/STA/physical configuration | `<TBD>` | |
| DRC/LVS and signoff handoff | `<TBD>` | |
| Power activity source | `<TBD>` | |

Dual-target projects keep constraints, tools, memory wrappers, implementation
evidence and acceptance decisions separate.

## 6. PPA and non-regression targets

| Metric | Reference, if any | Acceptance/non-regression limit | Conditions and evidence |
|---|---:|---:|---|
| Frequency/throughput | `<TBD>` | `<TBD>` | `<TBD>` |
| Timing | `<TBD>` | `<TBD>` | `<TBD>` |
| Area/resources | `<TBD>` | `<TBD>` | `<TBD>` |
| Power | `<TBD>` | `<TBD>` | `<TBD>` |
| External memory bandwidth | `<TBD>` | `<TBD>` | `<TBD>` |

## 7. Golden model, vectors and verification acceptance

| Field | Input | Status/notes |
|---|---|---|
| Read-only golden model/version | `<TBD>` | |
| Golden manifest/content hashes | `<TBD>` | |
| Representative/end-to-end vectors | `<TBD>` | |
| Boundary/reset/protocol/error vectors | `<TBD>` | |
| Parameter/random coverage | `<TBD>` | Fixed seeds and reproduction information |
| Simulation/formal tools and versions | `<TBD>` | |
| Functional/code coverage targets | `<TBD>` | Coverage does not replace correctness |
| PASS criteria/evidence retention | `<TBD>` | |

## 8. Source manifest and generated code

| Field | Input | Status/notes |
|---|---|---|
| RTL/HLS directories and files | `<TBD>` | |
| Verification directories and files | `<TBD>` | |
| Tops, parameters and macros | `<TBD>` | |
| Generated code/LUT origin and reproduction | `<TBD>` | Generator version and input hashes |
| Third-party IP/vendor output | `<TBD>` | |
| Prohibited public content | Licenses, credentials, customer assets, personal paths, restricted IP and raw runs | Review repository rules |

## 9. Ownership, review and approval boundaries

| Field | Input/approver | Status/notes |
|---|---|---|
| Golden/third-party licensing | `<TBD>` | |
| New-code owner | `<TBD>` | |
| Confidentiality/release restrictions | `<TBD>` | |
| Architecture approval | `<TBD>` | Independent human review |
| Numeric contract approval | `<TBD>` | Independent human review |
| Reset/CDC exception approval | `<TBD>` | Independent human review |
| Verification acceptance approval | `<TBD>` | Independent human review |
| Hardware/release approval | `<TBD>` | |
| Open-item escalation owner | `<TBD>` | |

## 10. Remaining decisions

| ID | Open decision | Owner | Blocked scope | Status/closure evidence |
|---|---|---|---|---|
| D1 | `<TBD>` | `<TBD>` | `<TBD>` | OPEN |
