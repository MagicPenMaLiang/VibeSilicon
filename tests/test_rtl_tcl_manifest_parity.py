"""Static Tcl parity rejects source, top and clock drift without executing Tcl."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.quality_gate.rtl_manifest import ManifestError
from scripts.quality_gate.rtl_tcl_manifest_parity import check_parity


class RtlTclManifestParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rtl = self.root / "project/demo/src"
        self.rtl.mkdir(parents=True)
        for name in ("top.v", "child.v", "tb.v"):
            (self.rtl / name).write_text(f"module {name[:-2]}; endmodule\n", encoding="utf-8")
        self.manifest = self.root / "project/demo/manifest.json"
        self.manifest.write_text(json.dumps({
            "schema_version": 2, "project_root": "project/demo", "target": "fpga",
            "source_kinds": ["handwritten"], "top": "top",
            "source_roots": ["project/demo/src"],
            "sources": ["project/demo/src/top.v", "project/demo/src/child.v"],
            "excluded_sources": {"project/demo/src/tb.v": "testbench"},
            "headers": [], "include_dirs": ["project/demo/src"],
            "defines": {}, "parameters": {}, "clocks": ["clk"], "resets": ["rst_n"],
        }), encoding="utf-8")
        self.tcl = self.rtl / "build.tcl"
        self.rtl_dir = "C:" + "/code/project/demo/src"
        self.content = (
            f'set RTL_DIR "{self.rtl_dir}"\n'
            'add_files [list \\\n'
            '    $RTL_DIR/top.v \\\n'
            '    $RTL_DIR/child.v \\\n'
            ']\n'
            'set_property top top [current_fileset]\n'
            'puts $fh "create_clock -name clk -period 4.000 \\[get_ports clk\\]"\n'
            'add_files -fileset constrs_1 $XDC_FILE\n'
        )

    def check(self):
        self.tcl.write_text(self.content, encoding="utf-8")
        return check_parity(self.manifest, "project/demo/src/build.tcl", repository_root=self.root)

    def test_exact_literal_configuration_passes(self):
        report = self.check()
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["selected_source_count"], 2)
        self.assertEqual(report["clock_period_ns"], {"clk": "4.000"})
        self.assertNotIn(str(self.root), str(report))

    def test_source_and_top_drift_block(self):
        self.content = self.content.replace("$RTL_DIR/child.v", "$RTL_DIR/tb.v")
        with self.assertRaisesRegex(ManifestError, "source list differs"):
            self.check()
        self.content = self.content.replace("$RTL_DIR/tb.v", "$RTL_DIR/child.v")
        self.content = self.content.replace("set_property top top", "set_property top child")
        with self.assertRaisesRegex(ManifestError, "top differs"):
            self.check()

    def test_clock_drift_and_unsupported_extra_command_block(self):
        self.content = self.content.replace("get_ports clk", "get_ports wrong")
        with self.assertRaisesRegex(ManifestError, "clocks differ"):
            self.check()
        self.content = self.content.replace("get_ports wrong", "get_ports clk")
        self.content += "add_files $RTL_DIR/extra.v\n"
        with self.assertRaisesRegex(ManifestError, "additional add_files"):
            self.check()

    def test_dynamic_list_and_source_root_drift_block(self):
        self.content = self.content.replace("$RTL_DIR/child.v", "[glob $RTL_DIR/*.v]")
        with self.assertRaisesRegex(ManifestError, "unsupported or unsafe"):
            self.check()
        self.content = self.content.replace("[glob $RTL_DIR/*.v]", "$RTL_DIR/child.v")
        self.content = self.content.replace(self.rtl_dir, "C:" + "/code/project/other/src")
        with self.assertRaisesRegex(ManifestError, "RTL_DIR"):
            self.check()


if __name__ == "__main__":
    unittest.main()
