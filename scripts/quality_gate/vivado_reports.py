#!/usr/bin/env python3
"""Versioned, fail-closed parsers for deterministic Vivado report evidence."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


class ReportParseError(ValueError):
    """Raised when a report exists but does not contain trustworthy metrics."""


def _read(path: Path, marker: str) -> str:
    if not path.is_file():
        raise ReportParseError(f"report not found: {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    if marker.lower() not in text.lower():
        raise ReportParseError(f"{path.name} is not a complete {marker} report")
    return text


def _metadata(path: Path, text: str, kind: str) -> dict[str, Any]:
    def field(name: str) -> str | None:
        match = re.search(rf"\|\s*{re.escape(name)}\s*:\s*(.+?)\s*(?:\||$)", text, re.I | re.M)
        return match.group(1).strip() if match else None

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "source": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "tool_version": field("Tool Version"),
        "design": field("Design"),
        "design_state": field("Design State"),
    }


def _numeric_summary_after_header(text: str, header_token: str) -> list[str]:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if header_token not in line:
            continue
        for candidate in lines[index + 1 : index + 8]:
            tokens = candidate.split()
            if len(tokens) < 8:
                continue
            try:
                float(tokens[0])
                float(tokens[1])
                int(tokens[2])
            except ValueError:
                continue
            return tokens
    raise ReportParseError(f"numeric summary row after {header_token!r} is missing")


def parse_timing(path: Path) -> dict[str, Any]:
    text = _read(path, "Design Timing Summary")
    tokens = _numeric_summary_after_header(text, "WNS(ns)")
    try:
        metrics = {
            "wns_ns": float(tokens[0]),
            "tns_ns": float(tokens[1]),
            "setup_failing_endpoints": int(tokens[2]),
            "whs_ns": float(tokens[4]),
            "ths_ns": float(tokens[5]),
            "hold_failing_endpoints": int(tokens[6]),
        }
    except (IndexError, ValueError) as exc:
        raise ReportParseError(f"invalid timing summary row in {path}") from exc
    metrics["constraints_met"] = (
        metrics["wns_ns"] >= 0
        and metrics["whs_ns"] >= 0
        and metrics["setup_failing_endpoints"] == 0
        and metrics["hold_failing_endpoints"] == 0
    )
    result = _metadata(path, text, "timing_summary")
    result["metrics"] = metrics
    return result


def _summary_count(text: str, labels: tuple[str, ...]) -> int | None:
    joined = "|".join(re.escape(label) for label in labels)
    patterns = (
        rf"(?:{joined})\s*(?:violations?|warnings?|checks?)?\s*[:=]\s*(\d+)",
        rf"\|\s*(?:{joined})\s*\|[^\n]*?\|\s*(\d+)\s*\|",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))
    return None


def parse_cdc(path: Path) -> dict[str, Any]:
    text = _read(path, "CDC Report")
    critical = _summary_count(text, ("Critical", "Unsafe"))
    warning = _summary_count(text, ("Warning", "Unknown"))
    info = _summary_count(text, ("Info", "Safe"))

    # Vivado emits a valid short report containing only the report header when
    # there are no CDC paths. Detailed reports contain CDC-* rule identifiers.
    rule_ids = re.findall(r"\bCDC-\d+\b", text, re.I)
    if critical is None and warning is None and info is None:
        if rule_ids:
            critical = len(set(rule_ids))
            warning = 0
            info = 0
        else:
            critical = warning = info = 0

    metrics = {
        "critical": int(critical or 0),
        "warning": int(warning or 0),
        "info": int(info or 0),
    }
    metrics["violations"] = metrics["critical"] + metrics["warning"]
    result = _metadata(path, text, "cdc")
    result["metrics"] = metrics
    return result


def parse_utilization(path: Path) -> dict[str, Any]:
    text = _read(path, "Utilization Design Information")
    row_names = {
        "lut": ("CLB LUTs", "Slice LUTs"),
        "ff": ("CLB Registers", "Slice Registers"),
        "bram": ("Block RAM Tile",),
        "uram": ("URAM",),
        "dsp": ("DSPs",),
    }
    metrics: dict[str, Any] = {}
    for key, aliases in row_names.items():
        row_pattern = "(?:" + "|".join(re.escape(alias) for alias in aliases) + ")"
        match = re.search(
            rf"^\|\s*{row_pattern}\s*\*?\s*\|\s*(\d+(?:\.\d+)?)\s*\|"
            rf"(?:[^\n|]*\|){{3}}\s*<?\s*([\d.]+)\s*\|",
            text,
            re.I | re.M,
        )
        if match:
            used = float(match.group(1))
            metrics[f"{key}_used"] = int(used) if used.is_integer() else used
            metrics[f"{key}_pct"] = float(match.group(2))
    required = {"lut_used", "ff_used", "bram_used", "dsp_used"}
    missing = sorted(required - metrics.keys())
    if missing:
        raise ReportParseError(f"utilization metrics missing in {path.name}: {missing}")
    result = _metadata(path, text, "utilization")
    result["metrics"] = metrics
    return result


def parse_drc(path: Path) -> dict[str, Any]:
    text = _read(path, "Report DRC")
    found_match = re.search(r"Checks found:\s*(\d+)", text, re.I)
    if not found_match:
        raise ReportParseError(f"DRC checks summary is missing in {path.name}")
    critical = warning = error = 0
    for line in text.splitlines():
        match = re.match(
            r"\|\s*[A-Za-z0-9_-]+\s*\|\s*(Critical Warning|Critical|Error|Warning)\s*\|.*\|\s*(\d+)\s*\|",
            line,
            re.I,
        )
        if not match:
            continue
        severity, count_text = match.groups()
        count = int(count_text)
        lowered = severity.lower()
        if "critical" in lowered:
            critical += count
        elif "error" in lowered:
            error += count
        elif "warning" in lowered:
            warning += count
    metrics = {
        "checks_found": int(found_match.group(1)),
        "critical": critical,
        "error": error,
        "warning": warning,
    }
    result = _metadata(path, text, "drc")
    result["metrics"] = metrics
    return result
