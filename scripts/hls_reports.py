"""Read-only, root-confined Vitis HLS synthesis estimates and diagnostic excerpts."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
import xml.etree.ElementTree as ET

from scripts.evidence_contract import sha256_bytes


MAX_XML_BYTES = 8 * 1024 * 1024
MAX_LOG_BYTES = 16 * 1024 * 1024
MAX_DIAGNOSTICS = 80
MAX_LOOPS = 128
RESOURCES = ("BRAM_18K", "DSP", "FF", "LUT", "URAM")
DIAGNOSTIC = re.compile(r"Pipelining (?:loop|function|result)|WARNING:|ERROR:|HLS 200-(?:880|885|887)", re.I)


def _read(root: Path, value: str, suffixes: set[str], limit: int) -> tuple[bytes, dict]:
    if not isinstance(value, str) or not value:
        raise ValueError("artifact path must be a non-empty string")
    candidate = Path(value)
    path = (candidate if candidate.is_absolute() else root / candidate).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in suffixes:
        raise ValueError("artifact must be a supported file within the project root")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("artifact exceeds the supported size limit")
    return raw, {"path": path.relative_to(root).as_posix(), "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _text(element: ET.Element, path: str) -> str | None:
    matches = element.findall(path)
    if len(matches) > 1:
        raise ValueError(f"ambiguous synthesis field: {path}")
    return matches[0].text.strip() if matches and matches[0].text else None


def _number(element: ET.Element, path: str, *, integer: bool = False, positive: bool = False):
    value = _text(element, path)
    if value is None:
        return None
    if integer:
        return int(value) if re.fullmatch(r"[0-9]+", value) and (not positive or int(value) > 0) else None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) and (number > 0 if positive else number >= 0) else None


def parse_csynth(raw: bytes) -> dict:
    """Parse the profile XML layout; unknown and undefined values remain null."""
    document = raw.decode("utf-8-sig")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", document, re.I):
        raise ValueError("DTD and entity declarations are unsupported")
    profile = ET.fromstring(document)
    if profile.tag != "profile":
        raise ValueError("unsupported HLS report layout: expected profile XML")
    identity = {
        "tool_version": _text(profile, "ReportVersion/Version"),
        "top": _text(profile, "UserAssignments/TopModelName"),
        "part": _text(profile, "UserAssignments/Part"),
        "flow_target": _text(profile, "UserAssignments/FlowTarget"),
    }
    if not identity["top"] or not identity["part"] or not identity["tool_version"]:
        raise ValueError("synthesis report lacks tool version, top or part identity")
    timing = "PerformanceEstimates/SummaryOfTimingAnalysis"
    latency = "PerformanceEstimates/SummaryOfOverallLatency"
    ns = _text(profile, "UserAssignments/unit") == "ns"
    timing_ns = _text(profile, timing + "/unit") == "ns"
    cycles = _text(profile, latency + "/unit") == "clock cycles"
    metrics = {
        "target_clock_ns": _number(profile, "UserAssignments/TargetClockPeriod", positive=True) if ns else None,
        "estimated_clock_ns": _number(profile, timing + "/EstimatedClockPeriod", positive=True) if timing_ns else None,
        "latency_min_cycles": _number(profile, latency + "/Best-caseLatency", integer=True) if cycles else None,
        "latency_max_cycles": _number(profile, latency + "/Worst-caseLatency", integer=True) if cycles else None,
        "interval_min_cycles": _number(profile, latency + "/Interval-min", integer=True, positive=True) if cycles else None,
        "interval_max_cycles": _number(profile, latency + "/Interval-max", integer=True, positive=True) if cycles else None,
    }
    for low, high in (("latency_min_cycles", "latency_max_cycles"), ("interval_min_cycles", "interval_max_cycles")):
        if metrics[low] is not None and metrics[high] is not None and metrics[low] > metrics[high]:
            raise ValueError(f"inverted synthesis range: {low}, {high}")
    resources = {name: _number(profile, f"AreaEstimates/Resources/{name}", integer=True) for name in RESOURCES}
    loops = []
    loops_truncated = False
    for summary in profile.findall("PerformanceEstimates/SummaryOfLoopLatency"):
        for loop in summary:
            if len(loops) == MAX_LOOPS:
                loops_truncated = True
                break
            loops.append({
                "name": _text(loop, "Name") or loop.tag,
                "pipeline_ii": _number(loop, "PipelineII", integer=True, positive=True),
                "pipeline_depth": _number(loop, "PipelineDepth", integer=True),
            })
    return {
        **identity, "metrics": metrics, "resources": resources, "loops": loops,
        "loops_truncated": loops_truncated,
        "missing_metrics": [name for name, value in metrics.items() if value is None]
        + [f"resources.{name}" for name, value in resources.items() if value is None],
    }


def analyze_csynth(root: Path, report_path: str, log_path: str | None = None) -> dict:
    """Collect existing artifacts, without executing tools or certifying freshness."""
    root = root.resolve(strict=True)
    raw, report = _read(root, report_path, {".xml"}, MAX_XML_BYTES)
    parsed = parse_csynth(raw)
    diagnostics = []
    truncated = False
    log = None
    if log_path is not None:
        raw_log, log = _read(root, log_path, {".log", ".rpt", ".txt"}, MAX_LOG_BYTES)
        for line_number, line in enumerate(raw_log.decode("utf-8-sig").splitlines(), 1):
            if DIAGNOSTIC.search(line):
                if len(diagnostics) == MAX_DIAGNOSTICS:
                    truncated = True
                    break
                diagnostics.append({"line": line_number, "text": line[:600], "text_truncated": len(line) > 600})
    return {
        "schema_version": 1, "status": "COLLECTED", "acceptance": "NOT_EVALUATED",
        "evidence_scope": "hls_synthesis_estimate", "source_binding": "UNVERIFIED",
        "hardware_validated": False, "report": report, "log": log,
        **parsed, "diagnostics": diagnostics, "diagnostics_truncated": truncated,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_path")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--log", dest="log_path")
    args = parser.parse_args()
    try:
        result = analyze_csynth(args.root, args.report_path, args.log_path)
    except (OSError, ValueError, ET.ParseError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}))
        return 2
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
