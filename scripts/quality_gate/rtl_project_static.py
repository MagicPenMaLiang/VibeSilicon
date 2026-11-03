"""Source-bound readability and heuristic ASYNC_REG checks for project G1."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.quality_gate.rtl_manifest import ManifestError
from scripts.quality_gate.rtl_project_lint import _hash_sources
from scripts.quality_gate.rtl_readability import analyze
from scripts.quality_gate.scan_async_reg import scan_file


def run_static_checks(manifest: dict, *, repository_root: Path, source_hashes: dict) -> dict:
    """Check the same bytes as G0 and Verilator, after waiver validation."""
    root = repository_root.resolve(strict=True)
    if _hash_sources(root, manifest) != source_hashes:
        raise ManifestError("source changed before G1 static checks")
    findings = []
    blocking = warnings = waived = missing = 0
    for source in manifest["sources"] + manifest["headers"]:
        path = root / source
        report = analyze(path, root=root)
        blocking += report["summary"]["blocking"]
        warnings += report["summary"]["warnings"]
        waived += report["summary"]["waived"]
        for finding in report["violations"]:
            if not finding["waived"]:
                findings.append({
                    "level": "error" if finding["severity"] == "ERROR" else "warning",
                    "rule_id": finding["rule_id"], "message_code": "RTL_READABILITY",
                    "file": source, "line": finding["line"], "column": 1,
                })
        for finding in scan_file(path):
            missing += 1
            findings.append({
                "level": "error", "rule_id": "ASYNC-REG", "message_code": "ASYNC_REG_MISSING",
                "file": source, "line": finding["line"], "column": 1,
            })
    if _hash_sources(root, manifest) != source_hashes:
        raise ManifestError("source changed during G1 static checks")
    findings.sort(key=lambda item: (item["file"], item["line"], item["column"], item["rule_id"]))
    result = {
        "status": "FAIL" if blocking or missing else "PASS",
        "source_sha256": source_hashes,
        "readability": {"blocking": blocking, "warnings": warnings, "waived": waived},
        "async_reg": {"missing": missing, "files_scanned": len(manifest["sources"] + manifest["headers"])},
        "findings": findings,
        "limitations": ["heuristic static checks; not CDC correctness or product signoff"],
    }
    result["evidence_id"] = "sha256:" + hashlib.sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return result
