"""Check shared documentation routing without relying on external network uptime."""

import json
import re
import unittest

import yaml

from tests.support import ROOT
from scripts.sync_agents import load_catalog, resolve_role


ENDPOINT = "https://ross.amd.com/mcp/doc-search"
ROLES = ("architect-hw", "coder-rtl", "reviewer-hw", "orchestrator-hw")


def section(text, name):
    found = re.search(r"(?ms)^\[" + re.escape(name) + r"\]\s*\n(.*?)(?=^\[|\Z)", text)
    if not found:
        raise AssertionError(f"missing configuration section: {name}")
    return found[1]


def array(text, field):
    found = re.search(r"(?m)^" + re.escape(field) + r"\s*=\s*(\[[^\n]*\])\s*$", text)
    if not found:
        raise AssertionError(f"missing array: {field}")
    return json.loads(found[1])


class FpgaDocServiceTests(unittest.TestCase):
    def test_clients_share_fixed_official_endpoint_and_no_embedded_credentials(self):
        claude = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["amd-doc-search"]
        opencode = json.loads((ROOT / "opencode.json").read_text())["mcp"]["amd-doc-search"]
        self.assertEqual(claude, {"type": "http", "url": ENDPOINT})
        self.assertEqual(opencode["type"], "remote")
        self.assertEqual(opencode["url"], ENDPOINT)
        self.assertTrue(opencode["enabled"])
        self.assertNotIn("headers", opencode)
        self.assertNotIn("command", opencode)
        codex = section((ROOT / ".codex/config.toml").read_text(), "mcp_servers.amd-doc-search")
        self.assertRegex(codex, rf'(?m)^url = "{re.escape(ENDPOINT)}"$')
        self.assertEqual(array(codex, "enabled_tools"), ["vivado_doc_search"])
        self.assertRegex(codex, r"(?m)^required = false$")
        self.assertNotRegex(codex, r"(?m)^(?:command|args|http_headers|bearer_token_env_var)\s*=")

    def test_all_roles_have_shared_skill_and_registered_service(self):
        registered = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]
        for role in ROLES:
            with self.subTest(role=role):
                branch = resolve_role(load_catalog(ROOT), role, "fpga")["branches"]["fpga"]
                skills = branch["skills"]
                servers = branch["mcp_servers"]
                self.assertIn("fpga-doc-search", skills)
                self.assertIn("amd-doc-search", servers)
                self.assertEqual(len(skills), len(set(skills)))
                self.assertTrue(set(servers) <= set(registered))
                for skill in skills:
                    self.assertTrue((ROOT / "skills" / skill / "SKILL.md").is_file())
                native = (ROOT / ".claude/agents" / f"{role}.md").read_text()
                metadata = yaml.safe_load(native.split("---", 2)[1])
                self.assertNotIn("fpga-doc-search", metadata["skills"])  # Loaded after target intake.
                self.assertIn("amd-doc-search", metadata["mcpServers"])

    def test_reviewer_routes_only_documentation_and_declares_inherited_codex_permissions(self):
        plan = resolve_role(load_catalog(ROOT), "reviewer-hw", "both")
        self.assertEqual(plan["branches"]["fpga"]["mcp_servers"], ["amd-doc-search"])
        self.assertEqual(plan["branches"]["asic"]["mcp_servers"], [])
        native = (ROOT / ".codex/agents/reviewer-hw.toml").read_text()
        self.assertNotIn("sandbox_mode", native)
        self.assertNotIn("[mcp_servers.", native)
        self.assertRegex(section(native, "features"), r"(?m)^request_permissions_tool = false$")
        self.assertIn("read-only parent session", native)

    def test_skill_route_does_not_add_an_asic_documentation_gate(self):
        text = (ROOT / "skills/fpga-doc-search/SKILL.md").read_text(encoding="utf-8")
        metadata = yaml.safe_load(text.split("---", 2)[1])
        self.assertEqual(metadata["metadata"]["routes"], ["fpga"])
        target_gates = section((ROOT / "subagents/orchestrator-fpga.toml").read_text(), "target_gates")
        self.assertFalse({"fpga-doc-search", "amd-doc-search", "documentation"} & set(array(target_gates, "asic")))


if __name__ == "__main__":
    unittest.main()
