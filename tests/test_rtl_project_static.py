"""Static G1 checks fail closed on unavailable or changing source evidence."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.quality_gate import rtl_project_static
from scripts.quality_gate.rtl_manifest import ManifestError
from scripts.quality_gate.rtl_project_lint import _hash_sources
from scripts.quality_gate.rtl_readability import analyze
from scripts.quality_gate.scan_async_reg import scan_file


ROOT = Path(__file__).resolve().parents[1]


class RtlProjectStaticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "counter.sv"
        self.source.write_bytes((ROOT / "examples/rtl/counter/rtl/counter.sv").read_bytes())
        self.manifest = {"sources": ["counter.sv"], "headers": []}
        self.hashes = _hash_sources(self.root, self.manifest)

    def run_check(self):
        return rtl_project_static.run_static_checks(
            self.manifest, repository_root=self.root, source_hashes=self.hashes,
        )

    def test_clean_sources_pass_both_checks(self):
        report = self.run_check()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["async_reg"], {"missing": 0, "files_scanned": 1})
        self.assertEqual(report["source_sha256"], self.hashes)

    def test_async_failure_cannot_be_hidden_by_readability_pass(self):
        missing = [{"line": 1, "signal": "sync_q"}]
        with patch.object(rtl_project_static, "scan_file", return_value=missing):
            report = self.run_check()
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["readability"]["blocking"], 0)
        self.assertEqual(report["findings"][0]["message_code"], "ASYNC_REG_MISSING")

    def test_scanner_io_failure_never_returns_pass(self):
        with patch.object(rtl_project_static, "scan_file", side_effect=OSError("unreadable source")):
            with self.assertRaises(OSError):
                self.run_check()
        with self.assertRaises(FileNotFoundError):
            scan_file(self.root / "missing.sv")

    def test_mutated_source_during_check_is_rejected(self):
        def mutate(path, *, root):
            report = analyze(path, root=root)
            path.write_text(path.read_text(encoding="utf-8") + "// changed\n", encoding="utf-8")
            return report

        with patch.object(rtl_project_static, "analyze", side_effect=mutate):
            with self.assertRaisesRegex(ManifestError, "changed during"):
                self.run_check()

    def test_invalid_utf8_never_returns_pass(self):
        self.source.write_bytes(b"\xff")
        self.hashes = _hash_sources(self.root, self.manifest)
        with self.assertRaises(UnicodeError):
            self.run_check()
        with self.assertRaises(UnicodeError):
            scan_file(self.source)


if __name__ == "__main__":
    unittest.main()
