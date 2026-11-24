"""Release selection, fail-closed inspection and reproducible export checks."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import public_release_audit as release


class PublicReleaseAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "README.md").write_text("# Neutral source\n", encoding="utf-8")

    def git(self, *args):
        try:
            return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                                  check=True, env=os.environ.copy())
        except subprocess.CalledProcessError as error:
            raise RuntimeError(error.stderr.decode("utf-8", errors="replace")) from error

    def init_git(self):
        if not shutil.which("git"):
            self.skipTest("Git is required for checkout-selection tests")
        self.git("init")
        (self.root / ".gitignore").write_text(".vibesilicon/\nprojects/\n*.log\n", encoding="utf-8")

    def test_neutral_knowledge_is_public_source_without_asset_exemptions(self):
        path = self.root / "knowledge/fpga-video/cases/example.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"observation": "synthetic example"}\n', encoding="utf-8")
        self.assertEqual(release.audit(self.root), [])
        binary = path.with_suffix(".bit")
        binary.write_bytes(b"not a source artifact")
        self.assertTrue(any("generated/binary artifact" in item for item in release.audit(self.root)))
        binary.unlink()
        path.write_text("local = " + "D:" + "/private-user/asset\n", encoding="utf-8")
        self.assertTrue(any("local path" in item for item in release.audit(self.root)))

    def test_source_export_passes_and_unknown_content_is_blocked(self):
        self.assertEqual(release.audit(self.root), [])
        path = self.root / "private/design.sv"
        path.parent.mkdir()
        path.write_text("module design; endmodule\n")
        self.assertTrue(any("outside public source profile" in issue for issue in release.audit(self.root)))

    def test_zcode_and_trial_profiles_keep_private_and_generated_content_blocked(self):
        for name in (".zcode/config.json", ".zcode/agents/reviewer-hw.md", "trials/example/scores.json"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        self.assertEqual(release.audit(self.root), [])
        for name in (".zcode/config.local.json", ".zcode/secrets/token.json", "trials/example/run.bit"):
            with self.subTest(name=name):
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
                self.assertTrue(any("outside public source profile" in item for item in release.audit(self.root)))
                path.unlink()

    def test_ignored_builds_are_excluded_but_forced_builds_still_fail(self):
        self.init_git()
        with (self.root / ".gitignore").open("a", encoding="utf-8") as stream:
            stream.write("/obj_*/\n/gate_*.json\n")
        path = self.root / "obj_example/generated.cpp"
        path.parent.mkdir()
        path.write_text("generated\n", encoding="utf-8")
        (self.root / "gate_example.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(release.audit(self.root), [])
        self.git("add", "-f", "obj_example/generated.cpp")
        self.assertTrue(any("outside public source profile" in item for item in release.audit(self.root)))

    def test_ignored_local_tree_is_not_traversed_but_tracked_ignored_files_are_checked(self):
        self.init_git()
        local = self.root / "projects/design"
        local.mkdir(parents=True)
        (local / "run.log").write_text("local run")
        # Inspection of an ignored directory must not be needed for candidate enumeration.
        with patch.object(Path, "rglob", side_effect=AssertionError("unexpected traversal")):
            self.assertEqual(release.audit(self.root), [])
        self.git("add", "-f", "projects/design/run.log")
        issues = release.audit(self.root)
        self.assertTrue(any("outside public source profile" in issue for issue in issues))
        self.assertTrue(any("generated/binary artifact" in issue for issue in issues))

    def test_untracked_source_is_checked_and_tracked_deletions_are_not_exported(self):
        self.init_git()
        self.git("add", "README.md")
        (self.root / "README.md").unlink()
        source = self.root / "docs/new.md"
        source.parent.mkdir()
        source.write_text("pass" + "word = 'example-secret'\n", encoding="utf-8")
        issues = release.audit(self.root)
        self.assertTrue(any("docs/new.md" in issue for issue in issues))
        self.assertNotIn(self.root / "README.md", release.source_files(self.root))

    def test_templates_shells_and_locks_receive_sensitive_text_checks(self):
        for name in ("templates/example.json.tpl", "scripts/example.sh", "requirements.lock"):
            with self.subTest(name=name):
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("pass" + "word = 'example-secret'\n", encoding="utf-8")
                self.assertTrue(any(name in issue for issue in release.audit(self.root)))
                path.unlink()

    def test_unreadable_source_is_reported_instead_of_raising(self):
        original = Path.read_text
        def unreadable(path, *args, **kwargs):
            if path.name == "README.md":
                raise OSError("unreadable source")
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", unreadable):
            self.assertTrue(release.audit(self.root))

    def test_git_failure_does_not_fall_back_to_a_partial_tree(self):
        self.init_git()
        with patch.object(release.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            self.assertTrue(any("cannot enumerate" in issue for issue in release.audit(self.root)))

    def test_git_lookup_preserves_empty_config_values_after_environment_restore(self):
        with patch.dict(os.environ, {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.pager",
                                     "GIT_CONFIG_VALUE_0": ""}):
            with patch.dict(os.environ, {"VIBESILICON_ENV_TEST": "1"}):
                pass
            self.init_git()
            self.assertEqual(release.audit(self.root), [])

    def test_export_does_not_use_parent_git_checkout(self):
        self.init_git()
        export = self.root / ".vibesilicon/export"
        export.mkdir(parents=True)
        (export / "README.md").write_text("# Export\n")
        with patch.object(release.subprocess, "run", side_effect=AssertionError("parent Git lookup")):
            self.assertEqual(release.audit(export), [])

    def test_snapshot_is_hash_bound_independently_audited_and_never_overwritten(self):
        self.init_git()
        destination = Path(".vibesilicon/release")
        manifest = release.prepare_snapshot(self.root, destination)
        prepared = self.root / destination
        self.assertEqual(release.audit(prepared / "source"), [])
        self.assertEqual(json.loads((prepared / "manifest.json").read_text()), manifest)
        for item in manifest["files"]:
            data = (prepared / "source" / item["path"]).read_bytes()
            self.assertEqual(item["sha256"], "sha256:" + hashlib.sha256(data).hexdigest())
        self.assertEqual(self.git("diff", "--cached", "--name-only").stdout, b"")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            release.prepare_snapshot(self.root, destination)
        with self.assertRaisesRegex(ValueError, "below"):
            release.prepare_snapshot(self.root, Path("outside"))

    def test_generated_unknown_binary_empty_tree_and_symlinks_fail_closed(self):
        for name in ("docs/run.bit", "docs/program.exe"):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"binary")
            self.assertTrue(release.audit(self.root))
            path.unlink()
        (self.root / "README.md").unlink()
        self.assertTrue(release.audit(self.root))
        link = self.root / "README.md"
        try:
            link.symlink_to(self.root / "missing.md")
        except OSError:
            return  # Reparse failures also have a privilege-independent test below.
        self.assertTrue(release.audit(self.root))

    def test_reparse_metadata_is_rejected_without_reading_content(self):
        class Reparse:
            st_mode = 0o100644
            st_reparse_tag = 1
        path = self.root / "README.md"
        with patch.object(release, "source_files", return_value=[path]), patch.object(Path, "lstat", return_value=Reparse()):
            self.assertTrue(any("reparse" in issue for issue in release.audit(self.root)))


if __name__ == "__main__":
    unittest.main()
