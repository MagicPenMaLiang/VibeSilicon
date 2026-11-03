import json
from pathlib import Path
import tempfile
import unittest

from scripts.sync_skills import inventory, synchronize
from tests.support import ROOT


class SkillResourceTests(unittest.TestCase):
    def test_native_skills_include_identical_resources(self):
        self.assertEqual(synchronize(ROOT), [])
        manifest, files = inventory(ROOT)
        self.assertGreaterEqual(manifest["skill_count"], 19)
        self.assertTrue(any(path.endswith(".cpp") for path in files))
        self.assertTrue(any(path.endswith(".v") for path in files))
        self.assertEqual(json.loads((ROOT / "skills/manifest.json").read_text()), manifest)

    def test_missing_reference_blocks_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills/example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: example\n---\n`references/missing.md`\n")
            with self.assertRaisesRegex(ValueError, "missing resource"):
                synchronize(root, write=True)
            self.assertFalse((root / ".agents").exists())

    def test_unknown_native_file_is_preserved_and_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills/example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: example\n---\n")
            synchronize(root, write=True)
            custom = root / ".agents/skills/example/custom.md"
            custom.write_text("user content")
            self.assertTrue(synchronize(root, write=True))
            self.assertEqual(custom.read_text(), "user content")

    def test_runtime_state_is_not_packaged_or_replicated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills/example"
            state = skill / ".omc/state/session.json"
            state.parent.mkdir(parents=True)
            state.write_text("runtime state")
            (skill / "SKILL.md").write_text("---\nname: example\n---\n")
            synchronize(root, write=True)
            self.assertFalse((root / ".agents/skills/example/.omc").exists())
            self.assertEqual(state.read_text(), "runtime state")
            native_state = root / ".agents/skills/example/.omc/state.json"
            native_state.parent.mkdir(parents=True)
            native_state.write_text("native state")
            self.assertEqual(synchronize(root), [])
            self.assertEqual(native_state.read_text(), "native state")

    def test_aliases_resolve_directly_to_canonical_skills_with_matching_routes(self):
        manifest, _ = inventory(ROOT)
        entries = {entry["name"]: entry for entry in manifest["skills"]}
        aliases = [entry for entry in entries.values() if entry["kind"] == "compatibility"]
        self.assertEqual(len(aliases), manifest["compatibility_alias_count"])
        self.assertEqual(manifest["canonical_skill_count"] + len(aliases), manifest["skill_count"])
        for alias in aliases:
            target = entries[alias["alias_of"]]
            self.assertEqual(target["kind"], "canonical")
            self.assertEqual(alias["routes"], target["routes"])

    def test_alias_cycle_missing_target_and_route_mismatch_block_before_writes(self):
        cases = [("example", "[fpga]", "[fpga]"),
                 ("missing", "[fpga]", "[fpga]"),
                 ("target", "[asic]", "[fpga]")]
        for target, alias_routes, canonical_routes in cases:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for name, metadata in (("example", f"  routes: {alias_routes}\n  alias_of: {target}\n"),
                                       ("target", f"  routes: {canonical_routes}\n")):
                    path = root / f"skills/{name}/SKILL.md"
                    path.parent.mkdir(parents=True)
                    path.write_text(f"---\nname: {name}\nmetadata:\n{metadata}---\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "alias"):
                    synchronize(root, write=True)
                self.assertFalse((root / ".agents").exists())

    def test_compatibility_resources_follow_canonical_changes_without_deleting_unknown_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, alias in (("target", ""), ("old", "  alias_of: target\n")):
                entry = root / f"skills/{name}/SKILL.md"
                entry.parent.mkdir(parents=True)
                entry.write_text(f"---\nname: {name}\nmetadata:\n  routes: [fpga]\n{alias}---\n", encoding="utf-8")
            resource = root / "skills/target/references/contract.md"
            resource.parent.mkdir()
            resource.write_text("first contract", encoding="utf-8")
            synchronize(root, write=True)
            legacy = root / "skills/old/references/contract.md"
            self.assertEqual(legacy.read_text(), "first contract")
            resource.write_text("updated contract", encoding="utf-8")
            self.assertIn("skills/old/references/contract.md", synchronize(root))
            synchronize(root, write=True)
            for path in (legacy, root / ".agents/skills/old/references/contract.md",
                         root / ".claude/skills/old/references/contract.md"):
                self.assertEqual(path.read_text(), "updated contract")
            unknown = legacy.parent / "custom.md"
            unknown.write_text("user content", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected compatibility resource"):
                synchronize(root, write=True)
            self.assertEqual(unknown.read_text(), "user content")

    def test_malformed_frontmatter_and_duplicate_routes_do_not_generate_adapters(self):
        for metadata in ("name: wrong\n", "metadata:\n  routes: [fpga, fpga]\n",
                         "metadata:\n  routes: [[]]\n"):
            with self.subTest(metadata=metadata), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "skills/example/SKILL.md"
                path.parent.mkdir(parents=True)
                path.write_text(f"---\nname: example\n{metadata}---\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    synchronize(root, write=True)
                self.assertFalse((root / ".agents").exists())


if __name__ == "__main__":
    unittest.main()
