# Ross MCP coverage and backend selection

Reviewed 2026-11-03 against the [official MCP reference](https://github.com/Xilinx/ross-ai-assistant/blob/dce0fb90611b144dd529490359b51cea5d0d5596/docs/reference/vivado-mcp-tools.md).
The upstream commit is `dce0fb90611b144dd529490359b51cea5d0d5596`.
This is a source and configuration review, not a live qualification of either
Vivado execution server.

VibeSilicon does **not fully cover the official Vivado MCP interface**. It covers
selected engineering tasks through bounded local adapters. Keep `native` as the
default and do not install or register the official execution MCP merely to use
the adapted skills. A missing capability should trigger a specific adapter
decision when a project needs it. Full official API parity is not a prerequisite
for the supported local FPGA workflow.

## Execution interface comparison

Here, partial means related local behavior exists, not compatible arguments,
session semantics or a drop-in replacement. Internal Python methods do not count
as client-visible MCP tools. Upstream availability also depends on platform and
server configuration.

| Official tool | Local coverage | Evidence and boundary |
|---|---|---|
| `vivado_start` | Partial | `NativeVivadoBackend.start_session` creates batch execution context; no persistent Tcl webserver, GUI or reconnectable project session |
| `vivado_stop` | Partial | Internal `stop_session` closes local bookkeeping; no official detach/keep-alive interface |
| `vivado_connect` | Absent | Native capabilities declare `remote_connection=false` |
| `vivado_list_sessions` | Absent at MCP boundary | No persistent session inventory tool is exposed to clients |
| `vivado_cleanup` | Absent at MCP boundary | No stale-session recovery or official orphan-cleanup interface |
| `vivado_execute` | Partial by task | Fixed synthesis, place/route, timing, CDC, checkpoint, report and bitstream tools; arbitrary Tcl is not an enabled client interface |
| `vivado_status` | Partial | Internal command status and adapter receipts; no live session/run polling, reset or relaunch MCP tool |
| `vivado_log_messages` | Partial | Internal audit-event reader, retained execution logs and `analyze_opt_log`; no generic live-session diagnostic-query MCP tool |
| `vivado_history` | Partial | Local audit/command evidence is retained; no cross-session history search interface |
| `vivado_display` | Absent | `gui=false`, `waveform=false`; no Linux virtual display/screenshot service |
| `vivado_lsf` | Absent | No LSF session adapter; upstream tool is conditional and Linux only |
| `vivado_ssh` | Absent | `remote_ssh=false`; upstream shared-filesystem remote sessions are not implemented |
| `vivado_todos` | Absent as IDE integration | Role handoffs and evidence gates do not implement the upstream sidebar protocol |
| `vivado_client_info` | Absent | Backend capabilities describe the EDA adapter, not the connected IDE's capabilities |

Implementation sources: [backend](../scripts/vivado_backend.py),
[selector](../scripts/vivado_backend_selector.py),
[Vivado MCP server](../mcp/vivado-mcp/server.py), and the client allowlists in
`.codex/config.toml`, `.mcp.json` and `opencode.json`. The optional `run_script`
tool needs explicit enablement and a matching SHA-256 allowlist; it does not
establish unrestricted Tcl or official API equivalence. Capabilities such as
`ipi=true` at the internal layer do not establish a supported IP/BD automation
workflow at the MCP boundary.

## Separate documentation and skill layers

`amd-doc-search` is already registered separately and has returned real queries;
see [documentation service evidence](fpga_documentation_service.md). It is not
part of the native execution backend or a reason to add the official Vivado MCP.
Exact document edition still needs checking.

The [Ross plugin](https://github.com/Xilinx/ross-ai-assistant/blob/dce0fb90611b144dd529490359b51cea5d0d5596/README.md)
supplies skills; the proprietary execution server is installed separately.
Original skills commonly call `vivado_execute` and related official endpoints.
Installing those instructions alone cannot supply those endpoints. VibeSilicon
adapts selected practices into its existing skills instead of loading a second
plugin with incompatible tool assumptions. Do not install both plugin and copied
upstream skills, which would duplicate discovery.

## When to extend the backend

For a project request, identify the operation, required release, exact inputs,
side effects and acceptance evidence before choosing a route:

1. Use an existing fixed local tool when its input contract covers the request.
2. For a repeated gap, consider a bounded native adapter with negative tests and
   source-bound receipts. Near-term candidates are explicit Vivado lint/elaboration,
   bounded XSim execution and IP/BD inspection/configuration readback. These are
   proposals, not installed capabilities.
3. Evaluate the official server only when a needed service, such as persistent
   interactive sessions, GUI or remote deployment, justifies an additional backend.
   A separately reviewed adapter and client configuration are required: the current
   selector rejects every backend name except `native`.

Do not silently fall back to official tools, another simulator, a different part
or a different release. Maintain one execution owner per operation and keep
evidence from different backends distinguishable. The current decision leaves
execution MCP registration unchanged. Skill adoption and remaining FPGA gaps are
listed in [upstream adoption](fpga_upstream_adoption.md).
