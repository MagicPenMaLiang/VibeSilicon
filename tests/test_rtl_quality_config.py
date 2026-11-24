import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.quality_gate import rtl_quality_config as config
from scripts.quality_gate import rtl_readability
from tests.test_rtl_readability import BROKEN_RTL, CLEAN_RTL


class RtlQualityConfigTests(unittest.TestCase):
    def _modified(self, source, mutator):
        """Load an edited copy *past* the byte pin so the content checks are what
        rejects it. Pinning the temp file's own hash is the only way to reach
        them; without this the rejection is the pin firing, and the test would
        pass even if every content rule were deleted."""
        payload = json.loads(source.read_text(encoding="utf-8"))
        mutator(payload)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / source.name
            path.write_text(json.dumps(payload), encoding="utf-8")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            # Patch only the pin of the file under test: load_policy() still
            # loads the real catalog, and must be able to.
            if source == config.CATALOG:
                with patch.object(config, "REVIEWED_CATALOG_SHA256", actual):
                    return config.load_catalog(path)
            with patch.object(config, "REVIEWED_POLICY_SHA256", actual):
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

    def test_readability_implementation_pin_matches_the_module_on_disk(self):
        """A stale pin must fail loudly here rather than at the first gate run."""
        actual = hashlib.sha256(config.READABILITY.read_bytes()).hexdigest()
        self.assertEqual(config.REVIEWED_READABILITY_SHA256, actual)
        self.assertEqual(config.READABILITY.name, "rtl_readability.py")

    def test_edited_readability_implementation_is_rejected(self):
        """Proves the pin is enforced, not merely stored: with a different
        expected hash the catalog refuses to load at all."""
        with patch.object(config, "REVIEWED_READABILITY_SHA256", "0" * 64):
            with self.assertRaises(config.RtlQualityConfigError):
                config.load_catalog()

    def test_duplicate_or_drifted_catalog_rule_rejected(self):
        with self.assertRaises(config.RtlQualityConfigError):
            self._modified(config.CATALOG, lambda data: data["rules"].append(dict(data["rules"][0])))
        with self.assertRaises(config.RtlQualityConfigError):
            self._modified(config.CATALOG, lambda data: data["rules"][0].update(severity="WARNING"))

    def test_standard_version_1_1_requires_the_domain_approval_check(self):
        policy = config.load_policy()
        self.assertEqual(policy["standard_version"], config.STANDARD_VERSION)
        self.assertIn("domain_approval", policy["gate_requirements"]["g2"])
        self.assertEqual(policy["standard_version"], "1.1")

    def test_unknown_gate_check_name_is_rejected(self):
        """A misspelt requirement would silently disable a gate, so the
        vocabulary is closed rather than free-form."""
        with self.assertRaises(config.RtlQualityConfigError):
            self._modified(config.POLICY, lambda data: data["gate_requirements"]["g2"].append("domain_approvel"))
        with self.assertRaises(config.RtlQualityConfigError):
            self._modified(config.POLICY, lambda data: data["gate_requirements"]["g2"].remove("domain_approval"))

    def test_unreviewed_threshold_and_activation_rejected(self):
        with self.assertRaises(config.RtlQualityConfigError):
            self._modified(config.POLICY, lambda data: data["legacy_gate_thresholds"].update(wns_ns_fail=-3.0))
        with self.assertRaises(config.RtlQualityConfigError):
            self._modified(config.POLICY, lambda data: data.update(activation="round2_project_gate"))
        with self.assertRaises(config.RtlQualityConfigError):
            self._modified(config.POLICY, lambda data: data["tool_versions"]["verilator"].update(accepted_major=[6]))

    def test_all_schema_files_are_json_and_waiver_requires_review_metadata(self):
        schema_dir = config.ROOT / "schemas"
        for name in ("rtl_quality_rules", "rtl_quality_policy", "rtl_quality_waiver",
                     "rtl_quality_signoff", "rtl_domain_evidence", "rtl_domain_approval"):
            with self.subTest(name=name):
                data = json.loads((schema_dir / f"{name}.schema.json").read_text(encoding="utf-8"))
                self.assertEqual(data["$schema"], "https://json-schema.org/draft/2020-12/schema")
        waiver = json.loads((schema_dir / "rtl_quality_waiver.schema.json").read_text(encoding="utf-8"))
        required = set(waiver["properties"]["waivers"]["items"]["required"])
        self.assertTrue({"owner", "approved_by", "expires_at_utc", "removal_condition", "compensating_verification"} <= required)


if __name__ == "__main__":
    unittest.main()
