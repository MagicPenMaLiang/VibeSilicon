#!/usr/bin/env python3
"""Build, verify and render a bounded unified G0/G1/G2 RTL evidence bundle."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path


SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
RULE_ID = re.compile(r"[A-Z][A-Z0-9_-]{2,63}\Z")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*\Z")
STATUSES = {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}
GATES = ("G0", "G1", "G2")
MAX_ANNOTATIONS = 20


class GateEvidenceError(ValueError):
    """Unified evidence is malformed, inconsistent or tampered."""


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _content_id(value: dict) -> str:
    payload = json.dumps(
        {key: item for key, item in value.items() if key != "evidence_id"},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return _sha(payload)


def _stage(gate: str, status: str, *, metrics: dict, annotations: list[dict], finding_count: int | None = None) -> dict:
    value = {
        "gate": gate, "status": status, "evidence_id": None,
        "finding_count": len(annotations) if finding_count is None else finding_count,
        "metrics": metrics, "annotations": annotations,
    }
    if status != "NOT_RUN":
        value["evidence_id"] = _content_id(value)
    return value


def _lint_annotations(lint: dict | None, allowed_sources: set[str]) -> tuple[list[dict], int]:
    if lint is None:
        return [], 0
    items = []
    for warning in lint.get("warning_headers", []):
        source = warning.get("source")
        code = warning.get("code")
        line = warning.get("line")
        column = warning.get("column")
        if (source not in allowed_sources or not isinstance(code, str) or not RULE_ID.fullmatch(code)
                or type(line) is not int or line < 1 or type(column) is not int or column < 1):
            raise GateEvidenceError("unsafe G1 source annotation")
        items.append({
            "level": "warning", "rule_id": f"VERILATOR-{code}",
            "message_code": "VERILATOR_WARNING", "file": source,
            "line": line, "column": column,
        })
    items.sort(key=lambda item: (item["file"], item["line"], item["column"], item["rule_id"]))
    return items[:MAX_ANNOTATIONS], max(0, len(items) - MAX_ANNOTATIONS)


def _verify_metrics(stage: dict) -> None:
    metrics = stage["metrics"]
    if stage["gate"] == "G0":
        if set(metrics) != {"manifest_sha256", "waiver_sha256", "sources_checked", "waivers_checked"}:
            raise GateEvidenceError("invalid G0 metrics shape")
        if not isinstance(metrics["manifest_sha256"], str) or not SHA256.fullmatch(metrics["manifest_sha256"]):
            raise GateEvidenceError("invalid G0 manifest hash")
        if metrics["waiver_sha256"] is not None and (
            not isinstance(metrics["waiver_sha256"], str) or not SHA256.fullmatch(metrics["waiver_sha256"])
        ):
            raise GateEvidenceError("invalid G0 waiver hash")
        if any(value is not None and (type(value) is not int or value < 0)
               for value in (metrics["sources_checked"], metrics["waivers_checked"])):
            raise GateEvidenceError("invalid G0 counters")
        if stage["status"] == "PASS" and any(metrics[key] is None for key in (
            "waiver_sha256", "sources_checked", "waivers_checked"
        )):
            raise GateEvidenceError("PASS G0 metrics are incomplete")
    elif stage["gate"] == "G1":
        if set(metrics) != {"source_set_sha256", "tool", "returncode"}:
            raise GateEvidenceError("invalid G1 metrics shape")
        populated = metrics["source_set_sha256"] is not None
        if populated:
            tool = metrics["tool"]
            if (not isinstance(metrics["source_set_sha256"], str) or not SHA256.fullmatch(metrics["source_set_sha256"])
                    or not isinstance(tool, dict) or set(tool) != {"name", "version"}
                    or tool["name"] != "verilator" or not isinstance(tool["version"], str) or not tool["version"]
                    or type(metrics["returncode"]) is not int):
                raise GateEvidenceError("invalid populated G1 metrics")
            if (stage["status"] == "PASS") != (metrics["returncode"] == 0):
                raise GateEvidenceError("G1 status and return code differ")
        elif metrics["tool"] is not None or metrics["returncode"] is not None or stage["status"] in {"PASS", "FAIL"}:
            raise GateEvidenceError("G1 metrics are incomplete")
    else:
        if set(metrics) != {"smoke_evidence_id", "compile", "run", "pass_token_count"}:
            raise GateEvidenceError("invalid G2 metrics shape")
        populated = metrics["smoke_evidence_id"] is not None
        if populated:
            if (not isinstance(metrics["smoke_evidence_id"], str) or not SHA256.fullmatch(metrics["smoke_evidence_id"])
                    or metrics["compile"] not in {"PASS", "FAIL", "TIMEOUT", "ERROR", "NOT_RUN"}
                    or metrics["run"] not in {"PASS", "FAIL", "TIMEOUT", "ERROR", "NOT_RUN"}
                    or type(metrics["pass_token_count"]) is not int or metrics["pass_token_count"] < 0):
                raise GateEvidenceError("invalid populated G2 metrics")
            expected = (
                "PASS" if metrics["compile"] == metrics["run"] == "PASS" and metrics["pass_token_count"] == 1
                else "BLOCKED" if ("TIMEOUT" in {metrics["compile"], metrics["run"]}
                                   or "ERROR" in {metrics["compile"], metrics["run"]}
                                   or metrics["compile"] == metrics["run"] == "NOT_RUN")
                else "FAIL"
            )
            if stage["status"] != expected:
                raise GateEvidenceError("G2 status and execution metrics differ")
        elif any(metrics[key] is not None for key in ("compile", "run", "pass_token_count")) or stage["status"] in {"PASS", "FAIL"}:
            raise GateEvidenceError("G2 metrics are incomplete")


def build_bundle(
    *, manifest_path: str, manifest: dict, manifest_sha256: str,
    waiver_sha256: str | None, waiver_result: dict | None,
    lint_report: dict | None, smoke_report: dict | None,
    checks: dict, status: str, blocked_gate: str | None = None,
) -> dict:
    """Normalize existing gate results without changing their threshold semantics."""
    allowed_sources = set(manifest["sources"] + manifest["headers"])
    annotations, truncated = _lint_annotations(lint_report, allowed_sources)
    g0_status = "BLOCKED" if blocked_gate == "g0" else checks["g0"]
    g1_status = "BLOCKED" if blocked_gate == "g1" else checks["g1"]
    g2_status = "BLOCKED" if blocked_gate == "g2" else checks["g2"]
    g0_metrics = {
        "manifest_sha256": manifest_sha256,
        "waiver_sha256": waiver_sha256,
        "sources_checked": waiver_result.get("sources_checked") if waiver_result else None,
        "waivers_checked": waiver_result.get("waivers_checked") if waiver_result else None,
    }
    if lint_report is None:
        g1_metrics = {"source_set_sha256": None, "tool": None, "returncode": None}
    else:
        source_hashes = lint_report["source_sha256"]
        g1_metrics = {
            "source_set_sha256": _sha(json.dumps(source_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")),
            "tool": lint_report["tool"], "returncode": lint_report["returncode"],
        }
    if smoke_report is None:
        g2_metrics = {"smoke_evidence_id": None, "compile": None, "run": None, "pass_token_count": None}
    else:
        execution = smoke_report["execution"]
        g2_metrics = {
            "smoke_evidence_id": smoke_report["evidence_id"],
            "compile": execution["compile"], "run": execution["run"],
            "pass_token_count": execution["pass_token_count"],
        }
    stages = [
        _stage("G0", g0_status, metrics=g0_metrics, annotations=[]),
        _stage("G1", g1_status, metrics=g1_metrics, annotations=annotations,
               finding_count=len(annotations) + truncated),
        _stage("G2", g2_status, metrics=g2_metrics, annotations=[]),
    ]
    bundle = {
        "schema_version": 1, "evidence_kind": "RTL_GATE_BUNDLE",
        "status": status, "evidence_id": "",
        "project": {
            "manifest": manifest_path, "manifest_sha256": manifest_sha256,
            "target": manifest["target"], "top": manifest["top"],
        },
        "stages": stages,
        "annotation_count": len(annotations), "annotations_truncated": truncated,
        "limitations": [
            "directed G0/G1/G2 checks only",
            "not CDC/RDC, FPGA/ASIC implementation, or product signoff",
        ],
    }
    bundle["evidence_id"] = _content_id(bundle)
    return verify_bundle(bundle, allowed_sources=allowed_sources)


def verify_bundle(bundle: dict, *, allowed_sources: set[str] | None = None) -> dict:
    required = {
        "schema_version", "evidence_kind", "status", "evidence_id", "project",
        "stages", "annotation_count", "annotations_truncated", "limitations",
    }
    if not isinstance(bundle, dict) or set(bundle) != required:
        raise GateEvidenceError("invalid RTL gate evidence shape")
    if (type(bundle["schema_version"]) is not int or bundle["schema_version"] != 1
            or bundle["evidence_kind"] != "RTL_GATE_BUNDLE" or bundle["status"] not in STATUSES - {"NOT_RUN"}):
        raise GateEvidenceError("unsupported RTL gate evidence")
    if not isinstance(bundle["evidence_id"], str) or not SHA256.fullmatch(bundle["evidence_id"]):
        raise GateEvidenceError("invalid RTL gate evidence ID")
    project = bundle["project"]
    if (not isinstance(project, dict) or set(project) != {"manifest", "manifest_sha256", "target", "top"}
            or not isinstance(project["manifest"], str) or Path(project["manifest"]).is_absolute()
            or "\\" in project["manifest"] or ".." in project["manifest"].split("/")
            or not isinstance(project["manifest_sha256"], str) or not SHA256.fullmatch(project["manifest_sha256"])
            or project["target"] not in {"fpga", "asic"}
            or not isinstance(project["top"], str) or not IDENTIFIER.fullmatch(project["top"])):
        raise GateEvidenceError("invalid RTL gate project identity")
    stages = bundle["stages"]
    if not isinstance(stages, list) or [stage.get("gate") for stage in stages if isinstance(stage, dict)] != list(GATES):
        raise GateEvidenceError("RTL gate stages must be ordered G0/G1/G2")
    annotation_count = 0
    for stage in stages:
        if set(stage) != {"gate", "status", "evidence_id", "finding_count", "metrics", "annotations"}:
            raise GateEvidenceError("invalid RTL gate stage shape")
        if stage["status"] not in STATUSES or not isinstance(stage["metrics"], dict) or not isinstance(stage["annotations"], list):
            raise GateEvidenceError("invalid RTL gate stage state")
        _verify_metrics(stage)
        if stage["gate"] != "G1" and stage["annotations"]:
            raise GateEvidenceError("only G1 may carry source annotations")
        if type(stage["finding_count"]) is not int or stage["finding_count"] < len(stage["annotations"]):
            raise GateEvidenceError("RTL gate finding count mismatch")
        if stage["status"] == "NOT_RUN":
            if stage["evidence_id"] is not None:
                raise GateEvidenceError("NOT_RUN stage cannot have evidence")
        elif not isinstance(stage["evidence_id"], str) or not SHA256.fullmatch(stage["evidence_id"]):
            raise GateEvidenceError("executed stage requires evidence ID")
        elif stage["evidence_id"] != _content_id(stage):
            raise GateEvidenceError("RTL gate stage content ID mismatch")
        for annotation in stage["annotations"]:
            if set(annotation) != {"level", "rule_id", "message_code", "file", "line", "column"}:
                raise GateEvidenceError("invalid RTL gate annotation shape")
            if (annotation["level"] != "warning"
                    or not isinstance(annotation["rule_id"], str)
                    or not annotation["rule_id"].startswith("VERILATOR-")
                    or not RULE_ID.fullmatch(annotation["rule_id"])
                    or annotation["message_code"] != "VERILATOR_WARNING"
                    or not isinstance(annotation["file"], str) or Path(annotation["file"]).is_absolute()
                    or "\\" in annotation["file"] or ".." in annotation["file"].split("/")
                    or type(annotation["line"]) is not int or annotation["line"] < 1
                    or type(annotation["column"]) is not int or annotation["column"] < 1
                    or allowed_sources is not None and annotation["file"] not in allowed_sources):
                raise GateEvidenceError("unsafe RTL gate annotation")
        annotation_count += len(stage["annotations"])
        if stage["gate"] != "G1" and stage["finding_count"] != len(stage["annotations"]):
            raise GateEvidenceError("only G1 findings may be annotation-truncated")
    if project["manifest_sha256"] != stages[0]["metrics"]["manifest_sha256"]:
        raise GateEvidenceError("project and G0 manifest hashes differ")
    if (type(bundle["annotation_count"]) is not int or bundle["annotation_count"] != annotation_count
            or type(bundle["annotations_truncated"]) is not int or bundle["annotations_truncated"] < 0
            or bundle["annotations_truncated"] != sum(
                stage["finding_count"] - len(stage["annotations"]) for stage in stages
            )
            or annotation_count > MAX_ANNOTATIONS):
        raise GateEvidenceError("invalid RTL gate annotation counts")
    if not isinstance(bundle["limitations"], list) or not bundle["limitations"] or not all(
        isinstance(item, str) and item for item in bundle["limitations"]
    ):
        raise GateEvidenceError("invalid RTL gate limitations")
    if bundle["evidence_id"] != _content_id(bundle):
        raise GateEvidenceError("RTL gate bundle content ID mismatch")
    derived = (
        "BLOCKED" if any(stage["status"] == "BLOCKED" for stage in stages)
        else "FAIL" if any(stage["status"] == "FAIL" for stage in stages)
        else "PASS" if all(stage["status"] == "PASS" for stage in stages)
        else "BLOCKED"
    )
    if bundle["status"] != derived:
        raise GateEvidenceError("RTL gate bundle status mismatch")
    return bundle


def summary(bundle: dict) -> str:
    rows = ["## Unified RTL G0/G1/G2 evidence\n\n",
            f"Status: **{bundle['status']}**; Evidence: `{bundle['evidence_id']}`\n\n",
            "| Gate | Status | Findings | Evidence |\n|---|---|---:|---|\n"]
    for stage in bundle["stages"]:
        evidence = f"`{stage['evidence_id']}`" if stage["evidence_id"] else "—"
        rows.append(f"| {stage['gate']} | {stage['status']} | {stage['finding_count']} | {evidence} |\n")
    if bundle["annotations_truncated"]:
        rows.append(f"\nAnnotations truncated: {bundle['annotations_truncated']}.\n")
    rows.append("\nDirected checks only; not CDC/RDC, implementation, or product signoff.\n")
    return "".join(rows)


def emit_github_annotations(bundle: dict) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for stage in bundle["stages"]:
        for item in stage["annotations"]:
            level = item["level"]
            title = f"{stage['gate']} {item['rule_id']}"
            message = f"{item['message_code']}; review unified RTL evidence"
            print(f"::{level} file={item['file']},line={item['line']},col={item['column']},title={title}::{message}")
