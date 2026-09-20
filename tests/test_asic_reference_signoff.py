import copy
import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from scripts import asic_reference_signoff as signoff
from tests import test_asic_toolchain_provenance as provenance_tests


class AsicReferenceSignoffTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile = {
            "schema_version": 1,
            "profile_id": "orfs-sky130hd-gcd-v1",
            "reference": {
                "design_id": "orfs-sky130hd-gcd",
                "orfs_revision": provenance_tests.ORFS,
                "tool_source_revisions": {
                    "openroad": provenance_tests.OPENROAD,
                    "yosys": provenance_tests.YOSYS,
                },
            },
        }
        helper = provenance_tests.AsicToolchainProvenanceTests(methodName="runTest")
        helper.setUp()
        self.addCleanup(helper.tearDown)
        helper.profile = copy.deepcopy(self.profile)
        self.toolchain = helper.collect()
        self.metrics = self.root / "6_report.json"
        self.metrics.write_text(
            json.dumps(
                {
                    "finish__timing__setup__ws": -1.46486,
                    "finish__timing__setup__tns": -65.0932,
                    "finish__timing__drv__setup_violation_count": 63,
                    "finish__timing__hold__tns": 0,
                    "finish__timing__drv__hold_violation_count": 0,
                    "finish__design__instance__area__stdcell": 5412.69,
                    "finish__power__total": 0.00985767,
                }
            ),
            encoding="utf-8",
        )
        self.clock = self.root / "clock_period.txt"
        self.clock.write_text("1.1\n", encoding="utf-8")
        self.drc = self.root / "6_drc_count.rpt"
        self.drc.write_text("0\n", encoding="utf-8")
        self.lvs_log = self.root / "6_lvs.log"
        self.lvs_log.write_text(
            "INFO : Congratulations! Netlists match.\n", encoding="utf-8"
        )
        self.artifacts = {}
        for name in ("final_gds", "signoff_drc_db", "lvs_db", "final_odb"):
            path = self.root / name
            path.write_bytes((name + "\n").encode())
            self.artifacts[name] = path

    def tearDown(self):
        self.temporary.cleanup()

    def collect(self):
        return signoff.collect_reference_signoff(
            self.profile,
            self.toolchain,
            variant="e08-matched-signoff-1",
            metrics_json=self.metrics,
            clock_period_report=self.clock,
            drc_count_report=self.drc,
            lvs_log=self.lvs_log,
            final_gds=self.artifacts["final_gds"],
            signoff_drc_db=self.artifacts["signoff_drc_db"],
            lvs_db=self.artifacts["lvs_db"],
            final_odb=self.artifacts["final_odb"],
        )

    def test_collects_physical_clean_timing_blocked_diagnostic(self):
        result = self.collect()
        signoff.validate_reference_signoff(result, self.profile, self.toolchain)
        schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "schemas/asic_reference_signoff.schema.json"
            ).read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator(schema).validate(result)
        self.assertEqual(result["status"], signoff.STATUS)
        self.assertTrue(result["checks"]["physical_signoff_clean"])
        self.assertFalse(result["checks"]["timing_clean"])
        self.assertEqual(result["limitations"], signoff.LIMITATIONS)
        serialized = json.dumps(result)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("Congratulations", serialized)

    def test_missing_metric_and_false_lvs_do_not_pass(self):
        raw = json.loads(self.metrics.read_text(encoding="utf-8"))
        del raw["finish__power__total"]
        self.metrics.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(signoff.AsicReferenceSignoffError, "missing"):
            self.collect()

        raw["finish__power__total"] = 0.00985767
        self.metrics.write_text(json.dumps(raw), encoding="utf-8")
        self.lvs_log.write_text(
            "INFO : Congratulations! Netlists match.\nERROR mismatch\n",
            encoding="utf-8",
        )
        result = self.collect()
        self.assertFalse(result["checks"]["lvs_clean"])
        self.assertFalse(result["checks"]["physical_signoff_clean"])

    def test_invalid_drc_variant_and_toolchain_fail_closed(self):
        self.drc.write_text("DRC=0\n", encoding="utf-8")
        with self.assertRaisesRegex(signoff.AsicReferenceSignoffError, "DRC count"):
            self.collect()
        self.drc.write_text("0\n", encoding="utf-8")
        with self.assertRaisesRegex(signoff.AsicReferenceSignoffError, "variant"):
            signoff.collect_reference_signoff(
                self.profile,
                self.toolchain,
                variant="../escape",
                metrics_json=self.metrics,
                clock_period_report=self.clock,
                drc_count_report=self.drc,
                lvs_log=self.lvs_log,
                final_gds=self.artifacts["final_gds"],
                signoff_drc_db=self.artifacts["signoff_drc_db"],
                lvs_db=self.artifacts["lvs_db"],
                final_odb=self.artifacts["final_odb"],
            )
        changed = copy.deepcopy(self.toolchain)
        changed["provenance_id"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(signoff.AsicReferenceSignoffError, "content ID"):
            signoff.validate_reference_signoff(self.collect(), self.profile, changed)

    def test_tampered_derivation_and_acceptance_claim_fail_closed(self):
        result = self.collect()
        changed = copy.deepcopy(result)
        changed["checks"]["timing_clean"] = True
        changed["evidence_id"] = signoff._content_id(changed)
        with self.assertRaisesRegex(signoff.AsicReferenceSignoffError, "derivation"):
            signoff.validate_reference_signoff(changed, self.profile, self.toolchain)

        changed = copy.deepcopy(result)
        changed["limitations"] = changed["limitations"][:-1]
        changed["evidence_id"] = signoff._content_id(changed)
        with self.assertRaisesRegex(signoff.AsicReferenceSignoffError, "limitations"):
            signoff.validate_reference_signoff(changed, self.profile, self.toolchain)


if __name__ == "__main__":
    unittest.main()
