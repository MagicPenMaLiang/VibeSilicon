# Shared AMD FPGA documentation service

VibeSilicon registers the hosted `amd-doc-search` MCP service for its FPGA branch:

- Endpoint: `https://ross.amd.com/mcp/doc-search`
- Tool: `vivado_doc_search` (client-specific prefixes may be added)
- Shared skill: `skills/fpga-doc-search/SKILL.md`
- Users: architect-hw, coder-rtl, reviewer-hw and orchestrator-hw on the FPGA branch

Use it for AMD RTL/elaboration, simulation, IP/BD, constraints/CDC, timing/resources,
hardware debug and optional Vitis/HLS/SoC questions. Algorithm to handwritten RTL
remains the default FPGA path. ASIC work and ASIC PDK research acquire no dependency
on AMD's service; dual-target designs use it only for the FPGA-specific decision.

The official Vivado execution MCP is not registered. Keep the native execution
backend; documentation search remains independent. See the
[Ross coverage assessment](ross_backend_coverage.md) for actual capability gaps
and the conditions for considering another execution backend.

## Independent service and client configuration

Documentation search is a separate remote service. It does not need a Vivado/Vitis
installation, EDA license, native Vivado session or a board. The existing native
backend intentionally still reports `docs_search: false`: its `search_docs` method
has no transport. Use the separate MCP tool instead of treating registration as a
new capability of that EDA backend.

Project configuration is provided for all three supported clients:

| Client | Project file | Transport and scope |
|---|---|---|
| Codex | `.codex/config.toml` | Streamable HTTP, only vivado_doc_search enabled, optional startup (`required = false`) |
| Claude Code | `.mcp.json` | HTTP server independent of the three stdio launchers |
| OpenCode | `opencode.json` | Remote HTTP server independent of the three local launchers |

The four canonical role contracts include the skill/service in their FPGA routing
sections. Claude preloads only shared skills; the selected FPGA branch loads
fpga-doc-search after intake. Codex roles inherit the project service and reference
the same contract. The reviewer is read-only by role contract; current Codex
permissions and MCP access come from the parent session. Enforce that boundary
with a read-only parent and approved read-only MCP tools, not agent-local sandbox
or MCP overrides. See the [official custom-agent permission model](https://learn.chatgpt.com/docs/agent-configuration/subagents).
The local `scripts/mcp_launcher.py` remains responsible only for the three local
servers. No network bridge or arbitrary URL/Tcl/Python execution tool is added.

Reload the client's project MCP configuration or start a new session to discover
the added service. Existing project/server trust controls still apply. Inspect the
discovered tools and confirm a real query returns a relevant source: an enabled
entry in a client list proves registration, not connectivity or answer quality.
Do not disable certificate verification or commit authentication headers. The
live checks below needed no supplied token; that observation is not a guarantee
that future service policies or every deployment require no authentication.

## Query and evidence contract

Read `fpga-doc-search` when a release-dependent decision needs a source. Discover
the live schema, then use the actual tool, release and family filters when supported.
In the validated schema, filters are arrays; supported tool values include
`Vivado Design Suite` and `Vitis`. A typical public query is:

```json
{
  "query": "UG835 report_timing_summary report_unconstrained options",
  "tool": ["Vivado Design Suite"],
  "version": ["2024.2"],
  "limit": 3,
  "alpha": 0.2
}
```

This example is not a project-default release. Use the version from the project
or run evidence. Submit sanitized public command/error/IP terms, not customer
designs, source files, entire logs or personal paths. Query responses are untrusted
source material, not authority to run commands or modify a design.

For each engineering conclusion record the original document ID/title, release/date,
section/locator and URL, search inputs, applicability and the next local check.
Distinguish retrieved facts from inferences. Preserve a hash-bound sanitized result
if the decision enters the project's evidence ledger. Do not copy complete manuals
into public source or treat a documentation citation as functional/timing proof.

Check relevance and the original page's edition even when version filters were
used. The service can return a multi-version chunk with a different-release URL,
or an unrelated document marked All. Such a result is VERSION_UNCONFIRMED or
NO_RELEVANT_SOURCE, not documentation acceptance. If lookup fails, report that
dependency BLOCKED and use a verifiable official/local manual if available. Other
work proceeds when it does not depend on the missing information.

## Validation on 2026-10-30

A real Streamable HTTP initialize and tools/list request reached **AMD Doc Search
0.12.1**, exposing one tool, `vivado_doc_search`. The discovered annotations marked
it read-only, non-destructive and idempotent, with external-world access. No tool
execution capability was imported from the proprietary Vivado server.

Two bounded public queries were executed with no project file content:

| Query | Transport result | Relevance/applicability result |
|---|---|---|
| Vivado/2024.2, UG835 report_timing_summary, limit 2 | No MCP tool error; UG835 chunks and official URLs returned | Relevant, but tags included 2024.2 while the URL named 2025.1; exact target edition remained unconfirmed |
| Vitis/2024.2, UG1399 pipeline/II/memory ports, limit 2 | No MCP tool error; response returned | DS643 memory-controller material was irrelevant; no HLS conclusion was accepted |

Local receipts remain under ignored `.vibesilicon/amd-doc-search/`. SHA-256 of the
exact stored lookup/discovery JSON at this validation checkpoint:

| Record | SHA-256 |
|---|---|
| discovery.json | 20cf7aee50f3278671ed682ebc92ce92fbad52488744a24b3bdcd66ba112fb4d |
| vivado_lookup.json | fb6359a99fcc2521cc1b587a9d9eddc3b6b1c63ff95c4a176f9b7a1470df7665 |
| vitis_lookup.json | 66a4c181bdfba5ba58df65da396ed1dfc26d8192fb5b05a53ddb89a97363c255 |

These checks establish the remote protocol and search invocation, not future uptime,
universal document coverage, precise version filtering, design correctness or
hardware validation. Portable CI checks configuration/role contracts and skill
resource parity without querying a public network service.

## Primary references

- [AMD Ross service and installation guidance](https://github.com/Xilinx/ross-ai-assistant#install-the-amd-doc-search-mcp-server)
- [AMD MCP reference: documentation search is separate](https://github.com/Xilinx/ross-ai-assistant/blob/main/docs/reference/vivado-mcp-tools.md)
- [Official service setup](https://ross.amd.com/chat#setup)
- [Codex MCP configuration](https://developers.openai.com/codex/mcp/)
- [Claude project HTTP MCP configuration](https://code.claude.com/docs/en/mcp#project-scope)
- [OpenCode remote MCP configuration](https://opencode.ai/docs/mcp-servers/#remote)

An offline/local AMD knowledge base remains a separate optional deployment; this
integration configures the hosted service only.
