"""The include closure must bind exactly the files the preprocessor would read."""

import tempfile
import unittest
from pathlib import Path

from scripts.quality_gate.rtl_include_closure import include_closure
from scripts.quality_gate.rtl_manifest import ManifestError


class IncludeClosureTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name).resolve()
        self.addCleanup(self._directory.cleanup)
        (self.root / "rtl").mkdir()

    def _write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def _closure(self, entry, *, defines=None):
        return include_closure(
            root=self.root,
            entries=[self.root / entry],
            include_dirs=[self.root / "rtl"],
            defines=defines or {},
        )

    def test_quoted_include_is_resolved(self):
        self._write("rtl/model.sv", "module model; endmodule\n")
        self._write("tb/tb.sv", 'module tb;\n`include "model.sv"\nendmodule\n')
        self.assertEqual(list(self._closure("tb/tb.sv")), ["rtl/model.sv"])

    def test_angle_include_is_resolved(self):
        self._write("rtl/model.sv", "module model; endmodule\n")
        self._write("tb/tb.sv", 'module tb;\n`include <model.sv>\nendmodule\n')
        self.assertEqual(list(self._closure("tb/tb.sv")), ["rtl/model.sv"])

    def test_nested_include_is_followed(self):
        self._write("rtl/inner.sv", "module inner; endmodule\n")
        self._write("rtl/middle.sv", '`include "inner.sv"\n')
        self._write("tb/tb.sv", '`include "middle.sv"\n')
        self.assertEqual(sorted(self._closure("tb/tb.sv")), ["rtl/inner.sv", "rtl/middle.sv"])

    def test_include_in_disabled_branch_is_not_an_input(self):
        self._write("rtl/optional.sv", "module optional; endmodule\n")
        self._write("tb/tb.sv", '`ifdef USE_OPTIONAL\n`include "optional.sv"\n`endif\n')
        self.assertEqual(self._closure("tb/tb.sv"), {})
        self.assertEqual(list(self._closure("tb/tb.sv", defines={"USE_OPTIONAL": "1"})),
                         ["rtl/optional.sv"])

    def test_ifndef_and_else_select_the_right_branch(self):
        self._write("rtl/a.sv", "")
        self._write("rtl/b.sv", "")
        text = '`ifndef MACRO\n`include "a.sv"\n`else\n`include "b.sv"\n`endif\n'
        self._write("tb/tb.sv", text)
        self.assertEqual(list(self._closure("tb/tb.sv")), ["rtl/a.sv"])
        self.assertEqual(list(self._closure("tb/tb.sv", defines={"MACRO": "1"})), ["rtl/b.sv"])

    def test_commented_include_is_ignored(self):
        self._write("tb/tb.sv", '// `include "ghost.sv"\n/* `include "ghost2.sv" */\n')
        self.assertEqual(self._closure("tb/tb.sv"), {})

    def test_unresolved_include_is_an_error_not_a_silent_omission(self):
        self._write("tb/tb.sv", '`include "missing.sv"\n')
        with self.assertRaisesRegex(ManifestError, "unresolved include"):
            self._closure("tb/tb.sv")

    def test_include_escaping_the_repository_is_rejected(self):
        outside = self.root.parent / "outside.sv"
        outside.write_text("module outside; endmodule\n", encoding="utf-8")
        self.addCleanup(outside.unlink)
        self._write("rtl/tb.sv", '`include "../../outside.sv"\n')
        with self.assertRaisesRegex(ManifestError, "escapes repository"):
            self._closure("rtl/tb.sv")

    def test_unbalanced_conditional_is_rejected(self):
        self._write("tb/tb.sv", "`ifdef SOMETHING\n")
        with self.assertRaisesRegex(ManifestError, "unterminated conditional"):
            self._closure("tb/tb.sv")

    def test_non_literal_include_is_rejected(self):
        self._write("tb/tb.sv", "`include `SOMETHING\n")
        with self.assertRaisesRegex(ManifestError, "non-literal include"):
            self._closure("tb/tb.sv")

    def test_repeated_include_across_entries_is_hashed_once(self):
        self._write("rtl/model.sv", "module model; endmodule\n")
        self._write("tb/one.sv", '`include "model.sv"\n')
        self._write("tb/two.sv", '`include "model.sv"\n')
        closure = include_closure(
            root=self.root,
            entries=[self.root / "tb/one.sv", self.root / "tb/two.sv"],
            include_dirs=[self.root / "rtl"],
            defines={},
        )
        self.assertEqual(list(closure), ["rtl/model.sv"])

    def test_included_macro_enables_following_include(self):
        self._write("rtl/flags.svh", "`define ENABLE_MODEL\n")
        self._write("rtl/model.sv", "")
        self._write("tb/tb.sv", '`include "flags.svh"\n`ifdef ENABLE_MODEL\n'
                    '`include "model.sv"\n`endif\n')
        self.assertEqual(sorted(self._closure("tb/tb.sv")), ["rtl/flags.svh", "rtl/model.sv"])

    def test_entry_order_and_macro_state_are_preserved(self):
        first = self._write("rtl/first.sv", "`define ENABLE_MODEL\n")
        second = self._write("rtl/second.sv", '`ifdef ENABLE_MODEL\n`include "model.sv"\n`endif\n')
        self._write("rtl/model.sv", "")
        self.assertEqual(list(include_closure(root=self.root, entries=[first, second],
                                             include_dirs=[self.root / "rtl"])), ["rtl/model.sv"])
        self.assertEqual(include_closure(root=self.root, entries=[second, first],
                                         include_dirs=[self.root / "rtl"]), {})

    def test_repeated_header_is_reprocessed_after_macro_change(self):
        self._write("rtl/select.svh", '`ifdef SELECT\n`include "selected.sv"\n`endif\n')
        self._write("rtl/selected.sv", "")
        self._write("tb/tb.sv", '`include "select.svh"\n`define SELECT\n`include "select.svh"\n')
        self.assertEqual(sorted(self._closure("tb/tb.sv")), ["rtl/select.svh", "rtl/selected.sv"])

    def test_include_guards_terminate_cycles_and_unguarded_cycles_block(self):
        self._write("rtl/a.svh", '`ifndef A_GUARD\n`define A_GUARD\n`include "b.svh"\n`endif\n')
        self._write("rtl/b.svh", '`include "a.svh"\n')
        self._write("tb/tb.sv", '`include "a.svh"\n')
        self.assertEqual(sorted(self._closure("tb/tb.sv")), ["rtl/a.svh", "rtl/b.svh"])
        self._write("rtl/a.svh", '`include "b.svh"\n')
        with self.assertRaisesRegex(ManifestError, "expansion limit"):
            self._closure("tb/tb.sv")

    def test_included_undefineall_affects_following_conditions(self):
        self._write("rtl/clear.svh", "`undefineall\n")
        self._write("rtl/fallback.sv", "")
        self._write("tb/tb.sv", '`include "clear.svh"\n`ifndef ENABLED\n'
                    '`include "fallback.sv"\n`endif\n')
        self.assertIn("rtl/fallback.sv", self._closure("tb/tb.sv", defines={"ENABLED": "1"}))


if __name__ == "__main__":
    unittest.main()
