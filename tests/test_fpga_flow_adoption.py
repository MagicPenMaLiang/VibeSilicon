import asyncio
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import ValidationError

from scripts.evidence_contract import sha256_bytes
from scripts.fpga_feasibility import assess
from scripts.hls_reports import analyze_csynth, parse_csynth
from scripts.vivado_opt_analysis import analyze_opt_log
from tests.support import ROOT, load_module


HLS_XML = b"""<profile><ReportVersion><Version>2024.2</Version></ReportVersion>
<UserAssignments><unit>ns</unit><TopModelName>neutral</TopModelName><Part>xc7a35tcpg236-1</Part>
<TargetClockPeriod>10</TargetClockPeriod><FlowTarget>vivado</FlowTarget></UserAssignments>
<PerformanceEstimates><SummaryOfTimingAnalysis><unit>ns</unit><EstimatedClockPeriod>8.5</EstimatedClockPeriod>
</SummaryOfTimingAnalysis><SummaryOfOverallLatency><unit>clock cycles</unit><Best-caseLatency>4</Best-caseLatency>
<Worst-caseLatency>12</Worst-caseLatency><Interval-min>1</Interval-min><Interval-max>9</Interval-max>
</SummaryOfOverallLatency><SummaryOfLoopLatency><pixel_loop><PipelineII>2</PipelineII><PipelineDepth>4</PipelineDepth>
</pixel_loop></SummaryOfLoopLatency></PerformanceEstimates><AreaEstimates><Resources><DSP>0</DSP><LUT>42</LUT>
</Resources></AreaEstimates></profile>"""


def planning_contract(root):
    bindings = []
    for role in ("numeric_contract", "golden_model", "test_vectors"):
        path = root / f"{role}.json"
        path.write_text("{}", encoding="utf-8")
        bindings.append({"role": role, "path": path.name, "sha256": sha256_bytes(path.read_bytes())})
    return {
        "schema_version": 1, "target_flow": "fpga", "implementation": "rtl", "device_part": "xc7a35tcpg236-1",
        "bindings": bindings,
        "workload": {"item_unit": "sample", "clock_hz": 100_000_000, "required_items_per_second": 40_000_000,
                     "items_per_initiation": 2, "initiation_interval_cycles": 4, "sustained_fraction": 0.8,
                     "latency_cycles": 20, "max_latency_seconds": 0.000001},
        "resources": [{"name": "LUT", "estimated": 100, "budget": 1000}],
        "memories": [{"name": "line", "width_bits": 16, "depth": 32, "copies": 2, "budget_bits": 1024}],
        "external_memory": {"bytes_per_item": 8, "available_bytes_per_second": 320_000_000},
    }


class FeasibilityTests(unittest.TestCase):
    def test_candidate_is_not_acceptance_and_includes_interval_stalls_and_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = planning_contract(root)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            result = assess(root, contract)
            self.assertEqual(result["status"], "CANDIDATE")
            self.assertEqual(result["acceptance"], "NOT_EVALUATED")
            self.assertFalse(result["hardware_validated"])
            self.assertEqual(result["sustained_items_per_second"], 40_000_000)
            memory = next(row for row in result["checks"] if row["metric"] == "memory_bits.line")
            self.assertEqual(memory["demand"], 1024)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
            self.assertEqual(assess(root, contract)["evidence_id"], result["evidence_id"])

    def test_each_budget_can_reject_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = planning_contract(root)
            for group, key, value in (("workload", "required_items_per_second", 40_000_001),
                                      ("workload", "latency_cycles", 101),
                                      ("external_memory", "available_bytes_per_second", 319_999_999),
                                      ("resources", "estimated", 1001), ("memories", "copies", 3)):
                contract = copy.deepcopy(baseline)
                target = contract[group][0] if isinstance(contract[group], list) else contract[group]
                target[key] = value
                with self.subTest(group=group, key=key):
                    self.assertEqual(assess(root, contract)["status"], "REJECTED")

    def test_arithmetic_planning_does_not_require_an_amd_device_or_hls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = planning_contract(root)
            contract["device_part"] = "LFE5U-85F-6BG381C"
            result = assess(root, contract)
            self.assertEqual(result["status"], "CANDIDATE")
            self.assertEqual(result["implementation"], "rtl")

    def test_hash_tamper_and_traversal_are_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = planning_contract(root)
            (root / "golden_model.json").write_text("changed")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                assess(root, contract)
            contract["bindings"][0]["path"] = "../outside.json"
            with self.assertRaises(ValueError):
                assess(root, contract)

    def test_missing_inputs_and_asic_do_not_acquire_fpga_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = planning_contract(root)
            for field, value in (("target_flow", "asic"), ("bindings", baseline["bindings"][:2]),
                                 ("resources", []), ("implementation", "unknown")):
                contract = copy.deepcopy(baseline)
                contract[field] = value
                with self.subTest(field=field), self.assertRaises(ValidationError):
                    assess(root, contract)

    def test_invalid_numbers_and_duplicate_allocations_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = planning_contract(root)
            for field, value in (("clock_hz", 0), ("clock_hz", True), ("clock_hz", float("inf")),
                                 ("sustained_fraction", 1.1), ("initiation_interval_cycles", 0)):
                contract = copy.deepcopy(baseline)
                contract["workload"][field] = value
                with self.subTest(field=field, value=value), self.assertRaises((ValueError, ValidationError)):
                    assess(root, contract)
            contract = copy.deepcopy(baseline)
            contract["memories"] *= 2
            with self.assertRaisesRegex(ValueError, "duplicate"):
                assess(root, contract)
            baseline["bindings"][2] = baseline["bindings"][0]
            with self.assertRaisesRegex(ValueError, "one numeric"):
                assess(root, baseline)

    def test_cli_rejects_unfilled_template(self):
        result = subprocess.run([sys.executable, "-m", "scripts.fpga_feasibility",
                                 "templates/fpga_feasibility.json.tpl"], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "BLOCKED")


class OptLogTests(unittest.TestCase):
    def read(self, root, content):
        (root / "run.log").write_text(content, encoding="utf-8")
        return analyze_opt_log(root, "run.log")

    def test_phase_scope_excludes_link_place_and_route_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.read(root, "Command: link_design\n[Opt 31-138] LINK\nCommand: opt_design -debug_log\n"
                               "Phase 2 Sweep\n[Opt 31-55] DONT_TOUCH cell_a\nopt_design completed successfully\n"
                               "opt_design: Time (s): cpu = 1\nCommand: place_design\n[Opt 31-138] PLACE\n")
            run = result["runs"][0]
            self.assertEqual(result["status"], "COLLECTED")
            self.assertEqual(run["start_line"], 3)
            self.assertEqual(run["excerpts"][1]["line"], 5)
            self.assertTrue(run["completion_marker"])
            self.assertNotIn("LINK", str(run))
            self.assertNotIn("PLACE", str(run))
            self.assertEqual(result["acceptance"], "NOT_EVALUATED")

    def test_incomplete_run_and_repeated_runs_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = self.read(root, "Command: opt_design\nERROR: failed\nCommand: place_design\n"
                               "[Opt 31-138] not opt\nCommand: opt_design\n[Opt 31-49] retarget\nopt_design: Time\n")
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(len(result["runs"]), 2)
            self.assertTrue(result["runs"][0]["error_seen"])
            self.assertFalse(result["runs"][0]["complete"])
            self.assertTrue(result["runs"][1]["complete"])
            self.assertNotIn("not opt", str(result["runs"]))

    def test_empty_scope_is_blocked_and_diagnostics_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(self.read(root, "[Opt 31-138] outside\n")["status"], "BLOCKED")
            result = self.read(root, "Command: opt_design\n" + "[Opt 31-55] cell\n" * 100 + "opt_design: Time\n")
            self.assertTrue(result["runs"][0]["excerpts_truncated"])
            self.assertEqual(len(result["runs"][0]["excerpts"]), 80)

    def test_root_escape_and_oversized_logs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project"
            root.mkdir()
            (root.parent / "outside.log").write_text("log")
            with self.assertRaises(ValueError):
                analyze_opt_log(root, "../outside.log")
            (root / "run.log").write_text("123456")
            with patch("scripts.vivado_opt_analysis.MAX_LOG_BYTES", 5), self.assertRaises(ValueError):
                analyze_opt_log(root, "run.log")

    def test_mcp_analysis_never_starts_vivado(self):
        vivado = load_module("adoption_vivado", "mcp/vivado-mcp/server.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.read(root, "Command: opt_design\nopt_design: Time\n")
            with patch.object(vivado, "PROJECT_ROOT", root), patch.object(vivado, "_run_vivado") as run:
                result = asyncio.run(vivado.call_tool("analyze_opt_log", {"log_path": "run.log"}))
                self.assertEqual(json.loads(result[0].text)["status"], "COLLECTED")
                invalid = asyncio.run(vivado.call_tool("analyze_opt_log", {"log_path": "run.log", "tcl": "exit"}))
                self.assertIn("accepts only", invalid[0].text)
                run.assert_not_called()


class OptionalHlsReportTests(unittest.TestCase):
    def test_estimates_and_loop_ii_stay_separate_with_missing_values(self):
        result = parse_csynth(HLS_XML)
        self.assertEqual(result["metrics"]["estimated_clock_ns"], 8.5)
        self.assertEqual(result["metrics"]["interval_max_cycles"], 9)
        self.assertEqual(result["loops"][0]["pipeline_ii"], 2)
        self.assertEqual(result["resources"]["DSP"], 0)
        self.assertIsNone(result["resources"]["URAM"])
        self.assertIn("resources.URAM", result["missing_metrics"])

    def test_unknown_and_nonfinite_fields_are_not_zero(self):
        for replacement in (b"undef", b"-", b"NaN", b"inf", b"-1"):
            with self.subTest(replacement=replacement):
                result = parse_csynth(HLS_XML.replace(b">8.5<", b">" + replacement + b"<"))
                self.assertIsNone(result["metrics"]["estimated_clock_ns"])
        result = parse_csynth(HLS_XML.replace(b"<unit>ns</unit>", b"<unit>ps</unit>"))
        self.assertIsNone(result["metrics"]["target_clock_ns"])

    def test_unsafe_ambiguous_or_unsupported_layout_rejected(self):
        for document in (b'<!DOCTYPE profile [<!ENTITY a "42">]>' + HLS_XML, b"<other/>",
                         HLS_XML.replace(b"<Part>", b"<Part>extra</Part><Part>"),
                         HLS_XML.replace(b">12<", b">2<")):
            with self.subTest(document=document[:60]), self.assertRaises(ValueError):
                parse_csynth(document)

    def test_reader_preserves_pipeline_info_lines_and_source_uncertainty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "csynth.xml").write_bytes(HLS_XML)
            (root / "compile.log").write_text("INFO: Pipelining loop 'pixel_loop'\nWARNING: port conflict\n"
                                             "INFO: Pipelining result: Target II=1 Final II=2\n")
            result = analyze_csynth(root, "csynth.xml", "compile.log")
            self.assertEqual(len(result["diagnostics"]), 3)
            self.assertEqual(result["report"]["sha256"], sha256_bytes(HLS_XML))
            self.assertEqual(result["source_binding"], "UNVERIFIED")
            self.assertEqual(result["acceptance"], "NOT_EVALUATED")
            with self.assertRaises(ValueError):
                analyze_csynth(root, str(ROOT / "pyproject.toml"))

    def test_optional_mcp_reader_requires_no_build_project_or_top(self):
        hls = load_module("adoption_hls", "mcp/vitis-hls-mcp/server.py")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "csynth.xml").write_bytes(HLS_XML)
            with patch.object(hls, "PROJECT_ROOT", root), patch.object(hls, "_run_vitis_hls") as runner:
                result = asyncio.run(hls.call_tool("analyze_csynth", {"report_path": "csynth.xml"}))
                self.assertEqual(json.loads(result[0].text)["status"], "COLLECTED")
                blocked = asyncio.run(hls.call_tool("analyze_csynth", {"report_path": "missing.xml"}))
                self.assertEqual(json.loads(blocked[0].text)["status"], "BLOCKED")
                runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
