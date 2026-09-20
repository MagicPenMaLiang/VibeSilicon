import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from scripts import asic_backend_contract as backend
from scripts import asic_physical_artifact as physical
from tests import test_asic_synth_sta_adapter as a02_tests


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
FINALIZE_TIME = datetime(2026, 9, 9, 14, 0, tzinfo=timezone.utc)


class AsicPhysicalArtifactTests(unittest.TestCase):
    def setUp(self):
        self.a02 = a02_tests.AsicSynthStaAdapterTests()
        self.a02.setUp()
        self.addCleanup(self.a02.tearDown)
        (
            self.policy,
            self.contract,
            self.capabilities,
            self.input_evidence,
            self.a02_approval,
        ) = self.a02.context()
        self.a02_evidence = self.a02.execute()
        self.a02_run = self.a02.run_parent / "run"
        self.physical_temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.physical_temporary.cleanup)
        self.physical_parent = Path(self.physical_temporary.name)

    def config(self):
        return {
            "schema_version": 2,
            "floorplan": {
                "die_area_um": [0, 0, 100, 100],
                "core_area_um": [10, 10, 90, 90],
                "site": "unithd",
            },
            "placement": {
                "pin_horizontal_layer": "metal3",
                "pin_vertical_layer": "metal2",
                "filler_cells": ["FILL1", "FILL2"],
            },
            "optimization": {
                "placement_density": 0.6,
                "timing_driven_placement": True,
                "routability_driven_placement": True,
                "force_center_initial_place": True,
                "min_phi_coefficient": 0.95,
                "max_phi_coefficient": 1.05,
                "match_cell_footprint": True,
                "cts_sink_clustering": True,
                "cts_repair_clock_nets": True,
                "post_global_route_repair": True,
            },
            "routing": {
                "signal_layers": "metal1-metal5",
                "clock_layers": "metal3-metal5",
                "signal_wire_rc_layer": "metal3",
                "clock_wire_rc_layer": "metal4",
                "global_layer_adjustment": 0.2,
                "via_in_pin_layer": "metal1",
                "detailed_route_end_iteration": 64,
                "detailed_route_seed": 1,
                "detailed_route_k": 1,
            },
        }

    def test_reference_physical_config_v2_is_valid_and_frozen(self):
        config = json.loads(
            (ROOT / "config/asic_reference_physical_config.json").read_text(
                encoding="utf-8"
            )
        )
        physical.validate_config(config)
        self.assertEqual(
            physical.config_sha256(config),
            "sha256:777147e70154414a142e28037144dc00993ad3e2408af7ed83533f74688d9826",
        )
        self.assertEqual(config["optimization"]["placement_density"], 0.6)
        self.assertTrue(config["optimization"]["post_global_route_repair"])
        serialized = json.dumps(config)
        self.assertNotIn("REPLACE_ME", serialized)
        self.assertNotRegex(serialized, r"(?:[A-Za-z]:\\|/opt/|/home/)")

    def approval(self, config=None):
        config = self.config() if config is None else config
        return {
            "schema_version": 1,
            "status": "APPROVED",
            "scope": [
                "floorplan",
                "place",
                "cts",
                "route",
                "drc",
                "export_gds",
                "lvs",
            ],
            "approved_by": "asic-physical-owner",
            "approved_at": "2026-09-09T00:00:00Z",
            "expires_at": "2099-01-01T00:00:00Z",
            "backend_contract_id": self.contract["contract_id"],
            "capability_id": self.capabilities["capability_id"],
            "input_evidence_id": self.input_evidence["evidence_id"],
            "a02_evidence_id": self.a02_evidence["evidence_id"],
            "physical_config_sha256": physical.config_sha256(config),
        }

    def fake_runner(
        self,
        *,
        wns=0.1,
        tns=0.0,
        area=10.3,
        drc_count=0,
        drc_rule="'m3.6'",
        route_drc_count=None,
        omit=None,
        lvs_returncode=0,
    ):
        route_drc_count = drc_count if route_drc_count is None else route_drc_count
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            root = Path(kwargs["cwd"])
            is_klayout = Path(command[0]).name.startswith("strmrun")
            is_lvs = is_klayout and any(
                item == "report_file=lvs.lvsdb" for item in command
            )
            is_drc = is_klayout and any(
                item == "report_file=signoff-drc.lyrdb" for item in command
            )
            artifacts = (
                {
                    "lvs.lvsdb": (
                        "#%lvsdb-klayout\n"
                        " X(top\n  N(1 I(VDD))\n )\n"
                        " X(TOP\n  N(2 I(VDD))\n )\n"
                        "Z(\n X(top TOP X\n  Z(\n   N(1 2 1)\n  )\n )\n)\n"
                    ),
                    "lvs-extracted.cdl": ".subckt top clk\n.ends top\n",
                }
                if is_lvs
                else {
                    "signoff-drc.lyrdb": "<report-database><top-cell>top</top-cell><items>"
                    + (
                        "<item><category>"
                        + drc_rule
                        + "</category><cell>top</cell><multiplicity>1</multiplicity>"
                        "<values><value>polygon: (10,10;11,10;11,11;10,11)"
                        "</value></values></item>"
                    )
                    * drc_count
                    + "</items></report-database>\n"
                }
                if is_drc
                else {"final.gds": "synthetic routed gds\n"}
                if is_klayout
                else {
                    "final.cdl": ".subckt top clk\n.ends top\n",
                    "final.def": (
                        "VERSION 5.8 ;\nDESIGN top ;\n"
                        "UNITS DISTANCE MICRONS 1000 ;\n"
                        "COMPONENTS 1 ;\n"
                        " - u1 CELL + PLACED ( 10000 10000 ) N ;\n"
                        "END COMPONENTS\n"
                        "SPECIALNETS 1 ;\n"
                        " - VDD ( * VPWR ) + ROUTED metal3 100 "
                        "( 10000 10000 ) ( 20000 10000 ) ;\n"
                        "END SPECIALNETS\n"
                        "NETS 1 ;\n"
                        " - clk ( u1 A ) + ROUTED metal3 100 "
                        "( 10000 10000 ) ( 20000 10000 ) ;\n"
                        "END NETS\nEND DESIGN\n"
                    ),
                    "drc.rpt": f"DRC violations: {route_drc_count}\n",
                    "postroute.v": "module top(); endmodule\n",
                    "final.spef": "*SPEF IEEE 1481-1998\n",
                }
            )
            for name, content in artifacts.items():
                if name != omit:
                    (root / name).write_text(content, encoding="utf-8")
            if is_lvs:
                return subprocess.CompletedProcess(
                    command,
                    lvs_returncode,
                    "INFO : Congratulations! Netlists match.\n",
                    "",
                )
            if is_drc:
                return subprocess.CompletedProcess(command, 0, "DRC complete\n", "")
            if is_klayout:
                return subprocess.CompletedProcess(
                    command, 0, "VIBESILICON_GDS_EXPORT=final.gds\n", ""
                )
            stdout = (
                f"VIBESILICON_DRC_COUNT={route_drc_count}\n"
                f"worst slack {wns}\n"
                f"tns {tns}\n"
                f"Design area {area} u^2 10% utilization.\n"
            )
            return subprocess.CompletedProcess(command, 0, stdout, "")

        return calls, run

    def execute(self, *, config=None, approval=None, runner=None):
        config = self.config() if config is None else config
        approval = self.approval(config) if approval is None else approval
        if runner is None:
            _, runner = self.fake_runner()
        return physical.run_physical(
            config,
            self.a02.manifest(),
            self.policy,
            self.contract,
            self.capabilities,
            self.input_evidence,
            self.a02_evidence,
            self.a02_approval,
            approval,
            repository_root=ROOT,
            pdk_root=self.a02.pdk_root,
            design_root=self.a02.design_root,
            a02_run_directory=self.a02_run,
            run_directory=self.physical_parent / "run",
            runner=runner,
            resolver=self.a02.tools.get,
            now=NOW,
        )

    def lvs_receipt(self, run_evidence, *, passed=True):
        run = self.physical_parent / "run"
        report = run / "lvs.lvsdb"
        artifacts = {item["role"]: item for item in run_evidence["artifacts"]}
        value = {
            "schema_version": 1,
            "receipt_id": "",
            "status": "PASS" if passed else "FAIL",
            "checker_id": "klayout",
            "checker_version": "1.5.270",
            "checked_at": "2026-09-09T13:00:00Z",
            "reviewed_by": "asic-signoff-owner",
            "pdk_input_evidence_id": self.input_evidence["evidence_id"],
            "gds_sha256": artifacts["gds"]["sha256"],
            "reference_netlist_sha256": artifacts["lvs_reference"]["sha256"],
            "lvs_rules_sha256": {
                item["role"]: item for item in self.input_evidence["pdk"]["views"]
            }["lvs_rules"]["sha256"],
            "top_cell": "top",
            "report_path": "lvs.lvsdb",
            "report_sha256": backend._sha256_file(report),
            "report_bytes": report.stat().st_size,
            "layout_instance_count": 12,
            "schematic_instance_count": 12,
            "mismatched_nets": 0 if passed else 1,
            "mismatched_devices": 0,
        }
        value["receipt_id"] = physical._content_id(value, "receipt_id")
        return value

    def finalize(self, run_evidence, receipt):
        return physical.finalize_manifest(
            run_evidence,
            receipt,
            self.policy,
            self.contract,
            self.capabilities,
            self.input_evidence,
            self.a02_evidence,
            self.a02_approval,
            self.approval(),
            self.config(),
            run_directory=self.physical_parent / "run",
            now=FINALIZE_TIME,
        )

    def test_fixed_physical_run_and_lvs_finalize_complete_manifest(self):
        calls, runner = self.fake_runner()
        run_evidence = self.execute(runner=runner)
        self.assertEqual(run_evidence["result_status"], "PASS")
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[0][0][1:], ["-no_init", "-exit", "physical.tcl"])
        self.assertEqual(
            calls[1][0][1:3],
            ["-v", "tech_file=" + str(self.a02.pdk_root / "platform.lyt")],
        )
        self.assertEqual(calls[1][0][-1], "gds_export.py")
        self.assertEqual(calls[2][0][-1], str(self.a02.pdk_root / "platform.lydrc"))
        self.assertIn("report_file=signoff-drc.lyrdb", calls[2][0])
        self.assertEqual(calls[3][0][-1], str(self.a02.pdk_root / "platform.lylvs"))
        self.assertIn("top_cell=top", calls[3][0])
        self.assertIn("report_file=lvs.lvsdb", calls[3][0])
        self.assertFalse(calls[0][1]["shell"])
        self.assertFalse(calls[1][1]["shell"])
        self.assertFalse(calls[2][1]["shell"])
        self.assertFalse(calls[3][1]["shell"])
        script = (self.physical_parent / "run" / "physical.tcl").read_text(
            encoding="utf-8"
        )
        for anchor in (
            "initialize_floorplan",
            "global_placement",
            "clock_tree_synthesis",
            "detailed_route",
            "detailed_route_num_drvs",
            "extract_parasitics -ext_model_file",
            'open "drc.rpt" "w"',
        ):
            self.assertIn(anchor, script)
        self.assertEqual(script.count("detailed_placement"), 5)
        self.assertIn(
            "make_tracks metal1 -x_offset 0.1 -x_pitch 0.2 -y_offset 0.1 -y_pitch 0.2",
            script,
        )
        self.assertIn("filler_placement {FILL1 FILL2}", script)
        self.assertIn(
            "set_layer_rc -layer metal1 -capacitance 1e-4 -resistance 1e-3",
            script,
        )
        self.assertIn(
            "add_global_connection -net {VDD} -inst_pattern {.*} "
            "-pin_pattern {^VPWR$} -power",
            script,
        )
        self.assertIn("tapcell -distance 14 -tapcell_master TAP1", script)
        lines = script.splitlines()
        self.assertLess(
            lines.index("tapcell -distance 14 -tapcell_master TAP1"),
            lines.index("global_connect"),
        )
        self.assertIn(
            "define_pdn_grid -name {core_grid} -voltage_domains {CORE} "
            "-pins {metal5}",
            script,
        )
        self.assertIn("pdngen", script)
        self.assertEqual(script.count("repair_timing -setup"), 3)
        self.assertEqual(script.count("repair_timing -hold"), 2)
        self.assertIn(
            "global_placement -density 0.6 -routability_driven -timing_driven "
            "-force_center_initial_place -min_phi_coef 0.95 -max_phi_coef 1.05",
            script,
        )
        self.assertEqual(script.count("-match_cell_footprint"), 7)
        self.assertIn(
            "clock_tree_synthesis -sink_clustering_enable -repair_clock_nets",
            script,
        )
        self.assertIn(
            "pin_access -via_in_pin_bottom_layer metal1 "
            "-via_in_pin_top_layer metal1",
            script,
        )
        self.assertEqual(script.count("global_route -start_incremental"), 2)
        self.assertEqual(script.count("global_route -end_incremental"), 2)
        first_route = lines.index("global_route")
        self.assertEqual(
            lines[first_route + 1 : first_route + 13],
            [
                "estimate_parasitics -global_routing",
                "repair_design -slew_margin 20 -cap_margin 20 "
                "-match_cell_footprint -verbose",
                "global_route -start_incremental",
                "detailed_placement",
                "global_route -end_incremental",
                "estimate_parasitics -global_routing",
                "repair_timing -setup -repair_tns 100 "
                "-match_cell_footprint -verbose",
                "repair_timing -hold -match_cell_footprint -verbose",
                "global_route -start_incremental",
                "detailed_placement",
                "global_route -end_incremental",
                "estimate_parasitics -global_routing",
            ],
        )
        self.assertIn("set_global_routing_layer_adjustment metal1-metal5 0.2", script)
        self.assertIn(
            "detailed_route -droute_end_iter 64 "
            "-via_in_pin_bottom_layer metal1 -via_in_pin_top_layer metal1 "
            "-or_seed 1 -or_k 1 -drc_report_iter_step 5 -verbose 1",
            script,
        )
        self.assertEqual(script.splitlines().count("global_connect"), 2)
        self.assertGreater(script.rindex("global_connect"), script.index("filler_placement"))
        self.assertNotIn("filler_placement -cell", script)
        self.assertNotIn("write_gds", script)
        self.assertIn("write_cdl -masters", script)
        self.assertEqual(
            (self.physical_parent / "run" / "lvs_reference.cdl").read_text(
                encoding="utf-8"
            ),
            ".subckt top clk\n.ends top\n\n"
            ".subckt INVX1 A Y VDD VSS\n.ends\n\n",
        )
        exporter = (self.physical_parent / "run" / "gds_export.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("options.lefdef_config.lef_files", exporter)
        self.assertIn("Referenced cell has no stream geometry", exporter)
        self.assertEqual(
            [item["name"] for item in run_evidence["tools"]],
            ["openroad", "strmrun"],
        )
        artifacts_by_role = {item["role"]: item for item in run_evidence["artifacts"]}
        self.assertIn("signoff_localization", artifacts_by_role)
        localization = json.loads(
            (self.physical_parent / "run" / "signoff-localization.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(localization["security"]["repository_safe"])
        self.assertFalse(localization["security"]["signoff_authority"])
        receipt = self.lvs_receipt(run_evidence)
        result = self.finalize(run_evidence, receipt)
        self.assertEqual(result["result_status"], "PASS")
        self.assertFalse(result["gds_alone_is_pass"])
        self.assertEqual(result["next_gate"], "A04_REPRODUCTION_ACCEPTANCE")
        schemas = json.loads(
            (ROOT / "schemas/asic_physical_artifact.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.Draft202012Validator(schemas).validate(run_evidence)
        jsonschema.Draft202012Validator(schemas).validate(result)
        physical_rule_schema = json.loads(
            (ROOT / "schemas/asic_pdk_physical_rules.schema.json").read_text(
                encoding="utf-8"
            )
        )
        physical_rules = json.loads(
            (self.a02.pdk_root / "physical_rules.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(physical_rule_schema).validate(physical_rules)

    def test_drc_timing_or_lvs_failure_blocks_gds_manifest(self):
        _, runner = self.fake_runner(drc_count=2, route_drc_count=0)
        run_evidence = self.execute(runner=runner)
        self.assertEqual(run_evidence["result_status"], "DRC_VIOLATION")
        self.assertEqual(
            run_evidence["metrics"]["drc_rule_counts"],
            [{"rule": "m3.6", "count": 2}],
        )
        receipt = self.lvs_receipt(run_evidence)
        result = self.finalize(run_evidence, receipt)
        self.assertEqual(result["result_status"], "BLOCKED")
        self.assertEqual(result["checks"]["drc"], "FAIL")

        self._new_physical_parent()
        _, runner = self.fake_runner(wns=-0.2, tns=-1.0)
        run_evidence = self.execute(runner=runner)
        receipt = self.lvs_receipt(run_evidence, passed=False)
        result = self.finalize(run_evidence, receipt)
        self.assertEqual(result["checks"]["timing"], "FAIL")
        self.assertEqual(result["checks"]["lvs"], "FAIL")
        self.assertEqual(result["next_gate"], "A03_REMEDIATE_AND_RERUN")

    def _new_physical_parent(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.physical_parent = Path(temporary.name)

    def test_gds_presence_without_other_artifacts_fails_closed(self):
        _, runner = self.fake_runner(omit="drc.rpt")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "drc_report"):
            self.execute(runner=runner)
        self.assertTrue((self.physical_parent / "run" / "final.gds").is_file())

    def test_lvs_execution_or_report_failure_retains_run_directory(self):
        _, runner = self.fake_runner(lvs_returncode=1)
        with self.assertRaisesRegex(physical.AsicPhysicalError, "LVS failed"):
            self.execute(runner=runner)
        self.assertTrue((self.physical_parent / "run" / "final.gds").is_file())
        self.assertTrue((self.physical_parent / "run" / "lvs.stdout.log").is_file())

        self._new_physical_parent()
        _, runner = self.fake_runner(omit="lvs.lvsdb")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "lvs_report"):
            self.execute(runner=runner)

    def test_expired_approval_and_config_drift_stop_before_runner(self):
        approval = self.approval()
        approval["expires_at"] = "2026-09-09T01:00:00Z"
        calls = []
        with self.assertRaisesRegex(physical.AsicPhysicalError, "not currently valid"):
            self.execute(
                approval=approval,
                runner=lambda *args, **kwargs: calls.append((args, kwargs)),
            )
        self.assertEqual(calls, [])
        changed = self.config()
        changed["floorplan"]["core_area_um"] = [20, 20, 80, 80]
        with self.assertRaisesRegex(physical.AsicPhysicalError, "exact evidence set"):
            self.execute(
                config=changed,
                approval=self.approval(),
                runner=lambda *args, **kwargs: calls.append((args, kwargs)),
            )
        self.assertEqual(calls, [])

    def test_a02_artifact_drift_stops_before_physical_runner(self):
        (self.a02_run / "netlist.v").write_text("changed\n", encoding="utf-8")
        calls = []
        with self.assertRaisesRegex(physical.AsicPhysicalError, "A02 artifact drift"):
            self.execute(runner=lambda *args, **kwargs: calls.append((args, kwargs)))
        self.assertEqual(calls, [])

    def test_track_definition_rejects_arbitrary_tcl(self):
        tracks = self.a02.pdk_root / "make_tracks.tcl"
        tracks.write_text("source /tmp/unreviewed.tcl\n", encoding="utf-8")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "non-allowlisted Tcl"):
            physical._track_commands(tracks)

    def test_rc_definition_rejects_arbitrary_tcl(self):
        rc_tech = self.a02.pdk_root / "rc.tech"
        rc_tech.write_text("source /tmp/unreviewed.tcl\n", encoding="utf-8")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "non-allowlisted Tcl"):
            physical._rc_commands(rc_tech)

    def test_physical_rules_reject_tcl_and_invalid_relations(self):
        rules = self.a02.pdk_root / "physical_rules.json"
        rules.write_text("source /tmp/unreviewed.tcl\n", encoding="utf-8")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "physical rules JSON"):
            physical._physical_rule_commands(rules)

        value = {
            "schema_version": 1,
            "global_connections": [
                {"net": "VDD", "pin": "VPWR", "type": "POWER"},
                {"net": "VSS", "pin": "VGND", "type": "GROUND"},
            ],
            "tapcell": {"distance_um": 14, "tapcell_master": "TAP1"},
            "pdn": {
                "voltage_domains": [
                    {"name": "CORE", "power_net": "VDD", "ground_net": "VSS"}
                ],
                "grids": [
                    {
                        "name": "core_grid",
                        "kind": "STANDARD",
                        "voltage_domain": "MISSING",
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
        rules.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "identity or domain"):
            physical._physical_rule_commands(rules)

        value["pdn"]["grids"][0]["voltage_domain"] = "CORE"
        value["global_connections"][1]["pin"] = "VPWR"
        rules.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "duplicates"):
            physical._physical_rule_commands(rules)

    def test_routing_remediation_parameters_are_bounded(self):
        for field, value in (
            ("global_layer_adjustment", 1.01),
            ("via_in_pin_layer", "metal1; source bad.tcl"),
            ("detailed_route_end_iteration", 129),
            ("detailed_route_seed", -1),
            ("detailed_route_k", 0),
        ):
            config = self.config()
            config["routing"][field] = value
            with self.subTest(field=field):
                with self.assertRaises(physical.AsicPhysicalError):
                    physical.validate_config(config)

    def test_optimization_parameters_are_bounded_and_typed(self):
        for field, value in (
            ("placement_density", 0.29),
            ("placement_density", True),
            ("min_phi_coefficient", 0.49),
            ("max_phi_coefficient", 1.51),
            ("timing_driven_placement", 1),
            ("post_global_route_repair", "true"),
        ):
            config = self.config()
            config["optimization"][field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(physical.AsicPhysicalError):
                    physical.validate_config(config)

        config = self.config()
        config["optimization"]["min_phi_coefficient"] = 1.0
        config["optimization"]["max_phi_coefficient"] = 0.99
        with self.assertRaisesRegex(
            physical.AsicPhysicalError, "must not exceed"
        ):
            physical.validate_config(config)

    def test_signoff_drc_report_requires_rule_categories(self):
        _, runner = self.fake_runner(drc_count=1, drc_rule="")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "rule category"):
            self.execute(runner=runner)

    def test_lvs_receipt_identity_counts_and_report_are_bound(self):
        run_evidence = self.execute()
        receipt = self.lvs_receipt(run_evidence)
        changed = copy.deepcopy(receipt)
        changed["checker_id"] = "netgen"
        changed["receipt_id"] = physical._content_id(changed, "receipt_id")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "fixed backend"):
            self.finalize(run_evidence, changed)
        changed = copy.deepcopy(receipt)
        changed["gds_sha256"] = "sha256:" + "0" * 64
        changed["receipt_id"] = physical._content_id(changed, "receipt_id")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "physical artifacts"):
            self.finalize(run_evidence, changed)
        changed = copy.deepcopy(receipt)
        artifacts = {item["role"]: item for item in run_evidence["artifacts"]}
        changed["reference_netlist_sha256"] = artifacts["cdl"]["sha256"]
        changed["receipt_id"] = physical._content_id(changed, "receipt_id")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "physical artifacts"):
            self.finalize(run_evidence, changed)
        changed = copy.deepcopy(receipt)
        changed["mismatched_nets"] = 1
        changed["receipt_id"] = physical._content_id(changed, "receipt_id")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "mismatch counts"):
            self.finalize(run_evidence, changed)
        for field, value in (
            ("lvs_rules_sha256", "sha256:" + "0" * 64),
            ("top_cell", "other_top"),
        ):
            changed = copy.deepcopy(receipt)
            changed[field] = value
            changed["receipt_id"] = physical._content_id(changed, "receipt_id")
            with self.assertRaisesRegex(physical.AsicPhysicalError, "physical artifacts"):
                self.finalize(run_evidence, changed)
        (self.physical_parent / "run" / "lvs.lvsdb").write_text(
            "changed\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(physical.AsicPhysicalError, "artifact drift: lvs_report"):
            self.finalize(run_evidence, receipt)

    def test_recomputed_run_and_final_tamper_are_rejected(self):
        run_evidence = self.execute()
        changed = copy.deepcopy(run_evidence)
        changed["metrics"]["drc_clean"] = False
        changed["evidence_id"] = physical._content_id(changed, "evidence_id")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "derived metric"):
            physical.validate_run_evidence(
                changed,
                self.policy,
                self.contract,
                self.capabilities,
                self.input_evidence,
                self.a02_evidence,
                self.a02_approval,
                self.approval(),
                self.config(),
            )
        self._new_physical_parent()
        _, runner = self.fake_runner(drc_count=1, route_drc_count=0)
        run_evidence = self.execute(runner=runner)
        changed = copy.deepcopy(run_evidence)
        changed["metrics"]["drc_rule_counts"][0]["rule"] = "li.3"
        changed["evidence_id"] = physical._content_id(changed, "evidence_id")
        receipt = self.lvs_receipt(changed)
        with self.assertRaisesRegex(physical.AsicPhysicalError, "DRC metrics"):
            self.finalize(changed, receipt)

        self._new_physical_parent()
        run_evidence = self.execute()
        receipt = self.lvs_receipt(run_evidence)
        result = self.finalize(run_evidence, receipt)
        changed = copy.deepcopy(result)
        changed["gds_alone_is_pass"] = True
        changed["manifest_id"] = physical._content_id(changed, "manifest_id")
        with self.assertRaisesRegex(physical.AsicPhysicalError, "reviewed semantics"):
            physical.validate_final_manifest(
                changed,
                run_evidence,
                receipt,
                self.policy,
                self.input_evidence,
                self.a02_evidence,
            )

    def test_recomputed_localization_tamper_is_rejected_against_sources(self):
        run_evidence = self.execute()
        run_directory = self.physical_parent / "run"
        path = run_directory / "signoff-localization.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["lvs"]["messages"].append(
            {"severity": "INFO", "message": "forged but structurally valid"}
        )
        value["localization_id"] = physical.signoff_localization._content_id(value)
        path.write_bytes(physical.signoff_localization._canonical_bytes(value) + b"\n")
        changed = copy.deepcopy(run_evidence)
        artifact = next(
            item
            for item in changed["artifacts"]
            if item["role"] == "signoff_localization"
        )
        artifact.update(
            physical.synth_sta._artifact(
                path, run_directory, "A03 signoff localization"
            )
        )
        changed["evidence_id"] = physical._content_id(changed, "evidence_id")
        receipt = self.lvs_receipt(changed)
        with self.assertRaisesRegex(physical.AsicPhysicalError, "source reports"):
            self.finalize(changed, receipt)

    def test_templates_are_non_authorizing_and_cli_is_standalone(self):
        config = json.loads(
            (ROOT / "templates/asic_physical_config.template.json").read_text(
                encoding="utf-8"
            )
        )
        with self.assertRaisesRegex(physical.AsicPhysicalError, "placeholder"):
            physical.validate_config(config)
        physical_rules = ROOT / "templates/asic_pdk_physical_rules.template.json"
        with self.assertRaisesRegex(physical.AsicPhysicalError, "placeholder"):
            physical._physical_rule_commands(physical_rules)
        approval = json.loads(
            (ROOT / "templates/asic_physical_approval.template.json").read_text(
                encoding="utf-8"
            )
        )
        with self.assertRaisesRegex(physical.AsicPhysicalError, "status"):
            physical.validate_approval(
                approval,
                self.contract,
                self.capabilities,
                self.input_evidence,
                self.a02_evidence,
                self.config(),
                now=NOW,
            )
        run_evidence = self.execute()
        lvs = json.loads(
            (ROOT / "templates/asic_lvs_receipt.template.json").read_text(
                encoding="utf-8"
            )
        )
        with self.assertRaisesRegex(physical.AsicPhysicalError, "content ID"):
            physical.validate_lvs_receipt(
                lvs,
                run_evidence,
                self.input_evidence,
                self.physical_parent / "run",
                now=FINALIZE_TIME,
            )
        completed = subprocess.run(
            [sys.executable, "scripts/asic_physical_artifact.py", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

if __name__ == "__main__":
    unittest.main()
