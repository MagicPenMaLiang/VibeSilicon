"""High-confidence RTL-XPR inventory stays source-bound and non-blocking."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.quality_gate import rtl_xpr_shadow


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("project/demo/rtl_project_manifest.json")
SOURCE = Path("project/demo/rtl/demo.sv")


class RtlXprShadowTests(unittest.TestCase):
    def project(self, directory, text):
        root = Path(directory)
        rtl = root / SOURCE
        rtl.parent.mkdir(parents=True)
        rtl.write_text(text, encoding="utf-8", newline="\n")
        manifest = {
            "schema_version": 1, "project_root": "project/demo", "target": "fpga",
            "source_kinds": ["handwritten"], "top": "demo",
            "source_roots": ["project/demo/rtl"], "sources": [SOURCE.as_posix()],
            "headers": [], "include_dirs": ["project/demo/rtl"],
            "defines": {}, "parameters": {}, "clocks": [], "resets": [],
        }
        (root / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
        return root, rtl

    def test_comments_strings_and_casez_do_not_trigger_findings(self):
        source = '''module demo;
// casex (a) and 1'bx are explanation only
/* 8'hzz is also explanation */
initial $display("casex (b) 1'bz");
casez (a)
  default: ;
endcase
endmodule
'''
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.project(directory, source)
            report = rtl_xpr_shadow.snapshot(MANIFEST, repository_root=root)
        self.assertEqual(report["status"], "SHADOW")
        self.assertEqual(report["finding_count"], 0)
        self.assertEqual(report["preview"], [])

    def test_casex_and_four_state_literals_have_bounded_locations(self):
        source = '''module demo;
casex (a)
  2'bx1: b = 1'bz;
  default: b = 2'h0x;
endcase
endmodule
'''
        with tempfile.TemporaryDirectory() as directory:
            root, _ = self.project(directory, source)
            report = rtl_xpr_shadow.snapshot(MANIFEST, repository_root=root)
        self.assertEqual(report["finding_count"], 4)
        self.assertEqual(report["by_kind"], {"CASEX": 1, "X_LITERAL": 2, "Z_LITERAL": 1})
        self.assertEqual({item["line"] for item in report["preview"]}, {2, 3, 4})
        self.assertTrue(all(item["file"] == SOURCE.as_posix() for item in report["preview"]))
        self.assertNotIn("2'bx1", json.dumps(report))

    def test_lf_crlf_equivalence_and_determinism(self):
        with tempfile.TemporaryDirectory() as directory:
            root, rtl = self.project(directory, "module demo;\ncasex (a)\nendcase\nendmodule\n")
            first = rtl_xpr_shadow.snapshot(MANIFEST, repository_root=root)
            rtl.write_bytes(rtl.read_bytes().replace(b"\n", b"\r\n"))
            manifest = root / MANIFEST
            manifest.write_bytes(manifest.read_bytes().replace(b"\n", b"\r\n"))
            second = rtl_xpr_shadow.snapshot(MANIFEST, repository_root=root)
        self.assertEqual(first, second)

    def test_unterminated_comment_and_midscan_edit_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root, rtl = self.project(directory, "module demo; /* not closed\n")
            with self.assertRaisesRegex(ValueError, "unterminated"):
                rtl_xpr_shadow.snapshot(MANIFEST, repository_root=root)
            rtl.write_text("module demo; endmodule\n", encoding="utf-8")
            original = rtl_xpr_shadow._findings

            def modify(text, path):
                rtl.write_text("module demo; casex (a) endcase endmodule\n", encoding="utf-8")
                return original(text, path)

            with patch.object(rtl_xpr_shadow, "_findings", side_effect=modify):
                with self.assertRaisesRegex(ValueError, "changed during"):
                    rtl_xpr_shadow.snapshot(MANIFEST, repository_root=root)

    def test_example_manifest_is_inventory_not_pass_claim(self):
        report = rtl_xpr_shadow.snapshot(
            Path("examples/rtl/counter/rtl_project_manifest.json"),
            repository_root=ROOT,
        )
        self.assertEqual(report["status"], "SHADOW")
        self.assertEqual(report["rule_id"], "RTL-XPR-001")
        self.assertIn("no severity or merge gate change", report["limitations"][0])


if __name__ == "__main__":
    unittest.main()
