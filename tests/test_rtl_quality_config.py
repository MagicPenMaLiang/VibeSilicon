import json
import tempfile
import unittest
from pathlib import Path

from scripts.quality_gate import rtl_quality_config as config
from scripts.quality_gate import rtl_readability
from tests.test_rtl_readability import BROKEN_RTL, CLEAN_RTL


class RtlQualityConfigTests(unittest.TestCase):
    def _modified(self, source, mutator):
        payload = json.loads(source.read_text(encoding="utf-8"))
        mutator(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / source.name
            path.write_text(json.dumps(payload), encoding="utf-8")
            if source == config.CATALOG:
                return config.load_catalog(path)
            return config.load_policy(path)

    def test_catalog_and_policy_validate(self):
        catalog = config.load_catalog()
        policy = config.load_policy(catalog=catalog)
        self.assertEqual(catalog["standard_version"], policy["standard_version"])
        self.assertEqual(policy["legacy_gate_thresholds"], config.LEGACY_THRESHOLDS)
        self.assertEqual(
            {rule["id"] for rule in catalog["rules"] if rule["verification"] == "automated"},
            set(rtl_readability.RULES) | config.SUPPLEMENTAL_AUTOMATED_RULES,
        )
        self.assertFalse(
            [rule["id"] for rule in catalog["rules"]
             if rule["level"] == "MUST" and rule["verification"] == "planned"]
        )
        memory_boundary = next(rule for rule in catalog["rules"] if rule["id"] == "RTL-MEM-002")
        self.assertEqual((memory_boundary["level"], memory_boundary["severity"], memory_boundary["verification"]), ("SHOULD", "WARNING", "manual"))

    def test_legacy_rules_have_matching_severity_and_positive_negative_fixtures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "good.sv"
            bad = root / "bad.sv"
            good.write_text(CLEAN_RTL, encoding="utf-8")
            bad.write_text(BROKEN_RTL, encoding="utf-8")
            good_ids = {row["rule_id"] for row in rtl_readability.analyze(good, root=root)["violations"]}
            bad_ids = {row["rule_id"] for row in rtl_readability.analyze(bad, root=root)["violations"]}
        self.assertFalse(good_ids)
        self.assertEqual(bad_ids, set(rtl_readability.RULES))

    def test_duplicate_or_drifted_catalog_rule_rejected(self):
        with self.assertRaises(config.RtlQualityConfigError):
            self._modified(config.CATALOG, lambda data: data["rules"].append(dict(data["rules"][0])))
        with self.assertRaises(config.RtlQualityConfigError):
            self._modified(config.CATALOG, lambda data: data["rules"][0].update(severity="WARNING"))

    def test_unreviewed_threshold_and_activation_rejected(self):
        with self.assertRaises(config.RtlQualityConfigError):
            self._modified(config.POLICY, lambda data: data["legacy_gate_thresholds"].update(wns_ns_fail=-3.0))
        with self.assertRaises(config.RtlQualityConfigError):
            self._modified(config.POLICY, lambda data: data.update(activation="round2_project_gate"))
        with self.assertRaises(config.RtlQualityConfigError):
            self._modified(config.POLICY, lambda data: data["tool_versions"]["verilator"].update(accepted_major=[6]))

    def test_all_schema_files_are_json_and_waiver_requires_review_metadata(self):
        schema_dir = config.ROOT / "schemas"
        for name in ("rtl_quality_rules", "rtl_quality_policy", "rtl_quality_waiver", "rtl_quality_signoff"):
            with self.subTest(name=name):
                data = json.loads((schema_dir / f"{name}.schema.json").read_text(encoding="utf-8"))
                self.assertEqual(data["$schema"], "https://json-schema.org/draft/2020-12/schema")
        waiver = json.loads((schema_dir / "rtl_quality_waiver.schema.json").read_text(encoding="utf-8"))
        required = set(waiver["properties"]["waivers"]["items"]["required"])
        self.assertTrue({"owner", "approved_by", "expires_at_utc", "removal_condition", "compensating_verification"} <= required)


if __name__ == "__main__":
    unittest.main()
