# FPGA upstream review and adoption

Initial review 2026-10-29; focused Ross FPGA review refreshed 2026-11-03.
VibeSilicon remains an FPGA **and ASIC** engineering toolkit.
This integration changes the FPGA branch: algorithm -> reviewed microarchitecture
-> handwritten RTL -> G0/G1/G2 -> synthesis/implementation -> hardware validation.
HLS is an explicitly selected alternative/sub-block. No HLS installation or HLS
baseline is required for the direct RTL path. ASIC/both manifests, PDK contracts,
memory wrappers and acceptance remain separate under AGENTS.md.

Current shared skill names, role names and compatibility mappings are maintained
in [project map](project_map.md). The native backend remains the execution default;
it is not a complete official MCP replacement. See the per-tool
[coverage assessment and selection policy](ross_backend_coverage.md).

## Sources and boundaries

- [AMD Ross](https://github.com/Xilinx/ross-ai-assistant/tree/dce0fb90611b144dd529490359b51cea5d0d5596),
  Git commit `dce0fb90611b144dd529490359b51cea5d0d5596` (main at both reviews).
  Reviewed the skill inventory and relevant RTL, HLS, IP, reproduction and hardware
  entrypoints. The public repository supplies skills; its proprietary Vivado MCP
  server is a separately installed component, not source imported here.
- Local Vivado AI Assistant Examples, README version **0.6.7**. The enclosing
  directory also contains binary extension/server packages; those were not
  unpacked, reverse engineered, copied or redistributed. Relevant skill bytes
  are identified below without a personal machine path.

The integration uses newly authored VibeSilicon contracts and bounded readers,
adapting engineering practices rather than importing upstream runtimes, tool names
or agent hierarchies. AMD attribution and upstream MIT terms are preserved in
THIRD_PARTY_NOTICES.md and third_party/amd-ross/LICENSE.

## Capability decisions

| Source capability | Existing FPGA coverage | Decision and implementation | Limit of the result |
|---|---|---|---|
| Algorithm restructuring, dependency/dataflow/memory reasoning (Ross hls-architect, pipeline, stencil/line-buffer helpers) | hw-microarch records numeric/dataflow/memory contracts | Adapt useful reasoning to direct RTL in **fpga-algorithm-to-rtl**; add `scripts/fpga_feasibility.py`, schema and template | Arithmetic planning rejection only; banking, numeric semantics and achieved PPA still require evidence |
| Local/Ross RTL lint and elaboration diagnosis | G0/G1 static/readability/waivers, Verilator, rtl-lint | Keep existing gates; add source/line-context and tool-failure triage in rtl-simulation | No new Vivado lint, Oasys parser or licensed simulator adapter is claimed |
| Local AXI simulation and Ross simulate-rtl | Self-checking smoke, protocol assertions, supported line coverage | Add targeted failure/waveform evidence and known-issue research guidance | XSim/UVM/third-party seeded regressions, functional/toggle/FSM coverage and SAIF capture are not implemented by this change |
| Local post-route/timing closure and Ross methodology checks | DCP report bundles, constraints/CDC/timing skills, bounded rollback experiments | Retain existing infrastructure; no duplicate timing framework | Sampled critical paths do not establish TNS/total failures; nonnegative setup slack alone is insufficient |
| Local opt-design-analysis | Reports and generic optimization exist, but stage-scoped attribution was missing | Add **analyze_opt_log** fixed Vivado MCP tool, CLI and DCP reference | Extracts existing logs only; incomplete scopes are BLOCKED; protection removal needs a reviewed change |
| Local specification-driven BD creation; Ross IP configurator and revision control | Generic source manifest and native Vivado backend | Add project reconstruction inventory and requirement/CONFIG/propagated/runtime readback ledger to fpga-flow | Playbook only; no arbitrary BD/Tcl executor, IP upgrade or automatic reconstruction adapter added |
| Local ILA/VIO insertion; Ross hw-ila/hw-vio | Exact-device program/capture/flash requests and immediate ILA captures | Add instrumentation planning, version matching and debug-overhead guidance | IP insertion, advanced triggers and VIO writes are not implemented; VIO needs a dedicated bounded control adapter |
| Ross vitis-embedded | PS7/MPSoC input preflight and explicit board checks | Add hardware-export -> platform -> app -> image -> observed boot handoff reference | No Vitis platform/app/Bootgen runner added; no claim of boot, DDR or Linux validation |
| Ross HLS report, II, dataflow and burst helpers | Four HLS build tools plus generic scheduling reference | Optional **analyze_csynth** fixed HLS MCP reader and detailed HLS diagnosis reference | Existing XML estimates/logs only; source freshness, co-simulation and routed results remain unverified |
| Ross MATLAB-to-C++ conversion | Immutable numeric/golden contract | Adopt only numeric/reference-first transformation discipline | MATLAB/OpenCV and frame-based C++ conversion are not prerequisites for direct RTL |
| Ross AIE/NPU vai-* agents, segcfg/DFX flows | Outside the current generic PL FPGA path | Defer; keep four existing roles | No NPU quantizer/compiler, custom-AIE worker, segmentation or DFX support is implied |
| Hosted/local AMD documentation search | Native backend advertises docs_search=false; documentation research was initially guidance only | Follow-up on 2026-10-30 adds the separate hosted amd-doc-search service, fpga-doc-search skill and four-role routing | See docs/fpga_documentation_service.md for verified connectivity and relevance/version limits; native EDA backend remains separate, local-KB index is not deployed |

Do not adopt arbitrary Tcl/Python/network tool exposure, first-file/device selection,
automatic part/clock substitution, automatic golden quantization, wholesale removal
of protection, or mandatory commits/interactive pauses for every iteration.
Use current project authority, exact inputs and proportionate existing gates.

## Focused FPGA skill adoption on 2026-11-03

The review used a fresh source checkout at the same pinned commit, including
the original skill bodies and MCP reference. The changes below strengthen skill
instructions; they do not add execution endpoints or qualify a vendor release.
Local ignored review receipts retain the reviewed source hashes.

| Original Ross skill | Useful practice absorbed | Maintained local destination |
|---|---|---|
| [vivado-simulate-rtl](https://github.com/Xilinx/ross-ai-assistant/blob/dce0fb90611b144dd529490359b51cea5d0d5596/skills/vivado-simulate-rtl/SKILL.md) | Explicit backend/mode/terminal result; separate DUT, testbench and tool failures; seed replay, SDF evidence, comparable waveforms, known-issue research and minimal reproducer | [rtl-simulation diagnosis](../skills/rtl-simulation/references/diagnostic_evidence.md) |
| [vivado-rtl-lint](https://github.com/Xilinx/ross-ai-assistant/blob/dce0fb90611b144dd529490359b51cea5d0d5596/skills/vivado-rtl-lint/SKILL.md) and [vivado-rtl-elaboration-analysis](https://github.com/Xilinx/ross-ai-assistant/blob/dce0fb90611b144dd529490359b51cea5d0d5596/skills/vivado-rtl-elaboration-analysis/SKILL.md) | Source-context diagnosis, complete accounting of warnings/cascades and file hotspots without losing original diagnostics | [rtl-lint](../skills/rtl-lint/SKILL.md), shared simulation diagnosis |
| [vivado-timing-methodology-checks](https://github.com/Xilinx/ross-ai-assistant/blob/dce0fb90611b144dd529490359b51cea5d0d5596/skills/vivado-timing-methodology-checks/SKILL.md) | Rule/object-level findings, original-XDC provenance, prerequisite order, release-specific remedies and before/after evidence | [checkpoint methodology reference](../skills/fpga-dcp-analysis/references/methodology.md), routed from fpga-dcp-analysis |
| [vivado-revision-control](https://github.com/Xilinx/ross-ai-assistant/blob/dce0fb90611b144dd529490359b51cea5d0d5596/skills/vivado-revision-control/SKILL.md) | Source ownership, per-file/run settings and clean-recreation comparison of BDs, managed wrappers and runs | [project reconstruction](../skills/fpga-flow/references/vivado_reproduction.md) |
| [vivado-ip-configurator](https://github.com/Xilinx/ross-ai-assistant/blob/dce0fb90611b144dd529490359b51cea5d0d5596/skills/vivado-ip-configurator/SKILL.md) | Atomic requirement ledger, documented parameter meaning, ignored-warning detection, post-propagation readback and explicit partial completion | Same reconstruction reference, IP intent ledger |
| [hw-ila-debug](https://github.com/Xilinx/ross-ai-assistant/blob/dce0fb90611b144dd529490359b51cea5d0d5596/skills/hw-ila-debug/SKILL.md) and [hw-vio-debug](https://github.com/Xilinx/ross-ai-assistant/blob/dce0fb90611b144dd529490359b51cea5d0d5596/skills/hw-vio-debug/SKILL.md) | Persist raw samples and exact metadata; distinguish capture timeout from DUT failure; synchronize control state and verify effects independently | [instrumentation reference](../skills/fpga-ila-debug/references/instrumentation.md); VIO remains planning only |
| Simulation coverage/activity references in vivado-simulate-rtl | Requirement-linked stimulus plus observation, comparable passing runs, seed identity and explicit activity windows | [rtl-coverage](../skills/rtl-coverage/SKILL.md), shared simulation diagnosis; backend metric limits retained |

The most useful plugin pattern is progressive disclosure: a short task entrypoint
loads detailed references only for the selected failure or mode. Reuse the four
VibeSilicon roles and existing skill routes. No extra Ross agent hierarchy, copied
helper runtime or duplicate skill installation is needed for these improvements.
Existing algorithm/storage/II/dataflow and optional HLS adaptations remain in the
capability table above; this refresh does not make HLS a prerequisite for RTL.

Do not inherit upstream behavior without checking its engineering effect:

- The reviewed methodology and hardware skills declare 2026.1+, the IP skill
  requires 2026.1, and simulation lists validation on 2025.2/2026.1. None establishes
  command, property or report-layout compatibility with a 2024.2 project.
- An upstream automatic fix or device-family fallback does not authorize changing
  the target, clock intent, reset/CDC exceptions or reviewed interface contract.
- Runtime-register instructions are a software handoff, not proof a feature works.
  A nearest-legal IP value or temporary stub connection cannot satisfy an unmet
  requirement. Verify the final integrated interface after propagation.
- Do not import broad Tcl execution, helper-launched Python, plugin-specific tool
  aliases, compulsory repair pauses or per-file subagent expansion. Use the current
  authorization, bounded adapters and independent review rules.
- Host-issued VIO writes do not establish cycle-precise pulses. Keep control writes
  unavailable until an exact-device adapter and drive/restore contract exist.

Near-term execution gaps worth addressing when needed are Vivado lint/elaboration,
bounded XSim simulation and IP/BD readback. Advanced ILA/VIO, embedded application
builds and persistent/GUI/remote sessions remain separately scoped work. Adopting
a playbook does not make any of these operations executable.

## Entry points

```bash
python -m scripts.fpga_feasibility PLAN.json --root PROJECT_ROOT
python -m scripts.vivado_opt_analysis RUN.log --root PROJECT_ROOT
# Optional HLS component only:
python -m scripts.hls_reports REPORT.xml --root PROJECT_ROOT --log COMPILE.log
```

Fill `templates/fpga_feasibility.json.tpl` with reviewed inputs; placeholders fail
validation. Rates include initiation interval and declared stalls, capacities
include storage copies, and external traffic includes aggregate read/write demand.
The caller owns assumptions, memory-port schedules and disjoint allocations.
Hash binding covers declared files, not their transitive dependencies.

Feasibility returns CANDIDATE/REJECTED for supplied estimates, or BLOCKED for invalid
inputs; CLI exit codes are 0/1/2 respectively. COLLECTED in report tools means
extraction, never PASS for the design. Report/log hashes identify bytes but do
not prove they were produced from the current source. Keep all these results
separate from architecture approval, RTL gates, timing closure and board evidence.

## Local example source fingerprints

Paths are relative to the locally supplied examples root. SHA-256 identifies the
reviewed instruction bytes; no example RTL, vendor IP or customer asset is copied.

| Skill path | SHA-256 |
|---|---|
| axi4-debug-simulation/.claude/skills/axi4-debug-simulation/SKILL.md | 0489c8bd2921aa32e0c2de02d6d4e4c58fdabf778bf1ca4796e42809e83a5a3b |
| ila-insertion-flow/.claude/skills/bd-ila-insertion/SKILL.md | c8e99668731ff9313f4f8dde1e7624e383fce289617c6788548dfb7247cd70aa |
| ila-insertion-flow/.claude/skills/bd-vio-insertion/SKILL.md | a175960f2d5f41af10465553cc05afe2ad4d13153556b808e4a40a78ae069bb2 |
| opt-design-analysis/.claude/skills/opt-design-analysis/SKILL.md | db49f3b0a1471c6c028de9dd8b0c9be6220296bf881215eb089e3ac7bcdada13 |
| rtl-lint/.claude/skills/rtl-lint/SKILL.md | 64cc673c7502799255dfadaea5156abf119b950fac9562fe9f24f00041533ab0 |
| timing-closure-prototype/.claude/skills/post-route-dcp-analysis/SKILL.md | b3476474a2271582bcaf59adf6b295564700f7eec61ffac573c01763bf0f319e |
| timing-closure-prototype/.claude/skills/timing-closure-prototype/SKILL.md | e0d38e40b9c2185d871cbdb6ba684a4a04aa0a193e31c8671c49b3f9b181cf95 |

## Validation scope

`tests/test_fpga_flow_adoption.py` covers independent rate/latency/resource/memory/
bandwidth rejection, missing/tampered inputs, path confinement, unsupported/nonfinite
report fields, phase isolation, incomplete logs, bounded excerpts, and MCP readers
that never launch EDA. Existing security, platform and skill-sync checks cover the
surrounding interfaces. These are software contract tests, not algorithm RTL
equivalence, vendor build qualification or hardware validation.
