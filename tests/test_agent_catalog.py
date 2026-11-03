"""Behavioral checks for conditional routing, compatibility and generated adapters."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from scripts.sync_agents import generated_files, load_catalog, resolve_role, synchronize, validate_catalog
from scripts.sync_skills import inventory
from tests.support import ROOT


class AgentCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog(ROOT)
        cls.manifest, _ = inventory(ROOT)

    def test_asic_routes_do_not_require_fpga_skills_or_services(self):
        entries = {entry["name"]: entry for entry in self.manifest["skills"]}
        for role in self.catalog["roles"]:
            plan = resolve_role(self.catalog, role, "asic")
            with self.subTest(role=role):
                self.assertFalse(plan["execution_authorized"])
                self.assertEqual(set(plan["branches"]), {"asic"})
                branch = plan["branches"]["asic"]
                self.assertFalse(set(branch["mcp_servers"]) - {"python-sim"})
                for name in branch["skills"]:
                    self.assertIn("asic", entries[name]["routes"])
                    self.assertEqual(entries[name]["kind"], "canonical")
                self.assertTrue(branch["backend_modules"])

    def test_legacy_role_names_resolve_to_the_same_target_contract(self):
        for alias, canonical in self.catalog["aliases"].items():
            for target in ("fpga", "asic", "both"):
                old = resolve_role(self.catalog, alias, target)
                new = resolve_role(self.catalog, canonical, target)
                old["requested_agent"] = canonical
                with self.subTest(alias=alias, target=target):
                    self.assertEqual(old, new)

    def test_dual_target_retains_two_independent_branches(self):
        both = resolve_role(self.catalog, "coder-rtl", "both")
        self.assertEqual(set(both["branches"]), {"fpga", "asic"})
        for target in both["branches"]:
            self.assertEqual(both["branches"][target], resolve_role(self.catalog, "coder-rtl", target)["branches"][target])
        self.assertIn("vivado", both["branches"]["fpga"]["mcp_servers"])
        self.assertNotIn("vivado", both["branches"]["asic"]["mcp_servers"])

    def test_wrong_target_skill_and_fpga_service_in_asic_are_rejected(self):
        for field, value in (("skills", "fpga-dcp-analysis"), ("mcp_servers", "vivado")):
            changed = copy.deepcopy(self.catalog)
            changed["roles"]["coder-rtl"]["routing"]["asic"][field].append(value)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "asic"):
                validate_catalog(changed, self.manifest, ROOT)

    def test_common_skill_must_support_both_targets(self):
        changed = copy.deepcopy(self.catalog)
        changed["roles"]["architect-hw"]["agent"]["skills"].append("fpga-doc-search")
        with self.assertRaisesRegex(ValueError, "asic skill"):
            validate_catalog(changed, self.manifest, ROOT)

    def test_alias_chains_unknown_skills_and_missing_modules_are_rejected(self):
        mutations = []
        chained = copy.deepcopy(self.catalog)
        chained["aliases"]["old-role"] = "coder-fpga"
        mutations.append(chained)
        unknown = copy.deepcopy(self.catalog)
        unknown["roles"]["coder-rtl"]["agent"]["skills"].append("missing-skill")
        mutations.append(unknown)
        legacy = copy.deepcopy(self.catalog)
        legacy["roles"]["coder-rtl"]["agent"]["skills"].append("fpga-ip-design")
        mutations.append(legacy)
        missing = copy.deepcopy(self.catalog)
        missing["roles"]["coder-rtl"]["routing"]["asic"]["backend_modules"].append("scripts.asic_missing_backend")
        mutations.append(missing)
        for index, changed in enumerate(mutations):
            with self.subTest(case=index), self.assertRaises(ValueError):
                validate_catalog(changed, self.manifest, ROOT)

    def test_reviewer_cannot_gain_implementation_mcp_access(self):
        changed = copy.deepcopy(self.catalog)
        changed["roles"]["reviewer-hw"]["routing"]["fpga"]["mcp_servers"].append("vivado")
        with self.assertRaisesRegex(ValueError, "reviewer"):
            validate_catalog(changed, self.manifest, ROOT)

    def test_reviewer_read_only_flag_requires_an_actual_boolean(self):
        for value in (False, "false", 1):
            changed = copy.deepcopy(self.catalog)
            changed["roles"]["reviewer-hw"]["guardrails"]["read_only"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "reviewer"):
                validate_catalog(changed, self.manifest, ROOT)

    def test_unknown_role_or_target_is_rejected(self):
        for role, target in (("missing", "asic"), ("coder-rtl", "unknown")):
            with self.subTest(role=role, target=target), self.assertRaises(ValueError):
                resolve_role(self.catalog, role, target)

    def test_role_adapters_match_the_canonical_catalog(self):
        self.assertEqual(synchronize(ROOT), [])

    def test_generation_preserves_unmanaged_opencode_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = {"mcp": {"custom": {"enabled": False}}, "agent": {"local-helper": {"mode": "subagent"}},
                        "instructions": ["custom.md"], "permission": {"bash": "ask"}}
            path = root / "opencode.json"
            path.write_text(json.dumps(original), encoding="utf-8")
            before = path.read_bytes()
            generated = generated_files(root, self.catalog)
            self.assertEqual(path.read_bytes(), before)
            result = json.loads(generated["opencode.json"])
            for key in ("mcp", "instructions", "permission"):
                self.assertEqual(result[key], original[key])
            self.assertEqual(result["agent"]["local-helper"], original["agent"]["local-helper"])
            for name in ("reviewer-hw", "reviewer-fpga"):
                self.assertEqual(result["agent"][name]["permission"]["edit"], "deny")
                self.assertEqual(result["agent"][name]["permission"]["bash"], "deny")

    def test_claude_preloads_only_shared_skills_and_restricts_reviewer(self):
        generated = generated_files(ROOT, self.catalog)
        entries = {entry["name"]: entry for entry in self.manifest["skills"]}
        for name in set(self.catalog["roles"]) | set(self.catalog["aliases"]):
            metadata = yaml.safe_load(generated[f".claude/agents/{name}.md"].decode().split("---", 2)[1])
            for skill in metadata["skills"]:
                self.assertTrue({"fpga", "asic"} <= set(entries[skill]["routes"]))
            if name.startswith("reviewer-"):
                self.assertNotIn("Bash", metadata["tools"])
                self.assertNotIn("Write", metadata["tools"])
                self.assertEqual(metadata["mcpServers"], ["amd-doc-search"])

    def test_generated_toml_is_parseable_and_preserves_contracts(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("stdlib TOML syntax validation requires Python 3.11+")
        for path, content in generated_files(ROOT, self.catalog).items():
            if path.endswith(".toml"):
                parsed = tomllib.loads(content.decode())
                if path.startswith("subagents/"):
                    name = parsed["agent"]["name"]
                    canonical = self.catalog["aliases"].get(name, name)
                    parsed["agent"]["name"] = canonical
                    parsed["agent"].pop("alias_of", None)
                    self.assertEqual(parsed, self.catalog["roles"][canonical])


if __name__ == "__main__":
    unittest.main()
