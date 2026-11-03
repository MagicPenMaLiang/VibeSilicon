#!/usr/bin/env python3
"""Validate hardware role routing and synchronize native client adapters."""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

import yaml
from jsonschema import validate

from scripts.sync_skills import ROOT, inventory


ROLES = {"architect-hw", "coder-rtl", "reviewer-hw", "orchestrator-hw"}
SERVERS = {"python-sim", "amd-doc-search", "vitis-hls", "vivado"}


def load_catalog(root: Path = ROOT) -> dict:
    catalog = json.loads((root / "subagents/catalog.json").read_text(encoding="utf-8"))
    schema = json.loads((root / "schemas/agent_catalog.schema.json").read_text(encoding="utf-8"))
    validate(catalog, schema)
    manifest, _ = inventory(root)
    validate_catalog(catalog, manifest, root)
    return catalog


def validate_catalog(catalog: dict, manifest: dict, root: Path) -> None:
    roles = catalog["roles"]
    aliases = catalog["aliases"]
    if set(roles) != ROLES or catalog["default_agent"] != "orchestrator-hw":
        raise ValueError("catalog must retain the four canonical hardware roles")
    for alias, target in aliases.items():
        if not re.fullmatch(r"[a-z0-9-]+", alias) or alias in roles or target not in roles:
            raise ValueError(f"agent alias must resolve directly to a canonical role: {alias}")
    skills = {entry["name"]: entry for entry in manifest["skills"]}
    for name, contract in roles.items():
        agent = contract["agent"]
        if agent["name"] != name:
            raise ValueError(f"agent identity mismatch: {name}")
        for target in ("fpga", "asic"):
            route = contract["routing"][target]
            servers = set(agent["mcp_servers"] + route["mcp_servers"])
            if not servers <= SERVERS or target == "asic" and servers - {"python-sim"}:
                raise ValueError(f"invalid {target} tool routing for {name}")
            for skill in agent["skills"] + route["skills"]:
                entry = skills.get(skill)
                if entry is None or entry["kind"] != "canonical" or target not in entry["routes"]:
                    raise ValueError(f"invalid {target} skill routing for {name}: {skill}")
            for module in route.get("backend_modules", []):
                if not re.fullmatch(r"scripts\.asic_[a-z_]+", module):
                    raise ValueError(f"invalid backend module: {module}")
                if not (root / (module.replace(".", "/") + ".py")).is_file():
                    raise ValueError(f"missing backend module: {module}")
        if name == "reviewer-hw" and (contract["guardrails"].get("read_only") is not True
                                      or agent["mcp_servers"]
                                      or contract["routing"]["fpga"]["mcp_servers"] != ["amd-doc-search"]):
            raise ValueError("reviewer must remain read-only with documentation-only MCP access")
        if "handoff" in contract and contract["handoff"]["next_agent"] not in roles:
            raise ValueError(f"handoff names an unknown role: {name}")


def resolve_role(catalog: dict, name: str, target: str) -> dict:
    if target not in {"fpga", "asic", "both"}:
        raise ValueError(f"unknown target: {target}")
    canonical = catalog["aliases"].get(name, name)
    if canonical not in catalog["roles"]:
        raise ValueError(f"unknown agent: {name}")
    contract = catalog["roles"][canonical]
    branches = {}
    for branch in ("fpga", "asic") if target == "both" else (target,):
        route = contract["routing"][branch]
        branches[branch] = {
            "skills": list(dict.fromkeys(contract["agent"]["skills"] + route["skills"])),
            "mcp_servers": list(dict.fromkeys(contract["agent"]["mcp_servers"] + route["mcp_servers"])),
            "backend_modules": route.get("backend_modules", []),
        }
    return {"requested_agent": name, "canonical_agent": canonical, "target_flow": target,
            "branches": branches, "execution_authorized": False}


def _toml(data: dict, prefix: str = "") -> str:
    lines = []
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    for key, value in data.items():
        if isinstance(value, dict):
            section = f"{prefix}.{key}" if prefix else key
            lines.extend(["", f"[{section}]", _toml(value, section).rstrip()])
    return "\n".join(lines).lstrip() + "\n"


def _instructions(name: str, canonical: str) -> str:
    alias = f"Compatibility name {name} resolves to {canonical}.\n" if name != canonical else ""
    return alias + (
        f"Read AGENTS.md and subagents/{canonical}.toml before starting.\n"
        "subagents/catalog.json is the canonical source for role contracts and target routing.\n"
        "Load shared skills, then only the declared target branch; both keeps separate evidence and acceptance.\n"
        "Use python -m scripts.sync_agents --plan " + canonical + " --target <fpga|asic|both> for a read-only routing plan.\n"
        "FPGA tools and AMD documentation are conditional on FPGA work, never ASIC prerequisites.\n"
        "Use the ASIC CLI adapters listed in the selected routing contract; no ASIC MCP server is registered.\n"
        "Follow role inputs, outputs, iteration limits and guardrails. Delegate only when authorized.\n"
        "Preserve independent human approval for architecture, reset/CDC exceptions, security, PDK selection and production signoff.\n"
        "Keep golden inputs read-only. Do not invent numeric widths, clocks, protocols or PDK assumptions.\n"
        "Missing tools, skipped checks and inconclusive proofs cannot PASS. Bind claims to primary current-run evidence.\n"
        + ("Remain read-only; do not modify the design or launch implementation tools.\n"
           "Codex custom agents inherit parent permissions and MCP servers; agent-local sandbox/MCP overrides do not isolate them.\n"
           "For permission-enforced independent review use a read-only parent session with only approved read-only MCP tools.\n"
           "Do not claim enforcement merely from this role contract.\n" if canonical == "reviewer-hw" else "")
    )


def generated_files(root: Path, catalog: dict) -> dict[str, bytes]:
    outputs = {}
    opencode_path = root / "opencode.json"
    opencode = json.loads(opencode_path.read_text(encoding="utf-8"))
    agents = {}
    targets = {name: name for name in catalog["roles"]} | catalog["aliases"]
    for name, canonical in targets.items():
        contract = copy.deepcopy(catalog["roles"][canonical])
        agent = contract["agent"]
        agent["name"] = name
        if name != canonical:
            agent["alias_of"] = canonical
        header = "# Generated by scripts.sync_agents from subagents/catalog.json.\n"
        outputs[f"subagents/{name}.toml"] = (header + _toml(contract)).encode()
        instructions = _instructions(name, canonical)
        description = agent["description"] if name == canonical else f"Compatibility alias for {canonical}."
        codex = {"name": name, "description": description}
        codex["developer_instructions"] = instructions
        if canonical == "reviewer-hw":
            codex["features"] = {"request_permissions_tool": False, "apps": False, "plugins": False}
        codex_text = header + _toml(codex)
        outputs[f".codex/agents/{name}.toml"] = codex_text.encode()
        # Preload shared skills only. Target-specific skills are loaded after intake.
        claude = {"name": name, "description": description, "skills": agent["skills"],
                  "maxTurns": agent["max_turns"]}
        servers = list(dict.fromkeys(agent["mcp_servers"] + contract["routing"]["fpga"]["mcp_servers"]))
        if servers:
            claude["mcpServers"] = servers
        if canonical == "reviewer-hw":
            claude["tools"] = ["Read", "Grep", "Glob", "mcp__amd-doc-search__vivado_doc_search"]
        outputs[f".claude/agents/{name}.md"] = (
            "---\n" + yaml.safe_dump(claude, sort_keys=False, allow_unicode=True) + "---\n\n" + instructions
        ).encode()
        agents[name] = {
            "description": description,
            "mode": "primary" if canonical == "orchestrator-hw" else "subagent",
            "prompt": instructions,
            "permission": {"edit": "deny" if canonical == "reviewer-hw" else "allow" if canonical == "coder-rtl" else "ask",
                           "bash": "deny" if canonical == "reviewer-hw" else "ask", "external_directory": "deny"},
        }
    # Preserve independently added OpenCode agents and all non-agent client settings.
    for name, value in opencode.get("agent", {}).items():
        if name not in targets:
            agents[name] = value
    opencode["agent"] = agents
    opencode["default_agent"] = catalog["default_agent"]
    outputs["opencode.json"] = (json.dumps(opencode, indent=2, ensure_ascii=False) + "\n").encode()
    return outputs


def synchronize(root: Path = ROOT, *, write: bool = False) -> list[str]:
    root = root.resolve(strict=True)
    outputs = generated_files(root, load_catalog(root))
    differences = []
    # Validate every destination before changing any adapter.
    for relative in outputs:
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"adapter escapes repository: {relative}")
    for relative, content in outputs.items():
        path = root / relative
        if not path.is_file() or path.read_bytes() != content:
            differences.append(relative)
            if write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
    return differences


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--plan", metavar="AGENT")
    parser.add_argument("--target", choices=("fpga", "asic", "both"))
    args = parser.parse_args()
    if bool(args.plan) != bool(args.target):
        parser.error("--plan and --target must be used together")
    if args.plan:
        print(json.dumps(resolve_role(load_catalog(), args.plan, args.target), indent=2))
        return 0
    differences = synchronize(write=args.write)
    remaining = synchronize() if args.write else differences
    print(json.dumps({"status": "FAIL" if remaining else "PASS", "differences": remaining}))
    return 1 if remaining else 0


if __name__ == "__main__":
    raise SystemExit(main())
