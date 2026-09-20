#!/usr/bin/env python3
"""Plan and verify a source-bound ASIC performance, power, and area report."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
STATUS = "ASIC_PPA_REPORT_COMPLETE"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SCOPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_./-]{0,511}$")
NUMBER = r"([+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
POWER_TOTAL_RE = re.compile(
    rf"(?mi)^\s*Total\s+{NUMBER}\s+{NUMBER}\s+{NUMBER}\s+{NUMBER}(?:\s+100(?:\.0+)?%)?\s*$"
)
ANNOTATED_RE = re.compile(r"(?mi)\bAnnotated\s+(\d+)\s+pin activities\b")
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_ACTIVITY_BYTES = 32 * 1024 * 1024 * 1024
REPORT_FIELDS = {
    "schema_version", "report_id", "power_plan_id", "status", "result_status", "stage",
    "source_evidence", "corner", "activity", "performance", "power",
    "area", "tool", "artifacts", "complete_dimensions", "signoff_status",
    "limitations",
}


class AsicPpaError(ValueError):
    """Raised when a PPA plan or report is incomplete, stale, or ambiguous."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _content_id(value: Mapping[str, Any], field: str) -> str:
    payload = {key: item for key, item in value.items() if key != field}
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _load(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AsicPpaError(f"cannot load {label}") from exc


def _fields(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise AsicPpaError(f"{label} fields are invalid")
    return value


def _number(value: Any, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AsicPpaError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or nonnegative and result < 0:
        raise AsicPpaError(f"{label} is invalid")
    return result


def _regular_file(path: Path, label: str, *, maximum: int | None = None) -> Path:
    try:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
    except OSError as exc:
        raise AsicPpaError(f"{label} is unavailable") from exc
    if not resolved.is_file() or path.is_symlink() or stat.st_size <= 0:
        raise AsicPpaError(f"{label} must be a nonempty regular file")
    if maximum is not None and stat.st_size > maximum:
        raise AsicPpaError(f"{label} exceeds the reviewed size limit")
    return resolved


def _artifact(path: Path, label: str, *, maximum: int | None = None) -> dict[str, Any]:
    resolved = _regular_file(path, label, maximum=maximum)
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"sha256": "sha256:" + digest.hexdigest(), "bytes": resolved.stat().st_size}


def _verify_content_id(value: Any, *, field: str, status: str, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or value.get("status") != status:
        raise AsicPpaError(f"{label} status is invalid")
    identity = value.get(field)
    if not isinstance(identity, str) or not HASH_RE.fullmatch(identity):
        raise AsicPpaError(f"{label} identity is invalid")
    if identity != _content_id(value, field):
        raise AsicPpaError(f"{label} content ID mismatch")
    return value


def _artifact_by_role(evidence: Mapping[str, Any], role: str, label: str) -> Mapping[str, Any]:
    artifacts = evidence.get("artifacts")
    if not isinstance(artifacts, list):
        raise AsicPpaError(f"{label} artifacts are invalid")
    matches = [item for item in artifacts if isinstance(item, dict) and item.get("role") == role]
    if len(matches) != 1:
        raise AsicPpaError(f"{label} must contain exactly one {role} artifact")
    item = matches[0]
    if (
        not HASH_RE.fullmatch(str(item.get("sha256")))
        or isinstance(item.get("bytes"), bool)
        or not isinstance(item.get("bytes"), int)
        or item["bytes"] <= 0
    ):
        raise AsicPpaError(f"{label} {role} artifact is invalid")
    return item


def _marker(text: str, name: str) -> str:
    matches = re.findall(rf"(?m)^\s*{re.escape(name)}=([^\r\n]+)\s*$", text)
    if len(matches) != 1:
        raise AsicPpaError(f"power report must contain exactly one {name} marker")
    return matches[0].strip()


def _script_marker(text: str, name: str) -> str:
    matches = re.findall(
        rf'(?m)^\s*puts "{re.escape(name)}=([^"\r\n]+)"\s*$', text
    )
    if len(matches) != 1:
        raise AsicPpaError(f"power script must contain exactly one {name} marker")
    return matches[0].strip()


def _parse_power(text: str) -> dict[str, float]:
    if text.count("VIBESILICON_POWER_REPORT_BEGIN") != 1 or text.count("VIBESILICON_POWER_REPORT_END") != 1:
        raise AsicPpaError("power report boundary markers are missing or duplicated")
    if "Power (Watts)" not in text:
        raise AsicPpaError("power report does not declare Watts")
    matches = list(POWER_TOTAL_RE.finditer(text))
    if len(matches) != 1:
        raise AsicPpaError("power report must contain exactly one Total row")
    internal, switching, leakage, total = (float(item) for item in matches[0].groups())
    if not all(math.isfinite(item) and item >= 0 for item in (internal, switching, leakage, total)):
        raise AsicPpaError("power metrics must be finite and nonnegative")
    component_sum = internal + switching + leakage
    if abs(component_sum - total) > max(1e-15, total * 0.02):
        raise AsicPpaError("power total does not match component sum within report precision")
    return {
        "unit": "W", "internal_w": internal, "switching_w": switching,
        "leakage_w": leakage, "total_w": total,
    }


def _tcl_path(path: Path, label: str) -> str:
    resolved = _regular_file(path, label).as_posix()
    if any(character in resolved for character in "{}\r\n"):
        raise AsicPpaError(f"{label} cannot be represented safely in Tcl")
    return "{" + resolved + "}"


def _write_new(path: Path, text: str, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    except FileExistsError as exc:
        raise AsicPpaError(f"refusing to overwrite {label}") from exc


def render_plan(
    *, top: str, liberty: Path, netlist: Path, sdc: Path, mode: str,
    activity_file: Path | None, scope: str | None, spef: Path | None,
    default_activity: float | None, default_duty: float | None,
) -> str:
    if not IDENTIFIER_RE.fullmatch(top):
        raise AsicPpaError("top module is invalid")
    mode = mode.upper()
    if mode not in {"VCD", "SAIF", "ESTIMATED"}:
        raise AsicPpaError("activity mode must be VCD, SAIF, or ESTIMATED")
    liberty_artifact = _artifact(liberty, "Liberty")
    netlist_artifact = _artifact(netlist, "gate netlist")
    sdc_artifact = _artifact(sdc, "SDC")
    spef_artifact = _artifact(spef, "SPEF") if spef is not None else None
    activity_artifact = None
    plan_inputs: dict[str, Any] = {
        "top": top,
        "liberty_sha256": liberty_artifact["sha256"],
        "netlist_sha256": netlist_artifact["sha256"],
        "sdc_sha256": sdc_artifact["sha256"],
        "spef_sha256": spef_artifact["sha256"] if spef_artifact else None,
        "activity_mode": mode,
    }
    if mode in {"VCD", "SAIF"}:
        if activity_file is None or not isinstance(scope, str) or not SCOPE_RE.fullmatch(scope):
            raise AsicPpaError("vector activity requires a safe scope and activity file")
        activity_artifact = _artifact(activity_file, "activity file", maximum=MAX_ACTIVITY_BYTES)
        plan_inputs.update({
            "activity_source_sha256": activity_artifact["sha256"],
            "activity_scope": scope,
        })
    else:
        activity = _number(default_activity, "default activity", nonnegative=True)
        duty = _number(default_duty, "default duty", nonnegative=True)
        if activity > 1 or duty > 1:
            raise AsicPpaError("default activity and duty must be within 0..1")
        plan_inputs.update({"default_activity": activity, "default_duty": duty})
    plan_id = "sha256:" + hashlib.sha256(_canonical_bytes(plan_inputs)).hexdigest()
    lines = [
        f'puts "VIBESILICON_POWER_PLAN_ID={plan_id}"',
        f"read_liberty {_tcl_path(liberty, 'Liberty')}",
        f"read_verilog {_tcl_path(netlist, 'gate netlist')}",
        f"link_design {top}",
        f"read_sdc {_tcl_path(sdc, 'SDC')}",
    ]
    if spef is not None:
        lines.append(f"read_spef {_tcl_path(spef, 'SPEF')}")
        lines.append(f'puts "VIBESILICON_SPEF_SHA256={spef_artifact["sha256"]}"')
    lines.extend([
        f'puts "VIBESILICON_LIBERTY_SHA256={liberty_artifact["sha256"]}"',
        f'puts "VIBESILICON_NETLIST_SHA256={netlist_artifact["sha256"]}"',
        f'puts "VIBESILICON_SDC_SHA256={sdc_artifact["sha256"]}"',
        f'puts "VIBESILICON_ACTIVITY_MODE={mode}"',
    ])
    if mode in {"VCD", "SAIF"}:
        lines.append(f'puts "VIBESILICON_ACTIVITY_SOURCE_SHA256={activity_artifact["sha256"]}"')
        lines.append(f'puts "VIBESILICON_ACTIVITY_SCOPE={scope}"')
        command = "read_vcd" if mode == "VCD" else "read_saif"
        lines.append(f"{command} -scope {scope} {_tcl_path(activity_file, 'activity file')}")
        lines.append("report_activity_annotation")
    else:
        lines.append(f'puts "VIBESILICON_DEFAULT_ACTIVITY={activity:.9g}"')
        lines.append(f'puts "VIBESILICON_DEFAULT_DUTY={duty:.9g}"')
        lines.append(f"set_power_activity -input -activity {activity:.9g} -duty {duty:.9g}")
    lines.extend([
        'puts "VIBESILICON_POWER_REPORT_BEGIN"',
        "report_power",
        'puts "VIBESILICON_POWER_REPORT_END"',
    ])
    return "\n".join(lines) + "\n"


def _upstream(
    input_evidence: Any, a02_evidence: Any, a03_evidence: Any | None,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any] | None]:
    a01 = _verify_content_id(
        input_evidence, field="evidence_id", status="A01_INPUTS_VERIFIED_UNEXECUTED",
        label="A01 input evidence",
    )
    a02 = _verify_content_id(
        a02_evidence, field="evidence_id", status="A02_SYNTH_STA_COMPLETE",
        label="A02 evidence",
    )
    if a02.get("input_evidence_id") != a01["evidence_id"]:
        raise AsicPpaError("A02 evidence is not bound to A01 input evidence")
    a03 = None
    if a03_evidence is not None:
        a03 = _verify_content_id(
            a03_evidence, field="evidence_id", status="A03_PHYSICAL_RUN_COMPLETE",
            label="A03 run evidence",
        )
        if (
            a03.get("input_evidence_id") != a01["evidence_id"]
            or a03.get("a02_evidence_id") != a02["evidence_id"]
        ):
            raise AsicPpaError("A03 evidence is not bound to A01/A02 evidence")
    return a01, a02, a03


def build_report(
    *, input_evidence: Any, a02_evidence: Any, a03_evidence: Any | None,
    power_script: Path, power_report: Path, activity_mode: str,
    activity_file: Path | None, activity_scope: str | None, spef: Path | None,
    default_activity: float | None, default_duty: float | None,
) -> dict[str, Any]:
    a01, a02, a03 = _upstream(input_evidence, a02_evidence, a03_evidence)
    script_artifact = _artifact(power_script, "power script", maximum=MAX_REPORT_BYTES)
    report_artifact = _artifact(power_report, "power report", maximum=MAX_REPORT_BYTES)
    try:
        script_text = _regular_file(
            power_script, "power script", maximum=MAX_REPORT_BYTES
        ).read_text(encoding="utf-8")
        report_text = _regular_file(power_report, "power report", maximum=MAX_REPORT_BYTES).read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeError) as exc:
        raise AsicPpaError("power script or report is not valid UTF-8") from exc
    power_plan_id = _script_marker(script_text, "VIBESILICON_POWER_PLAN_ID")
    if not HASH_RE.fullmatch(power_plan_id):
        raise AsicPpaError("power plan ID is invalid")
    if _marker(report_text, "VIBESILICON_POWER_PLAN_ID") != power_plan_id:
        raise AsicPpaError("power report is not bound to the supplied power plan")
    mode = activity_mode.upper()
    if _marker(report_text, "VIBESILICON_ACTIVITY_MODE") != mode:
        raise AsicPpaError("activity mode does not match power report")
    corner = a01.get("pdk", {}).get("corner")
    if not isinstance(corner, dict):
        raise AsicPpaError("A01 corner evidence is invalid")
    for field in ("name", "process", "voltage_v", "temperature_c", "liberty_sha256", "rc_tech_sha256"):
        if field not in corner:
            raise AsicPpaError("A01 corner evidence is incomplete")
    if _marker(report_text, "VIBESILICON_LIBERTY_SHA256") != corner["liberty_sha256"]:
        raise AsicPpaError("power report Liberty does not match A01 corner")
    expected_netlist = _artifact_by_role(
        a03 or a02, "postroute_netlist" if a03 else "netlist", "source evidence"
    )
    if _marker(report_text, "VIBESILICON_NETLIST_SHA256") != expected_netlist["sha256"]:
        raise AsicPpaError("power report netlist does not match source evidence")
    if _marker(report_text, "VIBESILICON_SDC_SHA256") != a01.get("design", {}).get("constraints_sha256"):
        raise AsicPpaError("power report SDC does not match A01 constraints")
    artifacts = [
        {"role": "power_script", **script_artifact},
        {"role": "power_report", **report_artifact},
    ]
    if a03 is not None:
        if spef is None:
            raise AsicPpaError("post-route PPA requires SPEF")
        spef_artifact = _artifact(spef, "SPEF")
        expected_spef = _artifact_by_role(a03, "spef", "A03 evidence")
        if spef_artifact != {"sha256": expected_spef["sha256"], "bytes": expected_spef["bytes"]}:
            raise AsicPpaError("SPEF does not match A03 evidence")
        if _marker(report_text, "VIBESILICON_SPEF_SHA256") != spef_artifact["sha256"]:
            raise AsicPpaError("power report SPEF marker does not match A03 evidence")
        artifacts.append({"role": "spef", **spef_artifact})
    activity: dict[str, Any]
    if mode in {"VCD", "SAIF"}:
        if (
            activity_file is None
            or not isinstance(activity_scope, str)
            or not SCOPE_RE.fullmatch(activity_scope)
        ):
            raise AsicPpaError("vector-backed PPA requires activity file and scope")
        activity_artifact = _artifact(activity_file, "activity file", maximum=MAX_ACTIVITY_BYTES)
        if _marker(report_text, "VIBESILICON_ACTIVITY_SOURCE_SHA256") != activity_artifact["sha256"]:
            raise AsicPpaError("activity source does not match power report")
        if _marker(report_text, "VIBESILICON_ACTIVITY_SCOPE") != activity_scope:
            raise AsicPpaError("activity scope does not match power report")
        annotated = [int(match) for match in ANNOTATED_RE.findall(report_text)]
        if len(annotated) != 1 or annotated[0] <= 0:
            raise AsicPpaError("vector activity must annotate a nonzero pin count exactly once")
        artifacts.append({"role": "activity", **activity_artifact})
        activity = {
            "mode": mode, "confidence": "VECTOR_BACKED",
            "source_sha256": activity_artifact["sha256"], "source_bytes": activity_artifact["bytes"],
            "scope": activity_scope, "annotated_pin_count": annotated[0],
            "default_activity": None, "default_duty": None,
        }
    elif mode == "ESTIMATED":
        activity_value = _number(default_activity, "default activity", nonnegative=True)
        duty_value = _number(default_duty, "default duty", nonnegative=True)
        if activity_value > 1 or duty_value > 1:
            raise AsicPpaError("default activity and duty must be within 0..1")
        if float(_marker(report_text, "VIBESILICON_DEFAULT_ACTIVITY")) != activity_value:
            raise AsicPpaError("default activity does not match power report")
        if float(_marker(report_text, "VIBESILICON_DEFAULT_DUTY")) != duty_value:
            raise AsicPpaError("default duty does not match power report")
        activity = {
            "mode": mode, "confidence": "DEFAULT_ACTIVITY_ESTIMATE",
            "source_sha256": None, "source_bytes": None, "scope": None,
            "annotated_pin_count": None, "default_activity": activity_value,
            "default_duty": duty_value,
        }
    else:
        raise AsicPpaError("activity mode must be VCD, SAIF, or ESTIMATED")
    a02_metrics = a02.get("metrics")
    selected = (a03 or a02).get("metrics")
    if not isinstance(a02_metrics, dict) or not isinstance(selected, dict):
        raise AsicPpaError("source PPA metrics are invalid")
    if not isinstance(selected.get("timing_met"), bool):
        raise AsicPpaError("source timing status must be Boolean")
    performance = {
        "wns_ns": _number(selected.get("wns_ns"), "WNS"),
        "tns_ns": _number(selected.get("tns_ns"), "TNS"),
        "timing_met": selected["timing_met"],
    }
    if performance["tns_ns"] > 0 or performance["timing_met"] is not (
        performance["wns_ns"] >= 0 and performance["tns_ns"] == 0
    ):
        raise AsicPpaError("timing status does not match WNS/TNS")
    if isinstance(a02_metrics.get("cell_count"), bool) or not isinstance(a02_metrics.get("cell_count"), int):
        raise AsicPpaError("A02 cell count is invalid")
    area = {
        "unit": "um2", "cell_count": a02_metrics["cell_count"],
        "synth_cell_area_um2": _number(
            a02_metrics.get("synth_cell_area_um2"), "synthesis area", nonnegative=True
        ),
        "standard_cell_area_um2": _number(
            selected.get("standard_cell_area_um2"), "selected area", nonnegative=True
        ),
    }
    tools = (a03 or a02).get("tools")
    if not isinstance(tools, list):
        raise AsicPpaError("source tool evidence is invalid")
    openroad = [tool for tool in tools if isinstance(tool, dict) and tool.get("name") == "openroad"]
    if len(openroad) != 1 or not HASH_RE.fullmatch(str(openroad[0].get("binary_sha256"))):
        raise AsicPpaError("OpenROAD identity is missing or ambiguous")
    vector = mode in {"VCD", "SAIF"}
    result_status = (
        ("VECTOR_BACKED" if vector else "ESTIMATED")
        + ("_TIMING_MET" if performance["timing_met"] else "_TIMING_VIOLATION")
    )
    limitations = [
        "single-corner report; MCMM and statistical variation are not covered",
        "NOT_SIGNOFF: IR drop, EM, thermal, package and silicon correlation are not covered",
    ]
    if vector:
        limitations.append("dynamic power is workload- and activity-scope-dependent")
    else:
        limitations.append("dynamic power uses reviewed default input activity and is an estimate")
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION, "report_id": "", "power_plan_id": power_plan_id,
        "status": STATUS,
        "result_status": result_status, "stage": "POST_ROUTE" if a03 else "POST_SYNTHESIS",
        "source_evidence": {
            "input_evidence_id": a01["evidence_id"], "a02_evidence_id": a02["evidence_id"],
            "a03_evidence_id": a03["evidence_id"] if a03 else None,
        },
        "corner": {field: corner[field] for field in (
            "name", "process", "voltage_v", "temperature_c", "liberty_sha256", "rc_tech_sha256"
        )},
        "activity": activity, "performance": performance, "power": _parse_power(report_text),
        "area": area,
        "tool": {key: openroad[0][key] for key in ("name", "version", "binary_sha256")},
        "artifacts": artifacts, "complete_dimensions": True, "signoff_status": "NOT_SIGNOFF",
        "limitations": limitations,
    }
    result["report_id"] = _content_id(result, "report_id")
    verify_report(result)
    return result


def verify_report(value: Any) -> Mapping[str, Any]:
    report = _fields(value, REPORT_FIELDS, "PPA report")
    if report["schema_version"] != SCHEMA_VERSION or report["status"] != STATUS:
        raise AsicPpaError("PPA report version or status is invalid")
    if report["report_id"] != _content_id(report, "report_id"):
        raise AsicPpaError("PPA report content ID mismatch")
    if not HASH_RE.fullmatch(str(report["power_plan_id"])):
        raise AsicPpaError("PPA power plan ID is invalid")
    stage = report["stage"]
    if stage not in {"POST_SYNTHESIS", "POST_ROUTE"}:
        raise AsicPpaError("PPA stage is invalid")
    source = _fields(
        report["source_evidence"], {"input_evidence_id", "a02_evidence_id", "a03_evidence_id"},
        "PPA source evidence",
    )
    if (
        not HASH_RE.fullmatch(str(source["input_evidence_id"]))
        or not HASH_RE.fullmatch(str(source["a02_evidence_id"]))
    ):
        raise AsicPpaError("PPA source evidence IDs are invalid")
    if (stage == "POST_ROUTE") is not bool(source["a03_evidence_id"]):
        raise AsicPpaError("PPA stage does not match A03 evidence")
    if source["a03_evidence_id"] is not None and not HASH_RE.fullmatch(str(source["a03_evidence_id"])):
        raise AsicPpaError("A03 evidence ID is invalid")
    corner = _fields(
        report["corner"],
        {"name", "process", "voltage_v", "temperature_c", "liberty_sha256", "rc_tech_sha256"},
        "PPA corner",
    )
    if (
        not isinstance(corner["name"], str)
        or not corner["name"]
        or not isinstance(corner["process"], str)
        or not corner["process"]
        or _number(corner["voltage_v"], "corner voltage") <= 0
        or not HASH_RE.fullmatch(str(corner["liberty_sha256"]))
        or not HASH_RE.fullmatch(str(corner["rc_tech_sha256"]))
    ):
        raise AsicPpaError("PPA corner evidence is invalid")
    _number(corner["temperature_c"], "corner temperature")
    activity = _fields(
        report["activity"], {"mode", "confidence", "source_sha256", "source_bytes", "scope",
                             "annotated_pin_count", "default_activity", "default_duty"},
        "PPA activity",
    )
    vector = activity["mode"] in {"VCD", "SAIF"}
    if vector:
        if (activity["confidence"] != "VECTOR_BACKED"
                or not HASH_RE.fullmatch(str(activity["source_sha256"]))
                or isinstance(activity["source_bytes"], bool)
                or not isinstance(activity["source_bytes"], int) or activity["source_bytes"] <= 0
                or not isinstance(activity["scope"], str) or not SCOPE_RE.fullmatch(activity["scope"])
                or isinstance(activity["annotated_pin_count"], bool)
                or not isinstance(activity["annotated_pin_count"], int)
                or activity["annotated_pin_count"] <= 0
                or activity["default_activity"] is not None or activity["default_duty"] is not None):
            raise AsicPpaError("vector activity evidence is invalid")
    elif activity["mode"] == "ESTIMATED":
        default_activity = _number(activity["default_activity"], "default activity", nonnegative=True)
        default_duty = _number(activity["default_duty"], "default duty", nonnegative=True)
        if (activity["confidence"] != "DEFAULT_ACTIVITY_ESTIMATE"
                or any(activity[field] is not None for field in (
                    "source_sha256", "source_bytes", "scope", "annotated_pin_count"
                )) or default_activity > 1 or default_duty > 1):
            raise AsicPpaError("estimated activity evidence is invalid")
    else:
        raise AsicPpaError("PPA activity mode is invalid")
    performance = _fields(report["performance"], {"wns_ns", "tns_ns", "timing_met"}, "performance")
    wns = _number(performance["wns_ns"], "WNS")
    tns = _number(performance["tns_ns"], "TNS")
    timing_met = wns >= 0 and tns == 0
    if tns > 0 or performance["timing_met"] is not timing_met:
        raise AsicPpaError("PPA timing status is inconsistent")
    expected_status = (
        ("VECTOR_BACKED" if vector else "ESTIMATED")
        + ("_TIMING_MET" if timing_met else "_TIMING_VIOLATION")
    )
    if report["result_status"] != expected_status:
        raise AsicPpaError("PPA result status is inconsistent")
    power = _fields(report["power"], {"unit", "internal_w", "switching_w", "leakage_w", "total_w"}, "power")
    components = [_number(power[field], field, nonnegative=True) for field in (
        "internal_w", "switching_w", "leakage_w"
    )]
    total = _number(power["total_w"], "total power", nonnegative=True)
    if power["unit"] != "W" or abs(sum(components) - total) > max(1e-15, total * 0.02):
        raise AsicPpaError("PPA power metrics are inconsistent")
    area = _fields(
        report["area"],
        {"unit", "cell_count", "synth_cell_area_um2", "standard_cell_area_um2"},
        "area",
    )
    if (area["unit"] != "um2" or isinstance(area["cell_count"], bool)
            or not isinstance(area["cell_count"], int) or area["cell_count"] < 0):
        raise AsicPpaError("PPA area metrics are invalid")
    _number(area["synth_cell_area_um2"], "synthesis area", nonnegative=True)
    _number(area["standard_cell_area_um2"], "standard-cell area", nonnegative=True)
    tool = _fields(report["tool"], {"name", "version", "binary_sha256"}, "PPA tool")
    if tool["name"] != "openroad" or not isinstance(tool["version"], str) or not tool["version"]:
        raise AsicPpaError("PPA tool identity is invalid")
    if not HASH_RE.fullmatch(str(tool["binary_sha256"])):
        raise AsicPpaError("PPA tool hash is invalid")
    expected_roles = ["power_script", "power_report"]
    if stage == "POST_ROUTE":
        expected_roles.append("spef")
    if vector:
        expected_roles.append("activity")
    roles = []
    if not isinstance(report["artifacts"], list):
        raise AsicPpaError("PPA artifacts are invalid")
    for item in report["artifacts"]:
        artifact = _fields(item, {"role", "sha256", "bytes"}, "PPA artifact")
        roles.append(artifact["role"])
        if (
            not HASH_RE.fullmatch(str(artifact["sha256"]))
            or isinstance(artifact["bytes"], bool)
            or not isinstance(artifact["bytes"], int)
            or artifact["bytes"] <= 0
        ):
            raise AsicPpaError("PPA artifact is invalid")
    if roles != expected_roles:
        raise AsicPpaError("PPA artifacts are not ordered and complete")
    if report["complete_dimensions"] is not True or report["signoff_status"] != "NOT_SIGNOFF":
        raise AsicPpaError("PPA capability boundaries are invalid")
    if (
        not isinstance(report["limitations"], list)
        or len(report["limitations"]) < 2
        or any(not isinstance(item, str) or not item for item in report["limitations"])
    ):
        raise AsicPpaError("PPA limitations are incomplete")
    return report


def markdown(report: Mapping[str, Any]) -> str:
    verify_report(report)
    power = report["power"]
    area = report["area"]
    timing = report["performance"]
    activity = report["activity"]
    lines = [
        "# ASIC PPA Report", "", f"- Report ID: `{report['report_id']}`",
        f"- Power plan ID: `{report['power_plan_id']}`",
        f"- Stage: `{report['stage']}`", f"- Result: `{report['result_status']}`",
        f"- Signoff: `{report['signoff_status']}`", "", "## Metrics", "",
        "| Dimension | Metric | Value |", "|---|---|---:|",
        f"| Performance | WNS | {timing['wns_ns']:.6g} ns |",
        f"| Performance | TNS | {timing['tns_ns']:.6g} ns |",
        f"| Power | Internal | {power['internal_w']:.6g} W |",
        f"| Power | Switching | {power['switching_w']:.6g} W |",
        f"| Power | Leakage | {power['leakage_w']:.6g} W |",
        f"| Power | Total | {power['total_w']:.6g} W |",
        f"| Area | Cell count | {area['cell_count']} |",
        f"| Area | Synthesis cell area | {area['synth_cell_area_um2']:.6g} um² |",
        f"| Area | Selected-stage cell area | {area['standard_cell_area_um2']:.6g} um² |",
        "", "## Context", "", f"- Corner: `{report['corner']['name']}`",
        "- Voltage / temperature: "
        f"`{report['corner']['voltage_v']} V / {report['corner']['temperature_c']} °C`",
        f"- Activity: `{activity['mode']} / {activity['confidence']}`",
    ]
    if activity["annotated_pin_count"] is not None:
        lines.append(f"- Annotated pins: `{activity['annotated_pin_count']}`")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--top", required=True)
    plan.add_argument("--liberty", type=Path, required=True)
    plan.add_argument("--netlist", type=Path, required=True)
    plan.add_argument("--sdc", type=Path, required=True)
    plan.add_argument("--spef", type=Path)
    plan.add_argument("--activity-mode", required=True, choices=("VCD", "SAIF", "ESTIMATED"))
    plan.add_argument("--activity-file", type=Path)
    plan.add_argument("--activity-scope")
    plan.add_argument("--default-activity", type=float)
    plan.add_argument("--default-duty", type=float)
    plan.add_argument("--output", type=Path, required=True)
    build = sub.add_parser("build")
    build.add_argument("--input-evidence", type=Path, required=True)
    build.add_argument("--a02-evidence", type=Path, required=True)
    build.add_argument("--a03-evidence", type=Path)
    build.add_argument("--power-script", type=Path, required=True)
    build.add_argument("--power-report", type=Path, required=True)
    build.add_argument("--spef", type=Path)
    build.add_argument("--activity-mode", required=True, choices=("VCD", "SAIF", "ESTIMATED"))
    build.add_argument("--activity-file", type=Path)
    build.add_argument("--activity-scope")
    build.add_argument("--default-activity", type=float)
    build.add_argument("--default-duty", type=float)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--markdown", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("report", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "plan":
            text = render_plan(
                top=args.top, liberty=args.liberty, netlist=args.netlist, sdc=args.sdc,
                mode=args.activity_mode, activity_file=args.activity_file, scope=args.activity_scope,
                spef=args.spef, default_activity=args.default_activity, default_duty=args.default_duty,
            )
            _write_new(args.output, text, "power plan")
            print(json.dumps({
                "status": "POWER_PLAN_READY",
                "sha256": _artifact(args.output, "power plan")["sha256"],
            }))
            return 0
        if args.command == "verify":
            report = verify_report(_load(args.report, "PPA report"))
            print(json.dumps({"status": report["status"], "report_id": report["report_id"]}))
            return 0
        report = build_report(
            input_evidence=_load(args.input_evidence, "A01 input evidence"),
            a02_evidence=_load(args.a02_evidence, "A02 evidence"),
            a03_evidence=_load(args.a03_evidence, "A03 evidence") if args.a03_evidence else None,
            power_script=args.power_script, power_report=args.power_report,
            activity_mode=args.activity_mode, activity_file=args.activity_file,
            activity_scope=args.activity_scope, spef=args.spef,
            default_activity=args.default_activity, default_duty=args.default_duty,
        )
        _write_new(args.output, json.dumps(report, ensure_ascii=False, indent=2) + "\n", "PPA report")
        if args.markdown:
            _write_new(args.markdown, markdown(report), "PPA Markdown report")
        print(json.dumps({"status": report["status"], "report_id": report["report_id"]}))
        return 0
    except (AsicPpaError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
