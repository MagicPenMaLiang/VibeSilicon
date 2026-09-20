#!/usr/bin/env python3
"""Run a project RTL G0/G1/G2 directed smoke without claiming product signoff."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from scripts.quality_gate.rtl_gate_evidence import (
    build_bundle, emit_github_annotations, summary as evidence_summary,
)
from scripts.quality_gate.rtl_manifest import ManifestError, validate_manifest
from scripts.quality_gate.rtl_project_lint import run_lint
from scripts.quality_gate.rtl_project_smoke import run_project
from scripts.quality_gate.rtl_quality_config import RtlQualityConfigError
from scripts.quality_gate.rtl_supplemental_policy import (
    maintenance_snapshot, validate_domain_evidence, validate_generated_provenance,
)
from scripts.quality_gate.rtl_waiver_registry import WaiverRegistryError, validate_waivers


ROOT = Path(__file__).resolve().parents[2]


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def run_gates(manifest_path: Path, *, repository_root: Path = ROOT) -> dict:
    root = repository_root.resolve(strict=True)
    manifest = validate_manifest(manifest_path, repository_root=root)
    manifest_file = manifest_path if manifest_path.is_absolute() else root / manifest_path
    manifest_relative = manifest_file.resolve(strict=True).relative_to(root).as_posix()
    manifest_sha256 = _sha(manifest_file.read_bytes())
    waiver_path = Path(manifest["project_root"]) / "rtl_quality_waivers.json"
    contract_path = Path(manifest["project_root"]) / "rtl_simulation_contract.json"
    result = {
        "schema_version": 1,
        "gate": "G0_G1_G2_PROJECT_RTL",
        "target": manifest["target"],
        "top": manifest["top"],
        "status": "BLOCKED",
        "checks": {"g0": "NOT_RUN", "g1": "NOT_RUN", "g2": "NOT_RUN"},
        "g2_evidence_id": None,
        "waiver_sha256": None,
        "supplemental": {
            "maintenance_evidence_id": None,
            "generated_provenance": "NOT_RUN",
            "domain_evidence": "NOT_RUN",
        },
    }
    waiver_result = None
    lint = None
    smoke = None
    blocked_gate = None
    try:
        maintenance = maintenance_snapshot(manifest_path, repository_root=root)
        result["supplemental"]["maintenance_evidence_id"] = maintenance["evidence_id"]
        generated = validate_generated_provenance(manifest_path, repository_root=root)
        result["supplemental"]["generated_provenance"] = generated["status"]
        waiver_result = validate_waivers(manifest_path, repository_root=root)
        result["checks"]["g0"] = "PASS"
        result["waiver_sha256"] = _sha((root / waiver_path).read_bytes())
        lint = run_lint(manifest_path, repository_root=root, include_warning_headers=True)
        result["checks"]["g1"] = lint["status"]
        if lint["status"] != "PASS":
            result["status"] = "FAIL"
        else:
            domains = validate_domain_evidence(manifest_path, repository_root=root)
            result["supplemental"]["domain_evidence"] = domains["status"]
            smoke = run_project(manifest_path, contract_path, repository_root=root)
            result["checks"]["g2"] = smoke["status"]
            result["g2_evidence_id"] = smoke["evidence_id"]
            result["status"] = smoke["status"]
    except (ManifestError, WaiverRegistryError, RtlQualityConfigError, OSError,
            UnicodeError, ValueError, KeyError, TypeError) as exc:
        result["status"] = "BLOCKED"
        blocked_gate = next(key for key, value in result["checks"].items() if value == "NOT_RUN")
        result["blocked_gate"] = blocked_gate
        result["reason_code"] = type(exc).__name__
    bundle = build_bundle(
        manifest_path=manifest_relative, manifest=manifest, manifest_sha256=manifest_sha256,
        waiver_sha256=result["waiver_sha256"], waiver_result=waiver_result,
        lint_report=lint, smoke_report=smoke, checks=result["checks"],
        status=result["status"], blocked_gate=blocked_gate,
    )
    result["unified_evidence_id"] = bundle["evidence_id"]
    result["evidence_bundle"] = bundle
    result["evidence_id"] = _sha(json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return result


def _summary(result: dict) -> str:
    return evidence_summary(result["evidence_bundle"])


def _write_summary(markdown: str) -> None:
    destination = os.environ.get("GITHUB_STEP_SUMMARY")
    if destination:
        with Path(destination).open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(markdown)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        result = run_gates(args.manifest, repository_root=args.repository_root)
        _write_summary(_summary(result))
        emit_github_annotations(result["evidence_bundle"])
    except (ManifestError, OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("::error title=Project RTL gate::BLOCKED; see the step log")
        print(json.dumps({"gate": "G0_G1_G2_PROJECT_RTL", "status": "BLOCKED",
                          "reason_code": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    if result["status"] != "PASS" and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::error title=Project RTL gate::{result['status']}; see the job summary")
    return 0 if result["status"] == "PASS" else 2 if result["status"] == "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
