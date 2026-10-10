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


if __name__ == "__main__":
    unittest.main()
