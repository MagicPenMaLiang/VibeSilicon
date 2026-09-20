import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

from scripts import asic_backend_contract as backend
from scripts import asic_input_evidence as evidence


ROOT = Path(__file__).resolve().parents[1]


class AsicInputEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.pdk_temporary = tempfile.TemporaryDirectory()
        self.design_temporary = tempfile.TemporaryDirectory()
        self.pdk_root = Path(self.pdk_temporary.name)
        self.design_root = Path(self.design_temporary.name)
        pdk_files = {
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
                        {"net": "VSS", "pin": "VGND", "type": "GROUND"},
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
        for name, content in pdk_files.items():
            (self.pdk_root / name).write_text(content, encoding="utf-8")
        (self.design_root / "top.sv").write_text(
            "module top(input logic a, output logic y); assign y = a; endmodule\n",
            encoding="utf-8",
        )
        (self.design_root / "design.sdc").write_text(
            "create_clock -period 10 [get_ports a]\n", encoding="utf-8"
        )

    def tearDown(self):
        self.design_temporary.cleanup()
        self.pdk_temporary.cleanup()

    def policy(self):
        return json.loads(
            (ROOT / "config/asic_backend_policy.json").read_text(encoding="utf-8")
        )

    def contract(self):
        return backend.build_contract(self.policy())

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

    def test_human_reviewer_name_is_accepted(self):
        manifest = self.manifest()
        manifest["pdk"]["license"]["reviewed_by"] = "Reviewer"

        result = evidence.build_evidence(
            manifest,
            self.policy(),
            self.contract(),
            repository_root=ROOT,
            pdk_root=Path(self.pdk_temporary.name),
            design_root=Path(self.design_temporary.name),
        )

        self.assertEqual(result["pdk"]["license"]["reviewed_by"], "Reviewer")

    def build(self, manifest=None):
        return evidence.build_evidence(
            self.manifest() if manifest is None else manifest,
            self.policy(),
            self.contract(),
            repository_root=ROOT,
            pdk_root=self.pdk_root,
            design_root=self.design_root,
        )

    def test_valid_external_inputs_build_sanitized_content_addressed_evidence(self):
        result = self.build()
        self.assertEqual(result["status"], "A01_INPUTS_VERIFIED_UNEXECUTED")
        self.assertEqual(result["closure_status"], "A01_ENGINEERING_COMPLETE")
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["pdk"]["storage"]["file_count"], 15)
        serialized = json.dumps(result)
        self.assertNotIn(str(self.pdk_root), serialized)
        self.assertNotIn(str(self.design_root), serialized)
        self.assertNotIn("module top", serialized)
        evidence.validate_evidence(result, self.policy(), self.contract())
        schema = json.loads(
            (ROOT / "schemas/asic_input_evidence.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.Draft202012Validator(schema).validate(result)

    def test_template_and_unreviewed_license_fail_closed(self):
        template = json.loads(
            (ROOT / "templates/asic_input_manifest.template.json").read_text(
                encoding="utf-8"
            )
        )
        with self.assertRaisesRegex(evidence.AsicInputError, "placeholder"):
            self.build(template)
        manifest = self.manifest()
        manifest["pdk"]["license"]["review_status"] = "REQUIRED"
        with self.assertRaisesRegex(evidence.AsicInputError, "APPROVED"):
            self.build(manifest)

    def test_missing_or_duplicate_view_fails_closed(self):
        manifest = self.manifest()
        manifest["pdk"]["views"].pop()
        with self.assertRaisesRegex(evidence.AsicInputError, "each required role"):
            self.build(manifest)
        manifest = self.manifest()
        manifest["pdk"]["views"][1]["path"] = "tech.lef"
        with self.assertRaisesRegex(evidence.AsicInputError, "distinct files"):
            self.build(manifest)

    def test_path_escape_and_repository_root_are_rejected(self):
        manifest = self.manifest()
        manifest["design"]["sources"] = ["../top.sv"]
        with self.assertRaisesRegex(evidence.AsicInputError, "traversal"):
            self.build(manifest)
        with self.assertRaisesRegex(evidence.AsicInputError, "disjoint"):
            evidence.build_evidence(
                self.manifest(),
                self.policy(),
                self.contract(),
                repository_root=ROOT,
                pdk_root=ROOT,
                design_root=self.design_root,
            )

    def test_source_change_changes_evidence_identity(self):
        first = self.build()
        (self.design_root / "top.sv").write_text(
            "module top(input logic a, output logic y); assign y = ~a; endmodule\n",
            encoding="utf-8",
        )
        second = self.build()
        self.assertNotEqual(first["evidence_id"], second["evidence_id"])
        self.assertNotEqual(
            first["design"]["source_manifest_sha256"],
            second["design"]["source_manifest_sha256"],
        )

    def test_tamper_and_backend_contract_drift_are_rejected(self):
        result = self.build()
        changed = copy.deepcopy(result)
        changed["execution_authorized"] = True
        with self.assertRaisesRegex(evidence.AsicInputError, "content ID"):
            evidence.validate_evidence(changed, self.policy(), self.contract())
        changed = copy.deepcopy(result)
        changed["backend_contract_id"] = "sha256:" + "0" * 64
        changed["evidence_id"] = evidence._content_id(changed, "evidence_id")
        with self.assertRaisesRegex(evidence.AsicInputError, "reviewed semantics"):
            evidence.validate_evidence(changed, self.policy(), self.contract())
        changed = copy.deepcopy(result)
        changed["pdk"]["storage"]["total_bytes"] += 1
        changed["evidence_id"] = evidence._content_id(changed, "evidence_id")
        with self.assertRaisesRegex(evidence.AsicInputError, "total_bytes mismatch"):
            evidence.validate_evidence(changed, self.policy(), self.contract())

    def test_cli_build_verify_is_exclusive_and_has_no_execution_surface(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            (root / "inputs").mkdir()
            (root / "config" / "asic_backend_policy.json").write_text(
                json.dumps(self.policy()), encoding="utf-8"
            )
            (root / "inputs" / "backend.json").write_text(
                json.dumps(self.contract()), encoding="utf-8"
            )
            (root / "inputs" / "manifest.json").write_text(
                json.dumps(self.manifest()), encoding="utf-8"
            )
            arguments = [
                "build",
                "inputs/manifest.json",
                "--root",
                str(root),
                "--backend-contract",
                "inputs/backend.json",
                "--pdk-root",
                str(self.pdk_root),
                "--design-root",
                str(self.design_root),
                "--output",
                "results/evidence.json",
            ]
            self.assertEqual(evidence.main(arguments), 0)
            self.assertEqual(evidence.main(arguments), 2)
            verify = [
                "verify",
                "results/evidence.json",
                "--root",
                str(root),
                "--backend-contract",
                "inputs/backend.json",
            ]
            self.assertEqual(evidence.main(verify), 0)
        source = (ROOT / "scripts/asic_input_evidence.py").read_text(encoding="utf-8")
        self.assertIn('choices=("build", "verify")', source)
        self.assertNotIn("execute", source)
        standalone = subprocess.run(
            [sys.executable, "scripts/asic_input_evidence.py", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(standalone.returncode, 0, standalone.stderr)


if __name__ == "__main__":
    unittest.main()
