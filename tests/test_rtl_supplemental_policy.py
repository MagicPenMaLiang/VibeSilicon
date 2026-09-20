"""Supplemental RTL policies remain source-bound, shadow-only or fail-closed."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.quality_gate import rtl_supplemental_policy as policy


MANIFEST = Path("project/demo/rtl_project_manifest.json")
SOURCE = "project/demo/rtl/demo.sv"


class RtlSupplementalPolicyTests(unittest.TestCase):
    def project(self, directory, *, kinds=None, clocks=None, resets=None, text="module demo; endmodule\n"):
        root = Path(directory)
        target = root / SOURCE
        target.parent.mkdir(parents=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        manifest = {
            "schema_version": 1, "project_root": "project/demo", "target": "fpga",
            "source_kinds": kinds or ["handwritten"], "top": "demo",
            "source_roots": ["project/demo/rtl"], "sources": [SOURCE], "headers": [],
            "include_dirs": ["project/demo/rtl"], "defines": {}, "parameters": {},
            "clocks": clocks or [], "resets": resets or [],
        }
        path = root / MANIFEST
        path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
        return root, path, target

    def test_maintenance_findings_are_bounded_shadow_evidence(self):
        text = "module demo;\n// TODO: unowned\n// FIXME(Reviewer): owned\n" + "begin\n" * 6 + "end\n" * 6 + "endmodule\n"
        with tempfile.TemporaryDirectory() as directory:
            root, _, _ = self.project(directory, text=text)
            report = policy.maintenance_snapshot(MANIFEST, repository_root=root)
        self.assertEqual(report["status"], "SHADOW")
        self.assertEqual(report["by_kind"]["UNOWNED_TODO"], 1)
        self.assertEqual(report["by_kind"]["OWNED_TODO"], 1)
        self.assertGreater(report["by_kind"]["NESTING_DEPTH"], 0)
        self.assertTrue(report["evidence_id"].startswith("sha256:"))
        self.assertIn("no Quality Gate threshold change", report["limitations"][0])

    def test_generated_source_requires_matching_approved_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _, source = self.project(directory, kinds=["generated"])
            with self.assertRaisesRegex(policy.SupplementalPolicyError, "requires"):
                policy.validate_generated_provenance(MANIFEST, repository_root=root)
            value = {
                "schema_version": 1,
                "generator": {"name": "demo-gen", "version": "1.0", "input_sha256": "sha256:" + "a" * 64},
                "generated_sources": [{"path": SOURCE, "sha256": policy._sha(source.read_bytes())}],
                "reproducible": True, "generated_by": "generator-owner",
                "approved_by": "Reviewer", "evidence_id": "",
            }
            value["evidence_id"] = policy._content_id(value)
            (root / "project/demo/rtl_generator_provenance.json").write_text(json.dumps(value), encoding="utf-8")
            self.assertEqual(policy.validate_generated_provenance(MANIFEST, repository_root=root)["status"], "PASS")
            value["approved_by"] = value["generated_by"]
            value["evidence_id"] = policy._content_id(value)
            (root / "project/demo/rtl_generator_provenance.json").write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(policy.SupplementalPolicyError, "independent approval"):
                policy.validate_generated_provenance(MANIFEST, repository_root=root)
            value["approved_by"] = "Reviewer"
            value["evidence_id"] = policy._content_id(value)
            (root / "project/demo/rtl_generator_provenance.json").write_text(json.dumps(value), encoding="utf-8")
            source.write_text("module changed; endmodule\n", encoding="utf-8")
            with self.assertRaisesRegex(policy.SupplementalPolicyError, "hash mismatch"):
                policy.validate_generated_provenance(MANIFEST, repository_root=root)

    def test_multidomain_without_real_cdc_rdc_evidence_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root, manifest_path, _ = self.project(directory, clocks=["a_clk", "b_clk"], resets=["a_rst_n", "b_rst_n"])
            with self.assertRaisesRegex(policy.SupplementalPolicyError, "requires CDC/RDC"):
                policy.validate_domain_evidence(MANIFEST, repository_root=root)
            manifest_hash = policy._sha(manifest_path.read_bytes())
            value = {
                "schema_version": 1, "top": "demo", "manifest_sha256": manifest_hash,
                "clocks": ["a_clk", "b_clk"], "resets": ["a_rst_n", "b_rst_n"],
                "tool": {"name": "reviewed-cdc", "version": "1.0"},
                "cdc_status": "PASS", "rdc_status": "PASS", "evidence_id": "",
            }
            value["evidence_id"] = policy._content_id(value)
            (root / "project/demo/rtl_domain_evidence.json").write_text(json.dumps(value), encoding="utf-8")
            self.assertEqual(policy.validate_domain_evidence(MANIFEST, repository_root=root)["status"], "PASS")
            value["rdc_status"] = "FAIL"
            value["evidence_id"] = policy._content_id(value)
            (root / "project/demo/rtl_domain_evidence.json").write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(policy.SupplementalPolicyError, "does not match"):
                policy.validate_domain_evidence(MANIFEST, repository_root=root)

    def test_single_domain_is_explicitly_not_applicable(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _, _ = self.project(directory, clocks=["clk"], resets=["rst_n"])
            result = policy.validate_domain_evidence(MANIFEST, repository_root=root)
        self.assertEqual(result, {"status": "NOT_APPLICABLE", "evidence_id": None})


if __name__ == "__main__":
    unittest.main()
