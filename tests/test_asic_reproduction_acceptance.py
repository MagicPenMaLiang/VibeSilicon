import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jsonschema

from scripts import asic_backend_contract as backend
from scripts import asic_physical_artifact as physical
from scripts import asic_reproduction_acceptance as acceptance
from scripts import asic_toolchain_provenance as toolchain_provenance
from tests import test_asic_synth_sta_adapter as a02_tests


ROOT = Path(__file__).resolve().parents[1]
ASSESSMENT_TIME = datetime(2026, 9, 9, 14, 0, tzinfo=timezone.utc)


class AsicReproductionAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.helpers = []
        self.directories = []
        self.profile = json.loads(
            (ROOT / "config/asic_reproduction_profile.json").read_text(encoding="utf-8")
        )
        self.baseline = self.make_chain(
            "baseline", datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc), area=10.30
        )
        self.replay = self.make_chain("replay", datetime(2026, 9, 9, 11, 0, tzinfo=timezone.utc), area=10.32)
        self.provenance = self.make_provenance()
        self.review = self.make_review()

    def tearDown(self):
        for helper in reversed(self.helpers):
            helper.tearDown()
        for directory in reversed(self.directories):
            directory.cleanup()

    @staticmethod
    def manifest():
        value = a02_tests.AsicSynthStaAdapterTests.manifest(None)
        value["pdk"].update(
            {
                "pdk_id": "sky130hd",
                "source_origin": acceptance.PROFILE["reference"]["pdk_source_origin"],
                "source_revision": acceptance.PROFILE["reference"][
                    "pdk_source_revision"
                ],
            }
        )
        value["design"].update(
            {
                "design_id": "orfs-sky130hd-gcd",
                "top_module": "gcd",
                "source_visibility": "PUBLIC",
            }
        )
        return value

    @staticmethod
    def physical_config():
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

    @staticmethod
    def physical_runner(area, marker):
        def run(command, **kwargs):
            root = Path(kwargs["cwd"])
            outputs = {
                "final.cdl": f".subckt gcd clk\n* {marker}\n.ends gcd\n",
                "final.def": (
                    "VERSION 5.8 ;\nDESIGN gcd ;\n"
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
                    f"# {marker}\n"
                ),
                "drc.rpt": "DRC violations: 0\n",
                "final.gds": f"synthetic routed gds {marker}\n",
                "postroute.v": f"module gcd(); endmodule // {marker}\n",
                "final.spef": f"*SPEF IEEE 1481-1998\n*DESIGN {marker}\n",
                "lvs.lvsdb": (
                    "#%lvsdb-klayout\n"
                    " X(gcd\n  N(1 I(VDD))\n )\n"
                    " X(GCD\n  N(2 I(VDD))\n )\n"
                    "Z(\n X(gcd GCD X\n  Z(\n   N(1 2 1)\n  )\n )\n)\n"
                    f"# {marker}\n"
                ),
                "lvs-extracted.cdl": f".subckt gcd clk\n* {marker}\n.ends gcd\n",
                "signoff-drc.lyrdb": (
                    "<report-database><top-cell>gcd</top-cell>"
                    "<items/></report-database>\n"
                ),
            }
            for name, content in outputs.items():
                (root / name).write_text(content, encoding="utf-8")
            stdout = (
                f"VIBESILICON_DRC_COUNT=0\nworst slack 0.10\ntns 0.0\nDesign area {area} u^2 10% utilization.\n"
            )
            return subprocess.CompletedProcess(command, 0, stdout, "")

        return run

    def make_chain(self, label, executed_at, *, area):
        helper = a02_tests.AsicSynthStaAdapterTests()
        helper.setUp()
        self.helpers.append(helper)
        helper.manifest = self.manifest
        (helper.design_root / "top.sv").write_text(
            "module gcd(input logic clk, input logic a, output logic y); "
            "always_ff @(posedge clk) y <= a; endmodule\n",
            encoding="utf-8",
        )
        policy, contract, capabilities, input_evidence, a02_approval = helper.context()

        def a02_runner(command, **kwargs):
            work = Path(kwargs["cwd"])
            if Path(command[0]).stem == "yosys":
                (work / "netlist.v").write_text("module gcd(); endmodule\n", encoding="utf-8")
                (work / "synthesis-stat.json").write_text(
                    json.dumps({"modules": {"gcd": {"num_cells": 12, "area": 10.0}}}),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, "synthesis complete\n", "")
            return subprocess.CompletedProcess(
                command,
                0,
                "worst slack 0.125\ntns 0.0\nDesign area 10.2 u^2 10% utilization.\n",
                "",
            )

        a02_evidence = helper.execute(runner=a02_runner, now=executed_at - timedelta(minutes=30))
        temporary = tempfile.TemporaryDirectory()
        self.directories.append(temporary)
        physical_run = Path(temporary.name) / "run"
        config = self.physical_config()
        physical_approval = {
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
            "backend_contract_id": contract["contract_id"],
            "capability_id": capabilities["capability_id"],
            "input_evidence_id": input_evidence["evidence_id"],
            "a02_evidence_id": a02_evidence["evidence_id"],
            "physical_config_sha256": physical.config_sha256(config),
        }
        physical_evidence = physical.run_physical(
            config,
            self.manifest(),
            policy,
            contract,
            capabilities,
            input_evidence,
            a02_evidence,
            a02_approval,
            physical_approval,
            repository_root=ROOT,
            pdk_root=helper.pdk_root,
            design_root=helper.design_root,
            a02_run_directory=helper.run_parent / "run",
            run_directory=physical_run,
            runner=self.physical_runner(area, label),
            resolver=helper.tools.get,
            now=executed_at,
        )
        lvs_report = physical_run / "lvs.lvsdb"
        artifacts = {item["role"]: item for item in physical_evidence["artifacts"]}
        checked_at = executed_at + timedelta(minutes=15)
        lvs_receipt = {
            "schema_version": 1,
            "receipt_id": "",
            "status": "PASS",
            "checker_id": "klayout",
            "checker_version": "1.5.270",
            "checked_at": checked_at.isoformat().replace("+00:00", "Z"),
            "reviewed_by": "asic-signoff-owner",
            "pdk_input_evidence_id": input_evidence["evidence_id"],
            "gds_sha256": artifacts["gds"]["sha256"],
            "reference_netlist_sha256": artifacts["lvs_reference"]["sha256"],
            "lvs_rules_sha256": {
                item["role"]: item for item in input_evidence["pdk"]["views"]
            }["lvs_rules"]["sha256"],
            "top_cell": "gcd",
            "report_path": "lvs.lvsdb",
            "report_sha256": backend._sha256_file(lvs_report),
            "report_bytes": lvs_report.stat().st_size,
            "layout_instance_count": 12,
            "schematic_instance_count": 12,
            "mismatched_nets": 0,
            "mismatched_devices": 0,
        }
        lvs_receipt["receipt_id"] = physical._content_id(lvs_receipt, "receipt_id")
        final_manifest = physical.finalize_manifest(
            physical_evidence,
            lvs_receipt,
            policy,
            contract,
            capabilities,
            input_evidence,
            a02_evidence,
            a02_approval,
            physical_approval,
            config,
            run_directory=physical_run,
            now=checked_at,
        )
        return {
            "run_label": label,
            "policy": policy,
            "contract": contract,
            "capabilities": capabilities,
            "input_manifest": self.manifest(),
            "input_evidence": input_evidence,
            "a02_evidence": a02_evidence,
            "a02_approval": a02_approval,
            "physical_config": config,
            "physical_approval": physical_approval,
            "physical_evidence": physical_evidence,
            "lvs_receipt": lvs_receipt,
            "final_manifest": final_manifest,
            "pdk_root": helper.pdk_root,
            "design_root": helper.design_root,
            "a02_run_directory": helper.run_parent / "run",
            "physical_run_directory": physical_run,
        }

    def make_review(self):
        inputs = self.baseline["input_evidence"]
        capabilities = {
            item["name"]: item for item in self.baseline["capabilities"]["tools"]
        }
        design_license = b"BSD 3-Clause License\n"
        value = {
            "schema_version": 1,
            "review_id": "",
            "status": "APPROVED",
            "profile_id": acceptance.PROFILE_ID,
            "reviewed_by": "independent-asic-acceptance-owner",
            "reviewed_at": "2026-09-09T13:00:00Z",
            "design": {
                "source_origin": self.profile["reference"]["design_source_origin"],
                "source_revision": self.profile["reference"]["orfs_revision"],
                "spdx_id": "BSD-3-Clause",
                "license_review_status": "APPROVED",
                "license_sha256": "sha256:" + hashlib.sha256(design_license).hexdigest(),
                "license_bytes": len(design_license),
                "source_manifest_sha256": inputs["design"]["source_manifest_sha256"],
                "constraints_sha256": inputs["design"]["constraints_sha256"],
            },
            "pdk": {
                "source_origin": inputs["pdk"]["source_origin"],
                "source_revision": inputs["pdk"]["source_revision"],
                "spdx_id": inputs["pdk"]["license"]["spdx_id"],
                "license_review_status": "APPROVED",
                "license_sha256": inputs["pdk"]["license"]["sha256"],
                "license_bytes": inputs["pdk"]["license"]["bytes"],
            },
            "toolchain": {
                "build_provenance_id": self.provenance["provenance_id"],
                "diagnostic_overrides": [],
                "tools": [
                    {
                        "name": name,
                        "version": capabilities[name]["version"],
                        "binary_sha256": capabilities[name]["binary_sha256"],
                        "source_revision": self.profile["reference"][
                            "tool_source_revisions"
                        ].get(name),
                    }
                    for name in ("yosys", "openroad", "strmrun")
                ],
            },
            "retention": {
                "raw_artifacts_mode": "EXTERNAL_ONLY",
                "retention_days": 30,
                "repository_content": "HASHES_AND_SANITIZED_EVIDENCE_ONLY",
                "public_artifact_export": False,
                "commercial_pdk_present": False,
                "customer_rtl_present": False,
                "model_context_export": False,
            },
        }
        value["review_id"] = acceptance._content_id(value, "review_id")
        return value

    def make_provenance(self):
        capabilities = {
            item["name"]: item for item in self.baseline["capabilities"]["tools"]
        }
        value = {
            "schema_version": 1,
            "provenance_id": "",
            "profile_id": acceptance.PROFILE_ID,
            "profile_sha256": toolchain_provenance._sha256_value(self.profile),
            "status": toolchain_provenance.STATUS,
            "source_build": {
                "mode": "LOCAL_SOURCE_BUILD",
                "orfs_revision": self.profile["reference"]["orfs_revision"],
                "openroad_revision": self.profile["reference"]["tool_source_revisions"][
                    "openroad"
                ],
                "yosys_revision": self.profile["reference"]["tool_source_revisions"]["yosys"],
                "build_launcher_sha256": "sha256:" + "1" * 64,
                "dependency_prefixes_sha256": "sha256:" + "2" * 64,
                "kepler_formal": "NOT_REQUIRED_FOR_A04_RTL_TO_GDS",
            },
            "tools": [
                {
                    "name": name,
                    "version": capabilities[name]["version"],
                    "binary_sha256": capabilities[name]["binary_sha256"],
                    "source_revision": self.profile["reference"]["tool_source_revisions"].get(
                        name
                    ),
                }
                for name in ("yosys", "openroad", "strmrun")
            ],
            "diagnostic_overrides": [],
            "compatibility_gate": {
                "design_id": self.profile["reference"]["design_id"],
                "target": "floorplan",
                "result_status": "PASS",
                "command_requirements": {
                    "repair_tie_fanout": True,
                    "replace_arith_modules": True,
                },
                "vars_sha256": "sha256:" + "3" * 64,
                "floorplan_odb_sha256": "sha256:" + "4" * 64,
                "floorplan_sdc_sha256": "sha256:" + "5" * 64,
            },
            "repository_content": "HASHES_AND_SANITIZED_EVIDENCE_ONLY",
        }
        value["provenance_id"] = toolchain_provenance._content_id(value)
        return value

    def build(self, baseline=None, replay=None, review=None, provenance=None):
        return acceptance.build_acceptance(
            self.profile,
            self.baseline if baseline is None else baseline,
            self.replay if replay is None else replay,
            self.review if review is None else review,
            self.provenance if provenance is None else provenance,
            repository_root=ROOT,
            now=ASSESSMENT_TIME,
        )

    def test_profile_passes_two_independent_chains_and_schema(self):
        result = self.build()
        self.assertEqual(result["result_status"], "PASS")
        self.assertEqual(result["next_gate"], "P4_ASIC_REFERENCE_ACCEPTED")
        self.assertEqual(len(result["safety_negatives"]), 6)
        self.assertTrue(all(item["observed"] == "REJECTED" for item in result["safety_negatives"]))
        self.assertFalse(result["real_execution_performed_by_assessor"])
        schema = json.loads(
            (ROOT / "schemas/asic_reproduction_acceptance.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(schema).validate(result)

    def test_same_run_or_metric_drift_blocks_acceptance(self):
        replay = copy.copy(self.baseline)
        replay["run_label"] = "replay"
        result = self.build(replay=replay)
        self.assertEqual(result["result_status"], "BLOCKED")
        self.assertEqual(result["checks"]["independent_runs"], "FAIL")
        far_replay = self.make_chain("replay", datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc), area=11.0)
        result = self.build(replay=far_replay)
        self.assertEqual(result["checks"]["metric_reproduction"], "FAIL")
        self.assertEqual(result["next_gate"], "A04_REMEDIATE_AND_RERUN")

    def test_source_profile_license_and_retention_fail_closed(self):
        changed = copy.deepcopy(self.profile)
        changed["reference"]["pdk_id"] = "commercial-pdk"
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "reviewed fixed profile"):
            acceptance.validate_profile(changed)
        review = copy.deepcopy(self.review)
        review["retention"]["commercial_pdk_present"] = True
        review["review_id"] = acceptance._content_id(review, "review_id")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "data-boundary"):
            self.build(review=review)

    def test_orfs_toolchain_revision_binary_and_override_drift_fail_closed(self):
        review = copy.deepcopy(self.review)
        review["design"]["source_revision"] = "3" * 40
        review["review_id"] = acceptance._content_id(review, "review_id")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "source or license"):
            self.build(review=review)

        review = copy.deepcopy(self.review)
        review["pdk"]["source_revision"] = "3" * 40
        review["review_id"] = acceptance._content_id(review, "review_id")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "source or license"):
            self.build(review=review)

        review = copy.deepcopy(self.review)
        review["toolchain"]["tools"][1]["source_revision"] = "4" * 40
        review["review_id"] = acceptance._content_id(review, "review_id")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "source revision"):
            self.build(review=review)

        review = copy.deepcopy(self.review)
        review["toolchain"]["tools"][1]["binary_sha256"] = "sha256:" + "5" * 64
        review["review_id"] = acceptance._content_id(review, "review_id")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "build provenance"):
            self.build(review=review)

        review = copy.deepcopy(self.review)
        review["toolchain"]["diagnostic_overrides"] = ["SKIP_REPAIR_TIE_FANOUT=1"]
        review["review_id"] = acceptance._content_id(review, "review_id")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "diagnostic overrides"):
            self.build(review=review)

        review = copy.deepcopy(self.review)
        review["toolchain"]["build_provenance_id"] = "sha256:" + "7" * 64
        review["review_id"] = acceptance._content_id(review, "review_id")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "does not bind"):
            self.build(review=review)

    def test_final_reviewer_must_be_independent_and_after_lvs(self):
        review = copy.deepcopy(self.review)
        review["reviewed_by"] = self.baseline["physical_approval"]["approved_by"]
        review["review_id"] = acceptance._content_id(review, "review_id")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "independent"):
            self.build(review=review)
        review = copy.deepcopy(self.review)
        review["reviewed_at"] = "2026-09-09T10:30:00Z"
        review["review_id"] = acceptance._content_id(review, "review_id")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "after both"):
            self.build(review=review)

    def test_raw_artifact_drift_is_rebuilt(self):
        (self.replay["physical_run_directory"] / "final.gds").write_text("drifted\n", encoding="utf-8")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "artifact drift"):
            self.build()

    def test_acceptance_tamper_and_recomputed_status_are_rejected(self):
        result = self.build()
        result["security"]["customer_rtl_present"] = True
        result["acceptance_id"] = acceptance._content_id(result, "acceptance_id")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "semantics"):
            acceptance.validate_acceptance(result, self.profile, self.review, self.provenance)
        result = self.build()
        result["checks"]["independent_runs"] = "FAIL"
        result["result_status"] = "BLOCKED"
        result["next_gate"] = "A04_REMEDIATE_AND_RERUN"
        result["closure_status"] = "A04_ENGINEERING_COMPLETE"
        result["acceptance_id"] = acceptance._content_id(result, "acceptance_id")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "checks"):
            acceptance.validate_acceptance(result, self.profile, self.review, self.provenance)
        result = self.build()
        result["runs"][1]["input_evidence_id"] = "sha256:" + "9" * 64
        result["acceptance_id"] = acceptance._content_id(result, "acceptance_id")
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "share input"):
            acceptance.validate_acceptance(result, self.profile, self.review, self.provenance)

    def test_templates_are_non_authorizing_and_cli_is_standalone(self):
        review = json.loads(
            (ROOT / "templates/asic_reproduction_review.template.json").read_text(encoding="utf-8")
        )
        with self.assertRaises(acceptance.AsicReproductionError):
            acceptance.validate_review(review, self.profile, now=ASSESSMENT_TIME)
        descriptor = ROOT / "templates/asic_reproduction_run.template.json"
        with self.assertRaisesRegex(acceptance.AsicReproductionError, "outside"):
            acceptance.load_chain_descriptor(descriptor, ROOT)
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/asic_reproduction_acceptance.py"), "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("baseline-descriptor", completed.stdout)


if __name__ == "__main__":
    unittest.main()
