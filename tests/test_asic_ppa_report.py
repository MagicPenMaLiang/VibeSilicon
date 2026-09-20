import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts import asic_ppa_report as ppa


HASH = "sha256:" + "a" * 64


class AsicPpaReportTests(unittest.TestCase):
    def write(self, root, name, text):
        path = Path(root) / name
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def digest(self, path):
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    def content(self, value, field="evidence_id"):
        value[field] = ppa._content_id(value, field)
        return value

    def evidence(self, root, *, physical=False):
        liberty = self.write(root, "corner.lib", "library(test) {}\n")
        netlist = self.write(root, "netlist.v", "module top; endmodule\n")
        sdc = self.write(root, "design.sdc", "create_clock -period 10 [get_ports clk]\n")
        spef = self.write(root, "final.spef", "*SPEF IEEE 1481-1998\n")
        activity = self.write(root, "activity.vcd", "$date today $end\n")
        a01 = self.content({
            "status": "A01_INPUTS_VERIFIED_UNEXECUTED", "evidence_id": "",
            "pdk": {"corner": {
                "name": "tt_025C_1v80", "process": "typical", "voltage_v": 1.8,
                "temperature_c": 25.0, "liberty_sha256": self.digest(liberty),
                "rc_tech_sha256": HASH,
            }},
            "design": {"constraints_sha256": self.digest(sdc)},
        })
        a02 = self.content({
            "status": "A02_SYNTH_STA_COMPLETE", "evidence_id": "",
            "input_evidence_id": a01["evidence_id"],
            "metrics": {"cell_count": 12, "synth_cell_area_um2": 100.0,
                        "standard_cell_area_um2": 101.0, "wns_ns": 0.2,
                        "tns_ns": 0.0, "timing_met": True},
            "tools": [{"name": "yosys", "version": "0.69", "binary_sha256": HASH},
                      {"name": "openroad", "version": "2.0", "binary_sha256": HASH}],
            "artifacts": [{"role": "netlist", "sha256": self.digest(netlist),
                           "bytes": netlist.stat().st_size}],
        })
        a03 = None
        if physical:
            postroute = self.write(root, "postroute.v", "module top; wire routed; endmodule\n")
            a03 = self.content({
                "status": "A03_PHYSICAL_RUN_COMPLETE", "evidence_id": "",
                "input_evidence_id": a01["evidence_id"], "a02_evidence_id": a02["evidence_id"],
                "metrics": {"standard_cell_area_um2": 120.0, "wns_ns": -0.1,
                            "tns_ns": -0.4, "timing_met": False},
                "tools": [{"name": "openroad", "version": "2.0", "binary_sha256": HASH}],
                "artifacts": [
                    {"role": "postroute_netlist", "sha256": self.digest(postroute),
                     "bytes": postroute.stat().st_size},
                    {"role": "spef", "sha256": self.digest(spef), "bytes": spef.stat().st_size},
                ],
            })
            netlist = postroute
        script = self.write(root, "power.tcl", ppa.render_plan(
            top="top", liberty=liberty, netlist=netlist, sdc=sdc,
            mode="VCD", activity_file=activity, scope="tb/dut",
            spef=spef if physical else None, default_activity=None,
            default_duty=None,
        ))
        return a01, a02, a03, liberty, netlist, sdc, spef, activity, script

    def report_text(self, *, plan_id, liberty, netlist, sdc, mode="VCD", activity=None,
                    scope="tb/dut", spef=None, annotated=17, default_activity=0.1,
                    default_duty=0.5):
        lines = [
            f"VIBESILICON_POWER_PLAN_ID={plan_id}",
            f"VIBESILICON_LIBERTY_SHA256={self.digest(liberty)}",
            f"VIBESILICON_NETLIST_SHA256={self.digest(netlist)}",
            f"VIBESILICON_SDC_SHA256={self.digest(sdc)}",
            f"VIBESILICON_ACTIVITY_MODE={mode}",
        ]
        if spef:
            lines.append(f"VIBESILICON_SPEF_SHA256={self.digest(spef)}")
        if mode in {"VCD", "SAIF"}:
            lines.extend([
                f"VIBESILICON_ACTIVITY_SOURCE_SHA256={self.digest(activity)}",
                f"VIBESILICON_ACTIVITY_SCOPE={scope}",
                f"Annotated {annotated} pin activities.",
            ])
        else:
            lines.extend([
                f"VIBESILICON_DEFAULT_ACTIVITY={default_activity}",
                f"VIBESILICON_DEFAULT_DUTY={default_duty}",
            ])
        lines.extend([
            "VIBESILICON_POWER_REPORT_BEGIN", "Power (Watts)",
            "Total 1.0e-3 2.0e-3 3.0e-4 3.3e-3 100.0%",
            "VIBESILICON_POWER_REPORT_END",
        ])
        return "\n".join(lines) + "\n"

    def build(self, root, *, physical=False, mode="VCD", annotated=17):
        values = self.evidence(root, physical=physical)
        a01, a02, a03, liberty, netlist, sdc, spef, activity, script = values
        if mode == "ESTIMATED":
            script.write_text(ppa.render_plan(
                top="top", liberty=liberty, netlist=netlist, sdc=sdc,
                mode=mode, activity_file=None, scope=None,
                spef=spef if physical else None, default_activity=0.1,
                default_duty=0.5,
            ), encoding="utf-8", newline="\n")
        plan_id = ppa._script_marker(script.read_text(encoding="utf-8"), "VIBESILICON_POWER_PLAN_ID")
        report = self.write(root, "power.log", self.report_text(
            plan_id=plan_id, liberty=liberty, netlist=netlist, sdc=sdc, mode=mode,
            activity=activity, spef=spef if physical else None, annotated=annotated,
        ))
        result = ppa.build_report(
            input_evidence=a01, a02_evidence=a02, a03_evidence=a03,
            power_script=script, power_report=report, activity_mode=mode,
            activity_file=activity if mode != "ESTIMATED" else None,
            activity_scope="tb/dut" if mode != "ESTIMATED" else None,
            spef=spef if physical else None,
            default_activity=0.1 if mode == "ESTIMATED" else None,
            default_duty=0.5 if mode == "ESTIMATED" else None,
        )
        return result, values

    def test_vector_backed_post_synthesis_report_has_complete_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            report, _ = self.build(directory)
        self.assertEqual(report["result_status"], "VECTOR_BACKED_TIMING_MET")
        self.assertEqual(report["stage"], "POST_SYNTHESIS")
        self.assertEqual(report["activity"]["annotated_pin_count"], 17)
        self.assertEqual(report["power"]["total_w"], 0.0033)
        self.assertTrue(report["complete_dimensions"])
        self.assertEqual(report["signoff_status"], "NOT_SIGNOFF")

    def test_estimated_activity_is_never_vector_backed(self):
        with tempfile.TemporaryDirectory() as directory:
            report, _ = self.build(directory, mode="ESTIMATED")
        self.assertEqual(report["result_status"], "ESTIMATED_TIMING_MET")
        self.assertEqual(report["activity"]["confidence"], "DEFAULT_ACTIVITY_ESTIMATE")
        self.assertIsNone(report["activity"]["source_sha256"])

    def test_post_route_report_uses_a03_timing_area_and_spef(self):
        with tempfile.TemporaryDirectory() as directory:
            report, _ = self.build(directory, physical=True)
        self.assertEqual(report["stage"], "POST_ROUTE")
        self.assertEqual(report["result_status"], "VECTOR_BACKED_TIMING_VIOLATION")
        self.assertEqual(report["area"]["standard_cell_area_um2"], 120.0)
        self.assertEqual(report["performance"]["wns_ns"], -0.1)
        self.assertEqual([item["role"] for item in report["artifacts"]],
                         ["power_script", "power_report", "spef", "activity"])

    def test_zero_vector_annotation_and_tampered_upstream_block(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ppa.AsicPpaError, "nonzero pin count"):
                self.build(directory, annotated=0)
        with tempfile.TemporaryDirectory() as directory:
            values = self.evidence(directory)
            a01, a02, _, liberty, netlist, sdc, _, activity, script = values
            a02["metrics"]["cell_count"] = 999
            report = self.write(directory, "power.log", self.report_text(
                plan_id=ppa._script_marker(
                    script.read_text(encoding="utf-8"), "VIBESILICON_POWER_PLAN_ID"
                ),
                liberty=liberty, netlist=netlist, sdc=sdc, activity=activity,
            ))
            with self.assertRaisesRegex(ppa.AsicPpaError, "content ID mismatch"):
                ppa.build_report(
                    input_evidence=a01, a02_evidence=a02, a03_evidence=None,
                    power_script=script, power_report=report, activity_mode="VCD",
                    activity_file=activity, activity_scope="tb/dut", spef=None,
                    default_activity=None, default_duty=None,
                )

    def test_power_total_and_report_content_id_tampering_block(self):
        with tempfile.TemporaryDirectory() as directory:
            report, _ = self.build(directory)
            changed = copy.deepcopy(report)
            changed["power"]["total_w"] = 1.0
            changed["report_id"] = ppa._content_id(changed, "report_id")
            with self.assertRaisesRegex(ppa.AsicPpaError, "power metrics"):
                ppa.verify_report(changed)
            report["area"]["cell_count"] += 1
            with self.assertRaisesRegex(ppa.AsicPpaError, "content ID mismatch"):
                ppa.verify_report(report)

    def test_fixed_plan_uses_activity_and_no_free_source_command(self):
        with tempfile.TemporaryDirectory() as directory:
            values = self.evidence(directory)
            _, _, _, liberty, netlist, sdc, spef, activity, _ = values
            plan = ppa.render_plan(
                top="top", liberty=liberty, netlist=netlist, sdc=sdc,
                mode="VCD", activity_file=activity, scope="tb/dut", spef=spef,
                default_activity=None, default_duty=None,
            )
        self.assertIn("read_vcd -scope tb/dut", plan)
        self.assertIn("VIBESILICON_POWER_PLAN_ID=sha256:", plan)
        self.assertIn("read_spef", plan)
        self.assertIn("report_power", plan)
        self.assertNotIn("source ", plan)
        self.assertNotIn("exec ", plan)
        with tempfile.TemporaryDirectory() as directory:
            values = self.evidence(directory)
            _, _, _, liberty, netlist, sdc, _, activity, _ = values
            with self.assertRaisesRegex(ppa.AsicPpaError, "safe scope"):
                ppa.render_plan(
                    top="top", liberty=liberty, netlist=netlist, sdc=sdc,
                    mode="VCD", activity_file=activity, scope="tb/[exit]",
                    spef=None, default_activity=None, default_duty=None,
                )

    def test_report_must_be_bound_to_supplied_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            values = self.evidence(directory)
            a01, a02, _, liberty, netlist, sdc, _, activity, script = values
            report = self.write(directory, "power.log", self.report_text(
                plan_id="sha256:" + "b" * 64,
                liberty=liberty, netlist=netlist, sdc=sdc, activity=activity,
            ))
            with self.assertRaisesRegex(ppa.AsicPpaError, "not bound"):
                ppa.build_report(
                    input_evidence=a01, a02_evidence=a02, a03_evidence=None,
                    power_script=script, power_report=report, activity_mode="VCD",
                    activity_file=activity, activity_scope="tb/dut", spef=None,
                    default_activity=None, default_duty=None,
                )

    def test_schema_is_versioned_and_declares_plan_binding(self):
        schema_path = Path(__file__).parents[1] / "schemas" / "asic_ppa_report.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertIn("power_plan_id", schema["required"])

    def test_markdown_is_sanitized_and_verifiable(self):
        with tempfile.TemporaryDirectory() as directory:
            report, _ = self.build(directory)
            text = ppa.markdown(report)
            self.assertNotIn(directory, text)
        self.assertIn("ASIC PPA Report", text)
        self.assertIn("NOT_SIGNOFF", text)


if __name__ == "__main__":
    unittest.main()
