import copy
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from scripts import asic_backend_contract as backend
from scripts import asic_input_evidence as inputs
from scripts import asic_synth_sta_adapter as adapter


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


class AsicSynthStaAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporaries = [tempfile.TemporaryDirectory() for _ in range(4)]
        self.pdk_root, self.design_root, self.tool_root, self.run_parent = [
            Path(item.name) for item in self.temporaries
        ]
        files = {
            "LICENSE": "Apache License 2.0\n",
            "corner.lib": "library(test) {}\n",
            "rc.tech": "set_layer_rc -layer metal1 -capacitance 1e-4 -resistance 1e-3\n",
            "tech.lef": "VERSION 5.8 ;\n",
            "cells.lef": "MACRO INVX1\nEND INVX1\n",
            "cells.gds": "synthetic gds bytes\n",
            "cells.spice": ".subckt INVX1 A Y VDD VSS\n.ends\n",
            "platform.sdc": "set_units -time ns\n",
            "synthesis_rules.json": json.dumps(
                {
                    "schema_version": 1,
                    "dont_use_cells": ["BADISO1", "BADPROBE1"],
                    "abc": {"driver_cell": "BUF1", "load_in_ff": 5},
                }
            )
            + "\n",
            "make_tracks.tcl": "make_tracks metal1 -x_offset 0.1 -x_pitch 0.2 -y_offset 0.1 -y_pitch 0.2\n",
            "platform.lyt": "<technology><name>test</name></technology>\n",
            "rcx.rules": "Extraction Rules for OpenRCX\n",
            "physical_rules.json": json.dumps(
                {
                    "schema_version": 1,
                    "global_connections": [
                        {"net": "VDD", "pin": "VPWR", "type": "POWER"},
                        {"net": "VDD", "pin": "VPB", "type": "SECONDARY"},
                        {"net": "VSS", "pin": "VGND", "type": "GROUND"},
                        {"net": "VSS", "pin": "VNB", "type": "SECONDARY"},
                    ],
                    "tapcell": {"distance_um": 14, "tapcell_master": "TAP1"},
                    "pdn": {
                        "voltage_domains": [
                            {
                                "name": "CORE",
                                "power_net": "VDD",
                                "ground_net": "VSS",
                            }
                        ],
                        "grids": [
                            {
                                "name": "core_grid",
                                "kind": "STANDARD",
                                "voltage_domain": "CORE",
                                "pins": ["metal5"],
                            }
                        ],
                        "stripes": [
                            {
                                "grid": "core_grid",
                                "layer": "metal1",
                                "width_um": 0.48,
                                "pitch_um": 5.44,
                                "offset_um": 0,
                                "followpins": True,
                            }
                        ],
                        "connects": [
                            {"grid": "core_grid", "layers": ["metal1", "metal5"]}
                        ],
                    },
                }
            )
            + "\n",
            "platform.lylvs": "# synthetic LVS rule deck\n",
            "platform.lydrc": "# synthetic DRC rule deck\n",
        }
        for name, content in files.items():
            (self.pdk_root / name).write_text(content, encoding="utf-8")
        (self.design_root / "top.sv").write_text(
            "module top(input logic clk, input logic a, output logic y); "
            "always_ff @(posedge clk) y <= a; endmodule\n",
            encoding="utf-8",
        )
        (self.design_root / "design.sdc").write_text(
            "create_clock -period 10 [get_ports clk]\n", encoding="utf-8"
        )
        self.tools = {}
        for name in ("yosys", "openroad", "strmrun"):
            path = self.tool_root / f"{name}.exe"
            path.write_bytes((name + " binary").encode("ascii"))
            self.tools[name] = str(path)

    def tearDown(self):
        for item in reversed(self.temporaries):
            item.cleanup()

    def test_artifact_normalizes_root_before_containment_check(self):
        run_directory = self.run_parent / "run"
        run_directory.mkdir()
        artifact = run_directory / "result.txt"
        artifact.write_bytes(b"result\n")
        original_directory = Path.cwd()
        try:
            os.chdir(self.run_parent)
            record = adapter._artifact(artifact, Path("run"), "test artifact")
        finally:
            os.chdir(original_directory)

        self.assertEqual(record["bytes"], 7)
        self.assertRegex(record["sha256"], r"^sha256:[0-9a-f]{64}$")

    def policy(self):
        return json.loads(
            (ROOT / "config/asic_backend_policy.json").read_text(encoding="utf-8")
        )

    def manifest(self):
        return {
            "schema_version": 1,
            "pdk": {
                "pdk_id": "public-pdk-alpha",
                "source_origin": "https://github.com/google/skywater-pdk",
                "source_revision": "1" * 40,
                "storage_id": "external-pdk-cache-01",
                "license": {
                    "spdx_id": "Apache-2.0",
                    "review_status": "APPROVED",
                    "reviewed_by": "asic-review-board",
                    "reviewed_at": "2026-09-09T00:00:00Z",
                    "path": "LICENSE",
                },
                "corner": {
                    "name": "nominal",
                    "process": "typical",
                    "voltage_v": 1.8,
                    "temperature_c": 25,
                    "liberty_path": "corner.lib",
                    "rc_tech_path": "rc.tech",
                },
                "views": [
                    {"role": "tech_lef", "path": "tech.lef"},
                    {"role": "cell_lef", "path": "cells.lef"},
                    {"role": "gds", "path": "cells.gds"},
                    {"role": "spice", "path": "cells.spice"},
                    {"role": "sdc", "path": "platform.sdc"},
                    {"role": "synthesis_rules", "path": "synthesis_rules.json"},
                    {"role": "tracks", "path": "make_tracks.tcl"},
                    {"role": "klayout_tech", "path": "platform.lyt"},
                    {"role": "rcx_rules", "path": "rcx.rules"},
                    {"role": "physical_rules", "path": "physical_rules.json"},
                    {"role": "lvs_rules", "path": "platform.lylvs"},
                    {"role": "drc_rules", "path": "platform.lydrc"},
                ],
            },
            "design": {
                "design_id": "public-smoke-design",
                "top_module": "top",
                "rtl_languages": ["systemverilog"],
                "source_visibility": "PUBLIC",
                "sources": ["top.sv"],
                "constraints_path": "design.sdc",
            },
            "security": {
                "paths_are_relative": True,
                "copy_into_repository": False,
                "network_access": False,
                "model_context_export": False,
            },
        }

    def context(self):
        policy = self.policy()
        contract = backend.build_contract(policy)

        def version_runner(command, **_kwargs):
            name = Path(command[0]).stem
            return subprocess.CompletedProcess(command, 0, f"{name} 1.0\n", "")

        capabilities = backend.discover_capabilities(
            policy, runner=version_runner, resolver=self.tools.get
        )
        input_evidence = inputs.build_evidence(
            self.manifest(),
            policy,
            contract,
            repository_root=ROOT,
            pdk_root=self.pdk_root,
            design_root=self.design_root,
        )
        approval = {
            "schema_version": 1,
            "status": "APPROVED",
            "scope": ["synthesize", "sta"],
            "approved_by": "asic-execution-owner",
            "approved_at": "2026-09-09T00:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
            "backend_contract_id": contract["contract_id"],
            "capability_id": capabilities["capability_id"],
            "input_evidence_id": input_evidence["evidence_id"],
        }
        return policy, contract, capabilities, input_evidence, approval

    def fake_runner(self, *, wns=0.125, tns=0.0, area=10.2, synth_area=10.0):
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            work = Path(kwargs["cwd"])
            if Path(command[0]).stem == "yosys":
                (work / "netlist.v").write_text("module top(); endmodule\n", encoding="utf-8")
                (work / "synthesis-stat.json").write_text(
                    json.dumps(
                        {
                            "modules": {
                                "top": {
                                    "num_cells": {
                                        "count": "12",
                                        "area": str(synth_area),
                                        "local_count": "12",
                                        "local_area": str(synth_area),
                                    }
                                }
                            }
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, "synthesis complete\n", "")
            stdout = (
                "[INFO GPL-0106] Timing-driven: worst slack -2.9971785e-09\n"
                f"worst slack max {wns}\n"
                f"tns max {tns}\n"
                f"Design area {area} um^2 10% utilization.\n"
            )
            return subprocess.CompletedProcess(command, 0, stdout, "")

        return calls, run

    def execute(self, *, runner=None, resolver=None, now=NOW):
        policy, contract, capabilities, input_evidence, approval = self.context()
        if runner is None:
            _, runner = self.fake_runner()
        return adapter.run_adapter(
            self.manifest(),
            policy,
            contract,
            capabilities,
            input_evidence,
            approval,
            repository_root=ROOT,
            pdk_root=self.pdk_root,
            design_root=self.design_root,
            run_directory=self.run_parent / "run",
            runner=runner,
            resolver=self.tools.get if resolver is None else resolver,
            now=now,
        )

    def test_fixed_two_step_run_builds_sanitized_canonical_evidence(self):
        calls, runner = self.fake_runner()
        result = self.execute(runner=runner)
        self.assertEqual(result["result_status"], "PASS")
        self.assertTrue(result["metrics"]["timing_met"])
        self.assertEqual(result["metrics"]["cell_count"], 12)
        self.assertEqual([item["role"] for item in result["artifacts"]], list(adapter.ARTIFACT_ROLES))
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0][1:], ["-q", "-s", "synth.ys"])
        self.assertEqual(calls[1][0][1:], ["-no_init", "-exit", "sta.tcl"])
        self.assertTrue(all(call[1]["shell"] is False for call in calls))
        self.assertIn(
            "set_cmd_units -time ns -distance um",
            (self.run_parent / "run" / "sta.tcl").read_text(encoding="utf-8"),
        )
        synth_script = (self.run_parent / "run" / "synth.ys").read_text(encoding="utf-8")
        self.assertIn("synth -flatten -noabc -top top", synth_script)
        self.assertEqual(synth_script.count("abc -D 10000 -constr"), 1)
        self.assertIn("-dont_use BADISO1 -dont_use BADPROBE1", synth_script)
        self.assertIn("-liberty", synth_script)
        self.assertEqual(
            (self.run_parent / "run" / "abc.constr").read_text(encoding="utf-8"),
            "set_driving_cell BUF1\nset_load 5\n",
        )
        self.assertIn("clean -purge", synth_script)
        self.assertIn("stat -top top -hierarchy", synth_script)
        serialized = json.dumps(result)
        self.assertNotIn(str(self.pdk_root), serialized)
        self.assertNotIn(str(self.design_root), serialized)
        policy, contract, capabilities, input_evidence, approval = self.context()
        adapter.validate_evidence(
            result, policy, contract, capabilities, input_evidence, approval
        )
        schema = json.loads(
            (ROOT / "schemas/asic_synth_sta_evidence.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.Draft202012Validator(schema).validate(result)

    def test_abc_delay_target_uses_tightest_literal_or_numeric_variable_clock(self):
        (self.design_root / "design.sdc").write_text(
            "set core_period 10\n"
            "create_clock -name core -period $core_period [get_ports clk]\n"
            "create_clock -name fast_virtual -period 1.1\n",
            encoding="utf-8",
        )

        self.execute()

        synth_script = (self.run_parent / "run" / "synth.ys").read_text(
            encoding="utf-8"
        )
        self.assertIn("abc -D 1100 -constr", synth_script)

    def test_synthesis_rules_are_schema_valid_and_bound_into_abc(self):
        rules = json.loads(
            (self.pdk_root / "synthesis_rules.json").read_text(encoding="utf-8")
        )
        schema = json.loads(
            (ROOT / "schemas/asic_pdk_synthesis_rules.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.Draft202012Validator(schema).validate(rules)

        self.execute()

        synth_script = (self.run_parent / "run" / "synth.ys").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            synth_script.index("-dont_use BADISO1"),
            synth_script.index("-dont_use BADPROBE1"),
        )

    def test_unsafe_synthesis_rules_stop_before_runner(self):
        invalid_rules = (
            {
                "schema_version": 1,
                "dont_use_cells": ["BAD1", "BAD1"],
                "abc": {"driver_cell": "BUF1", "load_in_ff": 5},
            },
            {
                "schema_version": 1,
                "dont_use_cells": ["BAD1;exec"],
                "abc": {"driver_cell": "BUF1", "load_in_ff": 5},
            },
            {
                "schema_version": 1,
                "dont_use_cells": ["BUF1"],
                "abc": {"driver_cell": "BUF1", "load_in_ff": 5},
            },
            {
                "schema_version": 1,
                "dont_use_cells": ["BAD1"],
                "abc": {"driver_cell": "BUF1", "load_in_ff": 0},
            },
        )
        for rules in invalid_rules:
            replacement = tempfile.TemporaryDirectory()
            self.temporaries.append(replacement)
            self.run_parent = Path(replacement.name)
            (self.pdk_root / "synthesis_rules.json").write_text(
                json.dumps(rules), encoding="utf-8"
            )
            policy, contract, capabilities, input_evidence, approval = self.context()
            calls = []
            with self.assertRaisesRegex(adapter.AsicSynthStaError, "synthesis"):
                adapter.run_adapter(
                    self.manifest(),
                    policy,
                    contract,
                    capabilities,
                    input_evidence,
                    approval,
                    repository_root=ROOT,
                    pdk_root=self.pdk_root,
                    design_root=self.design_root,
                    run_directory=self.run_parent / "run",
                    runner=lambda *args, **kwargs: calls.append((args, kwargs)),
                    resolver=self.tools.get,
                    now=NOW,
                )
            self.assertEqual(calls, [])

    def test_dynamic_or_missing_clock_period_stops_before_runner(self):
        for constraints in (
            "set core_period [expr 1.0 + 0.1]\n"
            "create_clock -period $core_period [get_ports clk]\n",
            "set core_period 1.1\n"
            "set core_period [expr 1.0 + 0.1]\n"
            "create_clock -period $core_period [get_ports clk]\n",
            "create_clock -period $core_period [get_ports clk]\n"
            "set core_period 1.1\n",
            "set_input_delay 0.2 [get_ports a]\n",
        ):
            replacement = tempfile.TemporaryDirectory()
            self.temporaries.append(replacement)
            self.run_parent = Path(replacement.name)
            (self.design_root / "design.sdc").write_text(
                constraints, encoding="utf-8"
            )
            calls = []
            with self.assertRaisesRegex(
                adapter.AsicSynthStaError, "period|create_clock"
            ):
                self.execute(
                    runner=lambda *args, **kwargs: calls.append((args, kwargs))
                )
            self.assertEqual(calls, [])

    def test_timing_violation_is_preserved_not_reported_as_pass(self):
        _, runner = self.fake_runner(wns=-0.25, tns=-1.5)
        result = self.execute(runner=runner)
        self.assertEqual(result["result_status"], "TIMING_VIOLATION")
        self.assertFalse(result["metrics"]["timing_met"])
        replacement = tempfile.TemporaryDirectory()
        self.temporaries.append(replacement)
        self.run_parent = Path(replacement.name)
        _, runner = self.fake_runner(wns=0.25, tns=0.5)
        with self.assertRaisesRegex(adapter.AsicSynthStaError, "TNS"):
            self.execute(runner=runner)

    def test_blocked_capabilities_stop_before_runner(self):
        policy, contract, _, input_evidence, approval = self.context()
        capabilities = backend.discover_capabilities(policy, resolver=lambda _name: None)
        approval["capability_id"] = capabilities["capability_id"]
        calls = []
        with self.assertRaisesRegex(adapter.AsicSynthStaError, "requires present"):
            adapter.run_adapter(
                self.manifest(),
                policy,
                contract,
                capabilities,
                input_evidence,
                approval,
                repository_root=ROOT,
                pdk_root=self.pdk_root,
                design_root=self.design_root,
                run_directory=self.run_parent / "run",
                runner=lambda *args, **kwargs: calls.append((args, kwargs)),
                resolver=lambda _name: None,
                now=NOW,
            )
        self.assertEqual(calls, [])

    def test_input_drift_and_missing_corner_stop_before_runner(self):
        policy, contract, capabilities, input_evidence, approval = self.context()
        manifest = self.manifest()
        manifest["pdk"]["corner"].pop("rc_tech_path")
        calls = []
        with self.assertRaisesRegex(adapter.AsicSynthStaError, "corner fields"):
            adapter.run_adapter(
                manifest,
                policy,
                contract,
                capabilities,
                input_evidence,
                approval,
                repository_root=ROOT,
                pdk_root=self.pdk_root,
                design_root=self.design_root,
                run_directory=self.run_parent / "run",
                runner=lambda *args, **kwargs: calls.append((args, kwargs)),
                resolver=self.tools.get,
                now=NOW,
            )
        self.assertEqual(calls, [])

    def test_binary_identity_drift_stops_before_runner(self):
        calls = []
        changed = self.tool_root / "changed-yosys.exe"
        changed.write_bytes(b"changed")
        resolver = {
            "yosys": str(changed),
            "openroad": self.tools["openroad"],
            "strmrun": self.tools["strmrun"],
        }.get
        with self.assertRaisesRegex(adapter.AsicSynthStaError, "identity drift"):
            self.execute(
                runner=lambda *args, **kwargs: calls.append((args, kwargs)),
                resolver=resolver,
            )
        self.assertEqual(calls, [])

    def test_expired_or_rebound_approval_is_rejected(self):
        policy, contract, capabilities, input_evidence, approval = self.context()
        template = json.loads(
            (ROOT / "templates/asic_execution_approval.template.json").read_text(
                encoding="utf-8"
            )
        )
        with self.assertRaisesRegex(adapter.AsicSynthStaError, "status"):
            adapter.validate_approval(
                template, contract, capabilities, input_evidence, now=NOW
            )
        approval["expires_at"] = "2026-09-09T01:00:00Z"
        with self.assertRaisesRegex(adapter.AsicSynthStaError, "not currently valid"):
            adapter.validate_approval(
                approval, contract, capabilities, input_evidence, now=NOW
            )
        approval = self.context()[-1]
        approval["input_evidence_id"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(adapter.AsicSynthStaError, "exact evidence set"):
            adapter.validate_approval(
                approval, contract, capabilities, input_evidence, now=NOW
            )

    def test_human_approver_name_is_accepted(self):
        _, contract, capabilities, input_evidence, approval = self.context()
        approval["approved_by"] = "Reviewer"

        adapter.validate_approval(
            approval,
            contract,
            capabilities,
            input_evidence,
            now=NOW,
        )

    def test_missing_reports_and_area_disagreement_fail_closed(self):
        def no_reports(command, **_kwargs):
            return subprocess.CompletedProcess(command, 0, "complete\n", "")

        with self.assertRaisesRegex(adapter.AsicSynthStaError, "synthesis stat"):
            self.execute(runner=no_reports)
        replacement = tempfile.TemporaryDirectory()
        self.temporaries.append(replacement)
        self.run_parent = Path(replacement.name)
        _, runner = self.fake_runner(area=20.0, synth_area=10.0)
        with self.assertRaisesRegex(adapter.AsicSynthStaError, "differ by more than"):
            self.execute(runner=runner)

    def test_recomputed_tamper_still_fails_semantic_verification(self):
        result = self.execute()
        changed = copy.deepcopy(result)
        changed["metrics"]["timing_met"] = False
        changed["evidence_id"] = adapter._content_id(changed, "evidence_id")
        policy, contract, capabilities, input_evidence, approval = self.context()
        with self.assertRaisesRegex(adapter.AsicSynthStaError, "timing_met"):
            adapter.validate_evidence(
                changed, policy, contract, capabilities, input_evidence, approval
            )
        changed_approval = copy.deepcopy(approval)
        changed_approval["approved_by"] = "different-owner"
        with self.assertRaisesRegex(adapter.AsicSynthStaError, "approval hash"):
            adapter.validate_evidence(
                result,
                policy,
                contract,
                capabilities,
                input_evidence,
                changed_approval,
            )

    def test_cli_requires_explicit_execution_flag(self):
        policy, contract, capabilities, input_evidence, approval = self.context()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "inputs").mkdir()
            records = {
                "policy.json": policy,
                "contract.json": contract,
                "capabilities.json": capabilities,
                "input-evidence.json": input_evidence,
                "manifest.json": self.manifest(),
                "approval.json": approval,
            }
            for name, value in records.items():
                (root / "inputs" / name).write_text(json.dumps(value), encoding="utf-8")
            arguments = [
                "run",
                "inputs/manifest.json",
                "--root",
                str(root),
                "--policy",
                "inputs/policy.json",
                "--backend-contract",
                "inputs/contract.json",
                "--capabilities",
                "inputs/capabilities.json",
                "--input-evidence",
                "inputs/input-evidence.json",
                "--approval",
                "inputs/approval.json",
                "--pdk-root",
                str(self.pdk_root),
                "--design-root",
                str(self.design_root),
                "--run-directory",
                str(self.run_parent / "run"),
                "--output",
                "results/evidence.json",
            ]
            self.assertEqual(adapter.main(arguments), 2)


if __name__ == "__main__":
    unittest.main()
