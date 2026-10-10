# FPGA skills and bounded adapters

The three-stage rollout adds engineering playbooks, software evidence adapters,
and reviewed hardware-operation entry points. The original four roles and
FPGA/ASIC acceptance boundaries remain authoritative. A successful adapter
test does not qualify a board or approve production use.

## Stage 1: engineering decisions and discoverable resources

Canonical skills now cover 19 focused tasks. The additions are constraints,
simulation bring-up, lint triage, line coverage, resource optimization, power
optimization, flow orchestration, ILA debug, programming and SoC bring-up.
Existing CDC, timing and PPA instructions retain their evidence and approval
boundaries; the eight unfinished reference documents are replaced with
usable engineering contracts.

The supporting examples are repaired as well: multiply-add retains full
precision, lookup storage is caller-initialized, the CSR bank has declared
read/write and interrupt semantics, and an empty I2C module is replaced by a
contract checklist. These examples are not accepted project RTL; adapting
their interfaces or numeric types still requires the project's reviewed
contract. Vendor HLS synthesis and protocol qualification are not implied.

All local resources, including reference RTL/HLS templates, are replicated in
the Codex and Claude skill directories. Shared repository scripts and templates
are resolved from the project root. After editing canonical skills, run:

```bash
python scripts/sync_skills.py --write
python scripts/sync_skills.py --check
```

The checker rejects missing references, escaping resources, symlinks and stale
native copies. Unexpected native files are reported and preserved. CI checks
the manifest and byte-for-byte resource parity. The canonical role skill lists
and Claude skill routing are updated; Codex reads its canonical role contracts.

## Stage 2: report collection and line coverage

The Vivado MCP `collect_reports` tool accepts only `checkpoint_path`. It opens
a root-confined DCP read-only and collects timing (setup/hold and unconstrained
paths), CDC, flat/hierarchical resources, power, clocks/clock interaction,
exceptions, methodology, route status, DRC and check_timing reports in a new
owned directory. It never sources caller Tcl or changes the design.

`scripts/fpga_reports.py` binds the DCP, generated Tcl, raw execution receipt,
logs and report bytes. Existing versioned parsers extract timing, CDC,
utilization and DRC metrics. Other reports remain explicit raw evidence for
review; the adapter does not fabricate power or hierarchy metrics.

```bash
python -m scripts.fpga_reports .vibesilicon/reports/RUN_ID/bundle.json
```

Here PASS means that the requested reports were collected and verified, even
if a report contains a timing or DRC failure. This bundle is additional evidence;
it does not replace the RTL G0/G1/G2 gates or certify implementation closure.
Power is an estimate under checkpoint activity assumptions, not board power.

The coverage contract declares a source scope and threshold. Run the neutral
example with Verilator 5 and a working native C++ toolchain:

```bash
python -m scripts.quality_gate.rtl_coverage examples/rtl/counter/rtl_project_manifest.json examples/rtl/counter/rtl_coverage_contract.json
```

The adapter compiles the declared self-checking testbench with line
instrumentation, preserves compile/run/conversion logs, converts coverage data
to LCOV and binds source, contract and artifact hashes. It requires both a zero
exit code and exactly one pass token. Empty or truncated coverage data cannot
pass; failure or missing tools cannot be repaired by a pass token alone.
An owned fixed C++ harness explicitly writes coverage for older Verilator 5
versions as well; the initial adapter does not depend on newer generated-main
coverage behavior. Compile/run commands and the harness are retained.

The initial backend counts **Verilator instrumented lines**, which may combine
multiple points on a source line. It does not measure every lexical line,
functional, branch, toggle, FSM or assertion coverage. Unsupported metrics and
user exclusions are rejected. The counter's three instrumented lines are a
small execution example, not evidence for a customer design. Parameterized
RTL continues to require a reviewed simulation adapter.

## Stage 3: hardware requests and SoC preflight

`schemas/fpga_board_request.schema.json` defines exact-target requests for:

| Operation | Artifacts and options | Result scope |
|---|---|---|
| program | .bit and reviewed build binding | Volatile programming tool completion |
| capture | .bit, matching .ltx, build binding, named core and bounded depth | Program matched image, then one immediate ILA CSV capture |
| flash | .bit, reviewed .mcs, build binding, exact configuration-memory part | Flash programming and tool verification of file address range |

Each artifact is a repository-relative path plus its `sha256:` digest. The
reviewed build binding is a JSON object with `schema_version: 1`, `device_part`
and `bitstream_sha256`, plus `probes_sha256` or `image_sha256` for the respective
operation. This binding is a reviewed declaration; the adapter does not reverse
engineer bitstream provenance. `device.part` is the exact silicon PART reported
by Hardware Manager, not an assumed full package/speed-grade part string.

The device contract requires the complete hardware target path, device name and
silicon part. Only the local server `localhost:3121` is supported. The Tcl selects
one exact object, rejects ambiguity or part mismatch before programming, and
uses fixed commands. There is no arbitrary trigger Tcl, flash geometry guessing,
remote shell or automatic first-device selection.

Start from `templates/fpga_board_request.json.tpl` and
`templates/fpga_soc_plan.json.tpl`. Their sample identities, paths and zero hashes
must be replaced with reviewed project inputs; unfilled templates cannot execute.

Preview a valid request without opening Hardware Manager:

```bash
python -m scripts.fpga_board preview board_request.json
```

Preview returns PREVIEW and `hardware_validated: false`. It creates no hardware
session or run output. The returned request ID binds the complete operation.
Live execution additionally requires a human approval JSON outside the
agent-writable checkout, with the following fields:

| Field | Meaning |
|---|---|
| schema_version | 1 |
| request_id | Exact digest returned by preview |
| operator | Accountable human operator |
| reviewer | Distinct independent human reviewer |
| expires_at | Future RFC 3339 time with explicit timezone |

The operator pins that approval file's digest in
`VIBESILICON_BOARD_APPROVAL_SHA256` through the trusted launch environment.
Only then may the operator invoke `execute` with `--approval-file`. An approval
for program does not authorize flash or a different image/device. Environment
pinning and named attestations depend on operator environment integrity; they
are not cryptographic authentication of a person's identity. Hardware execution
is deliberately kept out of the default MCP tools.

An exclusive lock in the account's temporary directory serializes these adapter
transactions across checkouts. It cannot coordinate unrelated hardware clients
or other accounts; a lab scheduler must provide that broader ownership. Stale
locks require operator review and are never forcibly removed. Native commands
have bounded timeouts and content-addressed receipts. Successful execution
means hardware tool completion, not a working application or cold boot.

`schemas/fpga_soc_plan.schema.json` and `validate-soc` separate PS7 and MPSoC:

```bash
python -m scripts.fpga_board validate-soc soc_plan.json
```

The plan binds the reviewed preset, initialization input and interface contract
by path/hash and checks family/part compatibility. It leaves identity, boot log,
DDR memory, peripheral and clock/reset board checkpoints BLOCKED. The initial
adapter provides input preflight, not PS configuration, FSBL/device-tree
generation or automated board bring-up. Board-specific presets, software flows
and observed hardware results must be supplied and reviewed before extending
that adapter. DRC is not proof of correct DDR electrical parameters.

## Provenance and validation scope

The engineering review used [oh-my-fpga at df95c73](https://github.com/LNC0831/oh-my-fpga/tree/df95c73aa3cb268a2a53d2271f24153c38581f94).
These additions are independently authored. No SynthPilot tool catalog,
workflow runtime or upstream scripts are imported. The useful practices are
measurement-led triage, bounded experiments, explicit stop conditions and
retest evidence. Unsafe constraint combinations, blanket utilization thresholds
and global simulator termination are not adopted.

Command semantics are checked against primary documentation:
[Verilator coverage](https://verilator.org/guide/latest/simulating.html),
[check_timing](https://docs.amd.com/r/2023.1-English/ug835-vivado-tcl-commands/check_timing),
[exact hardware devices](https://docs.amd.com/r/2023.2-English/ug835-vivado-tcl-commands/get_hw_devices),
[ILA timeout in minutes](https://docs.amd.com/r/2024.1-English/ug835-vivado-tcl-commands/wait_on_hw_ila),
[ILA data export](https://docs.amd.com/r/2021.1-English/ug835-vivado-tcl-commands/write_hw_ila_data),
and [configuration-memory programming](https://docs.amd.com/r/2022.1-English/ug835-vivado-tcl-commands/program_hw_cfgmem).

Portable tests exercise manifests, schemas, hash tampering, missing evidence,
approval binding, expiration, locking and generated Tcl against simulated
hardware objects. Vendor command availability and a neutral Verilator run add
local integration evidence. These checks do not establish live FPGA programming,
ILA operation, flash compatibility, PS initialization or DDR validation.
Local neutral-example validation also covers CSR configuration/IRQ/reset behavior
with Verilator and HLS multiply-add boundary values, identity/lookup transfers
and illegal-state recovery against the installed Vitis 2024.2 C++ headers.
This is C simulation and directed RTL simulation, not HLS synthesis.
