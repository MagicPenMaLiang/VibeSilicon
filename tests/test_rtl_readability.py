import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT, load_module


readability = load_module(
    "vibesilicon_rtl_readability", "scripts/quality_gate/rtl_readability.py"
)


CONTRACT = """// VibeSilicon Module Contract v1
// Module      : readable_counter
// Purpose     : Exercise the deterministic readability gate.
// Clocks      : clk_i, 100 MHz, single domain.
// Resets      : rst_ni, asynchronous assert and synchronous release.
// Interfaces  : enable input and registered count output.
// Numeric     : unsigned 8-bit, wrap on overflow.
// Latency     : fixed 1 cycle.
// Throughput  : one update per cycle.
// Invariants  : count_q changes only on clk_i.
// Generated   : no
"""

CLEAN_RTL = CONTRACT + """
`default_nettype none
module readable_counter (
    input  logic       clk_i,
    input  logic       rst_ni,
    input  logic       enable_i,
    output logic [7:0] count_o
);
    logic [7:0] count_d;
    logic [7:0] count_q;

    always_comb begin
        count_d = count_q;
        if (enable_i) begin
            count_d = count_q + 8'd1;
        end
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) count_q <= 8'h00;
        else count_q <= count_d;
    end

    assign count_o = count_q;
endmodule
`default_nettype wire
"""

BROKEN_RTL = """module broken (
    input logic clk_a,
    input logic clk_b,
    input logic signed [7:0] signed_a,
    input logic [7:0] unsigned_b,
    output logic [7:0] latch_o
);
    logic [7:0] src_q;
    logic [7:0] dst_q;
    logic [7:0] shared_q;
    logic valid_s3_q;
    logic data_s1_q;
    (* DONT_TOUCH = "TRUE" *) logic preserved_q;
    assign undeclared_net = unsigned_b;

    always_comb begin
        if (unsigned_b[0]) latch_o = unsigned_b + 1;
        valid_s3_q = data_s1_q;
    end

    always_ff @(posedge clk_a) begin
        src_q <= unsigned_b;
        shared_q = signed_a + unsigned_b;
    end

    always_ff @(posedge clk_b) begin
        dst_q <= src_q;
        shared_q <= dst_q;
    end
endmodule
"""


class RtlReadabilityTests(unittest.TestCase):
    def analyze_text(self, text):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "design.sv"
            source.write_text(text, encoding="utf-8")
            return readability.analyze(source, root=Path(root))

    def test_clean_contract_passes_all_rules(self):
        report = self.analyze_text(CLEAN_RTL)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["summary"], {"violations": 0, "blocking": 0, "warnings": 0, "waived": 0})

    def test_parameterized_ranges_are_not_datapath_arithmetic(self):
        rtl = CLEAN_RTL.replace("[7:0]", "[WIDTH-1:0]")
        self.assertNotIn("RTL-R002", {item["rule_id"] for item in self.analyze_text(rtl)["violations"]})

    def test_declaration_range_exemption_does_not_hide_unsized_initializer(self):
        rtl = CLEAN_RTL.replace("logic [7:0] count_d;", "logic [WIDTH-1:0] count_d = count_q + 1;")
        self.assertIn("RTL-R002", {item["rule_id"] for item in self.analyze_text(rtl)["violations"]})

    def test_fault_fixture_exercises_all_ten_rules(self):
        report = self.analyze_text(BROKEN_RTL)
        rule_ids = {item["rule_id"] for item in report["violations"]}
        self.assertEqual(rule_ids, {f"RTL-R{number:03d}" for number in range(1, 11)})
        self.assertEqual(report["status"], "FAIL")
        self.assertGreaterEqual(report["summary"]["blocking"], 8)

    def test_valid_inline_waiver_is_auditable_and_non_blocking(self):
        rtl = CLEAN_RTL.replace(
            "    logic [7:0] count_d;",
            "    // vibesilicon-waive RTL-R010 id=WAIVER-123 reason=debug-review\n"
            "    (* MARK_DEBUG = \"TRUE\" *) logic [7:0] count_d;",
        )
        report = self.analyze_text(rtl)
        finding = next(item for item in report["violations"] if item["rule_id"] == "RTL-R010")
        self.assertTrue(finding["waived"])
        self.assertEqual(finding["waiver_id"], "WAIVER-123")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["summary"]["waived"], 1)

    def test_invalid_waiver_identifier_does_not_suppress_error(self):
        rtl = CLEAN_RTL.replace(
            "    logic [7:0] count_d;",
            "    // vibesilicon-waive RTL-R010 id=bad reason=not-approved\n"
            "    (* KEEP = \"TRUE\" *) logic [7:0] count_d;",
        )
        report = self.analyze_text(rtl)
        finding = next(item for item in report["violations"] if item["rule_id"] == "RTL-R010")
        self.assertFalse(finding["waived"])
        self.assertEqual(report["status"], "FAIL")

    def test_each_module_requires_its_own_contract(self):
        rtl = CLEAN_RTL + "\nmodule undocumented_second; endmodule\n"
        report = self.analyze_text(rtl)
        missing = [item for item in report["violations"] if item["rule_id"] == "RTL-R007"]
        self.assertEqual(len(missing), 1)

    def test_package_header_does_not_require_module_contract(self):
        rtl = """`default_nettype none
package readable_types;
    typedef logic [7:0] byte_t;
endpackage
`default_nettype wire
"""
        report = self.analyze_text(rtl)
        self.assertNotIn("RTL-R007", {item["rule_id"] for item in report["violations"]})

    def test_loop_indices_do_not_trigger_numeric_width_rule(self):
        rtl = CLEAN_RTL.replace(
            "    assign count_o = count_q;",
            "    integer index;\n"
            "    always_ff @(posedge clk_i) begin\n"
            "        for (index = 0; index < 8; index = index + 1) count_o[index] <= count_q[index];\n"
            "    end",
        )
        report = self.analyze_text(rtl)
        numeric = [item for item in report["violations"] if item["rule_id"] == "RTL-R002"]
        self.assertEqual(numeric, [])

    def test_loop_body_remains_subject_to_numeric_and_sequential_rules(self):
        rtl = CLEAN_RTL.replace(
            "    assign count_o = count_q;",
            "    integer index;\n"
            "    always_ff @(posedge clk_i) begin\n"
            "        for (index = 0; index < 8; index = index + 1) count_o[index] = count_q[index] + 1;\n"
            "    end",
        )
        report = self.analyze_text(rtl)
        rules = {item["rule_id"] for item in report["violations"]}
        self.assertIn("RTL-R002", rules)
        self.assertIn("RTL-R005", rules)

    def test_contract_template_placeholders_do_not_count_as_completed(self):
        template = (ROOT / "templates/rtl/module_contract.sv.tpl").read_text(encoding="utf-8")
        report = self.analyze_text(template)
        self.assertIn("RTL-R007", {item["rule_id"] for item in report["violations"]})

    def test_async_reg_destination_is_an_approved_cdc_boundary(self):
        rtl = CONTRACT.replace("readable_counter", "cdc_boundary") + """
`default_nettype none
module cdc_boundary (input logic clk_a, input logic clk_b, input logic data_i);
    logic source_q;
    (* ASYNC_REG = "TRUE" *) logic sync_q;
    always_ff @(posedge clk_a) source_q <= data_i;
    always_ff @(posedge clk_b) sync_q <= source_q;
endmodule
`default_nettype wire
"""
        report = self.analyze_text(rtl)
        self.assertNotIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_sync_like_name_without_attribute_does_not_bypass_cdc(self):
        rtl = CONTRACT.replace("readable_counter", "unsafe_cdc") + """
`default_nettype none
module unsafe_cdc (input logic clk_a, input logic clk_b, input logic data_i);
    logic source_q;
    logic looks_synced_q;
    always_ff @(posedge clk_a) source_q <= data_i;
    always_ff @(posedge clk_b) looks_synced_q <= source_q;
endmodule
`default_nettype wire
"""
        report = self.analyze_text(rtl)
        self.assertIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    HELD_DATA_PRELUDE = """
`default_nettype none
module held_data_cdc (
    input  logic       clk_a,
    input  logic       clk_b,
    input  logic       aresetn_dst,
    input  logic       data_i,
    input  logic       stats_valid,
    output logic [7:0] dst_o
);
    logic [7:0] src_q;
    logic       stats_valid_sync;
    logic       stats_valid_rise;
    logic [7:0] dst_q;
    logic [7:0] other_q;

    always_ff @(posedge clk_a) src_q <= {7'd0, data_i};

    cdc_sync u_sval (
        .clk_dst    (clk_b),
        .aresetn_dst(aresetn_dst),
        .d_async    (stats_valid),
        .q_sync     (stats_valid_sync),
        .rise_pulse (stats_valid_rise)
    );
"""

    def analyze_held_data(self, body):
        rtl = self.HELD_DATA_PRELUDE + body + """
    assign dst_o = dst_q;
endmodule
`default_nettype wire
"""
        return self.analyze_text(rtl)

    def test_held_data_gated_by_synchronizer_enable_is_approved(self):
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        if (!aresetn_dst) begin
            dst_q <= 8'd0;
        end else if (stats_valid_rise) begin
            dst_q <= src_q;
        end
    end
""")
        self.assertNotIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_held_data_without_the_enable_is_still_a_violation(self):
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        dst_q <= src_q;
    end
""")
        self.assertIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_enable_low_branch_is_not_gated(self):
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        if (stats_valid_rise) begin
            dst_q <= 8'd0;
        end else begin
            dst_q <= src_q;
        end
    end
""")
        self.assertIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_enable_from_a_plain_register_does_not_approve_the_crossing(self):
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        other_q <= src_q;
    end

    always_ff @(posedge clk_b) begin
        if (other_q[0]) begin
            dst_q <= src_q;
        end
    end
""")
        self.assertIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_synchronized_level_from_q_sync_also_counts_as_an_enable(self):
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        if (stats_valid_sync) begin
            dst_q <= src_q;
        end
    end
""")
        self.assertNotIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_synchronizer_input_signal_does_not_count_as_an_enable(self):
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        if (stats_valid) begin
            dst_q <= src_q;
        end
    end
""")
        self.assertIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_negated_enable_does_not_approve_the_crossing(self):
        """`if (!enable)` captures while the enable is LOW -- the opposite of
        the approved pattern. Name-matching alone would wrongly approve it."""
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        if (!stats_valid_rise) begin
            dst_q <= src_q;
        end
    end
""")
        self.assertIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_bitwise_negated_enable_does_not_approve_the_crossing(self):
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        if (~stats_valid_rise) begin
            dst_q <= src_q;
        end
    end
""")
        self.assertIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_or_with_an_unrelated_term_does_not_approve_the_crossing(self):
        """`enable || other` runs when `other` is true and the enable is low."""
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        if (stats_valid_rise || other_q[0]) begin
            dst_q <= src_q;
        end
    end
""")
        self.assertIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_enable_anded_with_another_term_still_approves(self):
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        if (stats_valid_rise && other_q[0]) begin
            dst_q <= src_q;
        end
    end
""")
        self.assertNotIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_or_group_anded_with_the_enable_still_approves(self):
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        if ((other_q[0] || aresetn_dst) && stats_valid_rise) begin
            dst_q <= src_q;
        end
    end
""")
        self.assertNotIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_enable_inside_an_or_group_under_and_does_not_approve(self):
        """`(enable || other) && aresetn_dst` is satisfiable with enable low."""
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        if ((stats_valid_rise || other_q[0]) && aresetn_dst) begin
            dst_q <= src_q;
        end
    end
""")
        self.assertIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_wholly_negated_condition_does_not_approve(self):
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        if (!(stats_valid_rise && other_q[0])) begin
            dst_q <= src_q;
        end
    end
""")
        self.assertIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_equality_comparison_against_the_enable_is_conservatively_rejected(self):
        """`if (enable == 1'b1)` is a gating form the analyzer does not
        recognise. It must fail closed, not open."""
        report = self.analyze_held_data("""
    always_ff @(posedge clk_b) begin
        if (stats_valid_rise == 1'b1) begin
            dst_q <= src_q;
        end
    end
""")
        self.assertIn("RTL-R009", {item["rule_id"] for item in report["violations"]})

    def test_comments_do_not_satisfy_or_trigger_code_rules(self):
        rtl = CLEAN_RTL.replace("`default_nettype none", "// `default_nettype none")
        rtl = rtl.replace("    logic [7:0] count_d;", "    // DONT_TOUCH is intentionally not used.\n    logic [7:0] count_d;")
        report = self.analyze_text(rtl)
        rules = [item["rule_id"] for item in report["violations"]]
        self.assertIn("RTL-R001", rules)
        self.assertNotIn("RTL-R010", rules)

    def test_default_nettype_must_be_restored_at_file_end(self):
        rtl = CLEAN_RTL.replace("`default_nettype wire", "")
        report = self.analyze_text(rtl)
        nettype = [item for item in report["violations"] if item["rule_id"] == "RTL-R001"]
        self.assertEqual(len(nettype), 1)
        self.assertIn("restore", nettype[0]["evidence"])

    def test_report_and_schema_are_versioned_json(self):
        schema = json.loads((ROOT / "schemas/rtl_readability.schema.json").read_text(encoding="utf-8"))
        report = self.analyze_text(CLEAN_RTL)
        self.assertEqual(schema["properties"]["schema_version"]["const"], 1)
        self.assertEqual(report["schema_version"], 1)
        # The ruleset version is bound to the module's constant rather than a
        # literal, so a rule-acceptance change cannot land in one place and be
        # forgotten in the other.
        self.assertEqual(schema["properties"]["ruleset_version"]["const"], readability.RULESET_VERSION)
        self.assertEqual(report["ruleset_version"], readability.RULESET_VERSION)
        self.assertEqual(set(report), set(schema["required"]))

    def test_cli_writes_fail_report_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            source = root_path / "broken.sv"
            output = root_path / "rtl_readability.json"
            source.write_text(BROKEN_RTL, encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/quality_gate/rtl_readability.py"),
                    str(source),
                    "--root",
                    str(root_path),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(report["status"], "FAIL")

    def test_non_rtl_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "design.txt"
            source.write_text("module nope; endmodule\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "only accepts"):
                readability.analyze(source, root=Path(root))


if __name__ == "__main__":
    unittest.main()
