"""G0 waiver registry must bind each inline finding to reviewed source bytes."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.quality_gate.rtl_waiver_registry import WaiverRegistryError, validate_waivers


RTL = """`default_nettype none
module top;
    // vibesilicon-waive RTL-R010 id=WAIVER-123 reason=debug-review
    (* MARK_DEBUG = "TRUE" *) logic debug_q;
endmodule
`default_nettype wire
"""
SOURCE = "project/demo/rtl/top.sv"
NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


class RtlWaiverRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / SOURCE
        self.source.parent.mkdir(parents=True)
        self.source.write_text(RTL, encoding="utf-8")
        self.manifest = self.root / "project/demo/rtl_project_manifest.json"
        self.manifest.write_text(json.dumps({
            "schema_version": 1,
            "project_root": "project/demo",
            "target": "fpga",
            "source_kinds": ["handwritten"],
            "top": "top",
            "source_roots": ["project/demo/rtl"],
            "sources": [SOURCE],
            "headers": [],
            "include_dirs": ["project/demo/rtl"],
            "defines": {},
            "parameters": {},
            "clocks": [],
            "resets": [],
        }), encoding="utf-8")
        self.waiver = {
            "id": "WAIVER-123", "rule_id": "RTL-R010", "source": SOURCE,
            "module": "top", "scope": "line:4", "owner": "Designer",
            "reason": "Temporary debug observation", "risk": "Extra logic may remain",
            "approved_by": "Reviewer", "approved_at_utc": "2026-09-16T00:00:00Z",
            "expires_at_utc": "2026-09-18T00:00:00Z",
            "removal_condition": "Remove after debug", "compensating_verification": "Review synthesis report",
            "source_sha256": "sha256:" + hashlib.sha256(self.source.read_bytes()).hexdigest(),
        }
        self.registry = self.root / "project/demo/rtl_quality_waivers.json"

    def check(self, waivers=None):
        self.registry.write_text(json.dumps({
            "schema_version": 1, "standard_version": "1.0",
            "waivers": [self.waiver] if waivers is None else waivers,
        }), encoding="utf-8")
        return validate_waivers(self.manifest, self.registry, repository_root=self.root, now=NOW)

    def test_exact_approved_waiver_passes(self):
        self.assertEqual(self.check(), {
            "status": "PASS", "gate": "G0_WAIVER_REGISTRY", "sources_checked": 1, "waivers_checked": 1,
        })

    def test_project_default_registry_passes(self):
        self.check()
        self.assertEqual(
            validate_waivers(self.manifest, repository_root=self.root, now=NOW)["waivers_checked"],
            1,
        )

    def test_missing_default_registry_blocks(self):
        with self.assertRaisesRegex(WaiverRegistryError, "missing registry"):
            validate_waivers(self.manifest, repository_root=self.root, now=NOW)

    def test_other_project_registry_blocks(self):
        other = self.root / "project/other/rtl_quality_waivers.json"
        other.parent.mkdir(parents=True)
        other.write_text(json.dumps({"schema_version": 1, "standard_version": "1.0", "waivers": []}), encoding="utf-8")
        with self.assertRaisesRegex(WaiverRegistryError, "inside manifest project_root"):
            validate_waivers(self.manifest, other, repository_root=self.root, now=NOW)

    def test_empty_registry_without_inline_marker_passes(self):
        self.source.write_text(RTL.replace("    // vibesilicon-waive RTL-R010 id=WAIVER-123 reason=debug-review\n", ""), encoding="utf-8")
        self.assertEqual(self.check([])["waivers_checked"], 0)

    def test_unregistered_marker_blocks(self):
        with self.assertRaisesRegex(WaiverRegistryError, "unregistered"):
            self.check([])

    def test_expired_or_future_approval_blocks(self):
        self.waiver["expires_at_utc"] = "2026-09-17T00:00:00Z"
        with self.assertRaisesRegex(WaiverRegistryError, "not currently approved"):
            self.check()
        self.waiver["expires_at_utc"] = "2026-09-18T00:00:00Z"
        self.waiver["approved_at_utc"] = "2026-09-18T00:00:00Z"
        with self.assertRaisesRegex(WaiverRegistryError, "not currently approved"):
            self.check()

    def test_source_edit_and_scope_drift_block(self):
        self.source.write_text(RTL + "// changed\n", encoding="utf-8")
        with self.assertRaisesRegex(WaiverRegistryError, "scope or source changed"):
            self.check()
        self.source.write_text(RTL, encoding="utf-8")
        self.waiver["scope"] = "line:3"
        with self.assertRaisesRegex(WaiverRegistryError, "scope or source changed"):
            self.check()

    def test_self_approval_and_unknown_rule_block(self):
        self.waiver["approved_by"] = "designer"
        with self.assertRaisesRegex(WaiverRegistryError, "independent approval"):
            self.check()
        self.waiver["approved_by"] = "Reviewer"
        self.waiver["rule_id"] = "RTL-R999"
        with self.assertRaisesRegex(WaiverRegistryError, "unknown or unimplemented rule"):
            self.check()

    def test_unused_duplicate_and_noncomment_marker_block(self):
        self.source.write_text(RTL.replace("    (* MARK_DEBUG = \"TRUE\" *) logic debug_q;", "    logic debug_q;"), encoding="utf-8")
        with self.assertRaisesRegex(WaiverRegistryError, "does not bind one finding"):
            self.check()
        self.source.write_text(RTL, encoding="utf-8")
        with self.assertRaisesRegex(WaiverRegistryError, "duplicate waiver ID"):
            self.check([self.waiver, self.waiver])
        self.source.write_text(RTL.replace("    // vibesilicon-waive", "    logic stray; // vibesilicon-waive"), encoding="utf-8")
        with self.assertRaisesRegex(WaiverRegistryError, "malformed waiver marker"):
            self.check()

    def test_invalid_marker_is_not_silently_ignored(self):
        self.source.write_text(RTL.replace("id=WAIVER-123", "id=bad"), encoding="utf-8")
        with self.assertRaisesRegex(WaiverRegistryError, "malformed waiver marker"):
            self.check([])

    def test_registry_escape_blocks(self):
        with self.assertRaisesRegex(WaiverRegistryError, "inside repository"):
            validate_waivers(self.manifest, self.root.parent / "outside.json", repository_root=self.root, now=NOW)


if __name__ == "__main__":
    unittest.main()
