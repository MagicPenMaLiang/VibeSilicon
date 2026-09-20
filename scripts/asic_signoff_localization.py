#!/usr/bin/env python3
"""Build deterministic, non-authoritative DRC/LVS localization evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_DRC_ITEMS = 4096
MAX_LVS_MISMATCHES = 4096
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_$./\\\[\]-]+$")
COORDINATE_RE = re.compile(r"\(\s*([*]|-?\d+)\s+([*]|-?\d+)\s*\)")


class SignoffLocalizationError(ValueError):
    """Raised when localization inputs or derived evidence are invalid."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _content_id(value: Mapping[str, Any]) -> str:
    return _sha256_bytes(
        _canonical_bytes(
            {key: item for key, item in value.items() if key != "localization_id"}
        )
    )


def _read_regular(path: Path, label: str) -> bytes:
    try:
        resolved = path.resolve(strict=True)
        if path.is_symlink() or not resolved.is_file():
            raise SignoffLocalizationError(f"{label} must be a regular non-symlink file")
        size = resolved.stat().st_size
        if size <= 0 or size > MAX_INPUT_BYTES:
            raise SignoffLocalizationError(f"{label} size is outside the allowed range")
        return resolved.read_bytes()
    except SignoffLocalizationError:
        raise
    except OSError as exc:
        raise SignoffLocalizationError(f"cannot read {label}") from exc


def _decode_text(raw: bytes, label: str) -> str:
    try:
        value = raw.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as exc:
        raise SignoffLocalizationError(f"{label} must be UTF-8 text") from exc
    if "\r" in value:
        raise SignoffLocalizationError(f"{label} contains unsupported line endings")
    return value


def _clean_quoted(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        value = value[1:-1].replace("''", "'")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise SignoffLocalizationError(f"{label} is invalid")
    return value


def _eda_name(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 512
        or any(ord(character) < 32 for character in value)
    ):
        raise SignoffLocalizationError(f"{label} is invalid")
    return value


def _rounded(value: float) -> float:
    return round(value, 6)


def _drc_items(raw: bytes) -> tuple[str, list[dict[str, Any]]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SignoffLocalizationError("DRC report is invalid XML") from exc
    if root.tag != "report-database":
        raise SignoffLocalizationError("DRC report root is invalid")
    top_cell = _identifier((root.findtext("top-cell") or "").strip(), "DRC top cell")
    items = list(root.iter("item"))
    if len(items) > MAX_DRC_ITEMS:
        raise SignoffLocalizationError("DRC report has too many items")
    result = []
    for index, item in enumerate(items, start=1):
        rule = _clean_quoted(item.findtext("category") or "")
        cell = _clean_quoted(item.findtext("cell") or "")
        _identifier(rule, "DRC rule")
        _identifier(cell, "DRC cell")
        raw_multiplicity = (item.findtext("multiplicity") or "1").strip()
        if not raw_multiplicity.isdigit() or int(raw_multiplicity) < 1:
            raise SignoffLocalizationError("DRC multiplicity is invalid")
        coordinates: list[tuple[float, float]] = []
        values = item.find("values")
        if values is not None:
            for value in values.findall("value"):
                for x, y in re.findall(
                    r"(?:\(|;)(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)",
                    value.text or "",
                ):
                    coordinates.append((float(x), float(y)))
        if not coordinates or any(not math.isfinite(number) for pair in coordinates for number in pair):
            raise SignoffLocalizationError("DRC item has no finite geometry")
        xs = [pair[0] for pair in coordinates]
        ys = [pair[1] for pair in coordinates]
        bbox = [_rounded(min(xs)), _rounded(min(ys)), _rounded(max(xs)), _rounded(max(ys))]
        result.append(
            {
                "index": index,
                "rule": rule,
                "cell": cell,
                "multiplicity": int(raw_multiplicity),
                "bbox_um": bbox,
                "centroid_um": [
                    _rounded((bbox[0] + bbox[2]) / 2),
                    _rounded((bbox[1] + bbox[3]) / 2),
                ],
            }
        )
    return top_cell, result


def _def_section(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^{name}\s+\d+\s*;\s*(.*?)^END\s+{name}\s*$", text
    )
    if match is None:
        raise SignoffLocalizationError(f"DEF {name} section is missing")
    return match.group(1)


def _def_blocks(section: str) -> list[tuple[str, str]]:
    return [
        (match.group(1), match.group(2))
        for match in re.finditer(r"(?ms)^\s*-\s+(\S+)\s+(.*?);\s*$", section)
    ]


def _def_model(raw: bytes) -> dict[str, Any]:
    text = _decode_text(raw, "DEF")
    unit_match = re.search(r"(?m)^UNITS DISTANCE MICRONS (\d+)\s*;\s*$", text)
    design_match = re.search(r"(?m)^DESIGN\s+(\S+)\s*;\s*$", text)
    if unit_match is None or design_match is None:
        raise SignoffLocalizationError("DEF identity or units are missing")
    units = int(unit_match.group(1))
    if units < 1:
        raise SignoffLocalizationError("DEF units are invalid")
    design = _identifier(design_match.group(1), "DEF design")
    components = []
    for instance, body in _def_blocks(_def_section(text, "COMPONENTS")):
        tokens = body.split(None, 1)
        if not tokens:
            raise SignoffLocalizationError("DEF component master is missing")
        master = tokens[0]
        placement = re.search(
            r"\+\s+(?:PLACED|FIXED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)", body
        )
        if placement is None:
            continue
        components.append(
            {
                "instance": _identifier(instance, "DEF instance"),
                "master": _identifier(master, "DEF master"),
                "placement_um": [
                    _rounded(int(placement.group(1)) / units),
                    _rounded(int(placement.group(2)) / units),
                ],
            }
        )
    if not components:
        raise SignoffLocalizationError("DEF has no placed components")
    nets: dict[str, dict[str, Any]] = {}
    for section_name in ("SPECIALNETS", "NETS"):
        for net, body in _def_blocks(_def_section(text, section_name)):
            net = _identifier(net, "DEF net")
            connection_text = body.split("+", 1)[0]
            connections = []
            for instance, pin in re.findall(r"\(\s*(\S+)\s+(\S+)\s*\)", connection_text):
                if instance == "PIN":
                    continue
                connections.append(
                    {
                        "instance": (
                            instance
                            if instance == "*"
                            else _identifier(instance, "DEF net instance")
                        ),
                        "pin": _identifier(pin, "DEF net pin"),
                    }
                )
            segments = []
            previous: tuple[int, int] | None = None
            for line in body.splitlines():
                route = re.search(r"(?:\+\s+ROUTED|NEW)\s+(\S+)\s+", line)
                if route is None:
                    continue
                layer = _identifier(route.group(1), "DEF route layer")
                points = []
                unresolved_wildcard = False
                for raw_x, raw_y in COORDINATE_RE.findall(line):
                    if (raw_x == "*" or raw_y == "*") and previous is None:
                        unresolved_wildcard = True
                        break
                    x = previous[0] if raw_x == "*" else int(raw_x)
                    y = previous[1] if raw_y == "*" else int(raw_y)
                    previous = (x, y)
                    points.append((_rounded(x / units), _rounded(y / units)))
                if unresolved_wildcard:
                    continue
                if len(points) == 1:
                    segments.append((layer, points[0], points[0]))
                else:
                    segments.extend((layer, start, end) for start, end in zip(points, points[1:]))
            nets[net] = {"connections": connections, "segments": segments}
    return {"design": design, "components": components, "nets": nets}


def _point_segment_distance(
    point: Sequence[float], start: Sequence[float], end: Sequence[float]
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0 and dy == 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    projection = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (
        dx * dx + dy * dy
    )
    projection = max(0.0, min(1.0, projection))
    nearest = (start[0] + projection * dx, start[1] + projection * dy)
    return math.hypot(point[0] - nearest[0], point[1] - nearest[1])


def _rule_layers(rule: str) -> set[str]:
    metal = re.match(r"^m(\d+)\.", rule, re.IGNORECASE)
    if metal is not None:
        number = metal.group(1)
        return {f"m{number}", f"met{number}", f"metal{number}"}
    if re.match(r"^li(?:1)?\.", rule, re.IGNORECASE):
        return {"li", "li1"}
    return set()


def _attach_drc_candidates(items: list[dict[str, Any]], model: Mapping[str, Any]) -> None:
    for item in items:
        point = item["centroid_um"]
        instances = []
        for component in model["components"]:
            distance = math.hypot(
                point[0] - component["placement_um"][0],
                point[1] - component["placement_um"][1],
            )
            instances.append((distance, component))
        item["nearest_instances"] = [
            {**component, "distance_um": _rounded(distance)}
            for distance, component in sorted(
                instances, key=lambda pair: (pair[0], pair[1]["instance"])
            )[:3]
        ]
        net_candidates = []
        preferred_layers = _rule_layers(item["rule"])
        for net, details in model["nets"].items():
            distances = [
                (_point_segment_distance(point, start, end), layer)
                for layer, start, end in details["segments"]
                if not preferred_layers or layer.casefold() in preferred_layers
            ]
            if distances:
                distance, layer = min(distances, key=lambda pair: (pair[0], pair[1]))
                net_candidates.append((distance, net, layer))
        item["nearest_nets"] = [
            {
                "net": net,
                "layer": layer,
                "distance_um": _rounded(distance),
                "connections": model["nets"][net]["connections"][:8],
                "connections_truncated": len(model["nets"][net]["connections"]) > 8,
            }
            for distance, net, layer in sorted(
                net_candidates, key=lambda candidate: (candidate[0], candidate[1], candidate[2])
            )[:3]
        ]


def _lvs_top_block(text: str, name: str) -> str:
    marker = f" X({name}\n"
    start = text.find(marker)
    if start < 0:
        raise SignoffLocalizationError(f"LVS top circuit is missing: {name}")
    end = text.find("\n )\n", start)
    if end < 0:
        raise SignoffLocalizationError(f"LVS top circuit is unterminated: {name}")
    return text[start : end + 4]


def _lvs_net_map(block: str) -> dict[int, str]:
    result = {}
    for line in block.splitlines():
        match = re.match(r"^  N\((\d+) I\((.*?)\)\)?$", line)
        if match is not None:
            name = _clean_quoted(match.group(2))
            _eda_name(name, "LVS net")
            result[int(match.group(1))] = name
    if not result:
        raise SignoffLocalizationError("LVS top circuit has no named nets")
    return result


def _def_matches(name: str | None, nets: Mapping[str, Any]) -> list[dict[str, Any]]:
    if name is None:
        return []
    matches = []
    for net, details in sorted(nets.items()):
        if net.casefold() == name.casefold():
            matches.append(
                {
                    "net": net,
                    "connections": details["connections"][:16],
                    "connections_truncated": len(details["connections"]) > 16,
                }
            )
    return matches


def _lvs_summary(raw: bytes, top_cell: str, model: Mapping[str, Any]) -> dict[str, Any]:
    text = _decode_text(raw, "LVS report")
    if not text.startswith("#%lvsdb-klayout\n"):
        raise SignoffLocalizationError("LVS report is not a KLayout LVSDB")
    xref_match = re.search(r"(?m)^ X\((\S+) (\S+) (?:X|1)$", text)
    if xref_match is None:
        raise SignoffLocalizationError("LVS cross-reference header is missing")
    layout_top, reference_top = xref_match.groups()
    if layout_top.casefold() != top_cell.casefold():
        raise SignoffLocalizationError("LVS layout top does not match DRC/DEF top")
    layout_nets = _lvs_net_map(_lvs_top_block(text, layout_top))
    reference_nets = _lvs_net_map(_lvs_top_block(text, reference_top))
    cross_reference = []
    for layout_id, reference_id, status in re.findall(
        r"(?m)^   N\((\(\)|\d+) (\(\)|\d+) ([01])\)$", text[xref_match.start() :]
    ):
        if status != "0":
            continue
        layout_net = None if layout_id == "()" else layout_nets.get(int(layout_id))
        reference_net = (
            None if reference_id == "()" else reference_nets.get(int(reference_id))
        )
        if layout_id != "()" and layout_net is None or reference_id != "()" and reference_net is None:
            raise SignoffLocalizationError("LVS mismatch references an unknown top net")
        kind = (
            "REFERENCE_ONLY"
            if layout_net is None
            else "LAYOUT_ONLY"
            if reference_net is None
            else "MISMATCHED"
        )
        names = sorted({name for name in (layout_net, reference_net) if name is not None})
        cross_reference.append(
            {
                "kind": kind,
                "layout_net": layout_net,
                "reference_net": reference_net,
                "def_matches": [match for name in names for match in _def_matches(name, model["nets"])],
            }
        )
        if len(cross_reference) > MAX_LVS_MISMATCHES:
            raise SignoffLocalizationError("LVS report has too many mismatches")
    messages = [
        {
            "severity": "ERROR" if severity == "E" else "INFO",
            "message": message.replace("''", "'"),
        }
        for severity, message in re.findall(r"(?m)^   M\(([EI]) B\('(.*)'\)\)$", text)
    ]
    return {
        "layout_top": layout_top,
        "reference_top": reference_top,
        "mismatch_count": len(cross_reference),
        "cross_reference": cross_reference,
        "messages": messages,
    }


def build_localization(
    drc_report: Path, lvs_report: Path, def_file: Path
) -> dict[str, Any]:
    drc_raw = _read_regular(drc_report, "DRC report")
    lvs_raw = _read_regular(lvs_report, "LVS report")
    def_raw = _read_regular(def_file, "DEF")
    top_cell, drc = _drc_items(drc_raw)
    model = _def_model(def_raw)
    if model["design"].casefold() != top_cell.casefold():
        raise SignoffLocalizationError("DRC top does not match DEF design")
    _attach_drc_candidates(drc, model)
    counts: dict[str, int] = {}
    for item in drc:
        counts[item["rule"]] = counts.get(item["rule"], 0) + item["multiplicity"]
    value = {
        "schema_version": SCHEMA_VERSION,
        "localization_id": "",
        "status": "DIAGNOSTIC_READY",
        "top_cell": top_cell,
        "sources": {
            "drc_report_sha256": _sha256_bytes(drc_raw),
            "lvs_report_sha256": _sha256_bytes(lvs_raw),
            "def_sha256": _sha256_bytes(def_raw),
        },
        "drc": {
            "violation_count": sum(counts.values()),
            "rule_counts": [
                {"rule": rule, "count": counts[rule]} for rule in sorted(counts)
            ],
            "violations": drc,
        },
        "lvs": _lvs_summary(lvs_raw, top_cell, model),
        "security": {
            "storage_mode": "EXTERNAL_RUN_DIRECTORY_ONLY",
            "contains_design_identifiers": True,
            "contains_layout_coordinates": True,
            "repository_safe": False,
            "signoff_authority": False,
        },
    }
    value["localization_id"] = _content_id(value)
    validate_localization(value)
    return value


def _finite_number(value: Any, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SignoffLocalizationError(f"{label} is invalid")
    if nonnegative and value < 0:
        raise SignoffLocalizationError(f"{label} must be nonnegative")
    return float(value)


def _validate_connections(value: Any, maximum: int, label: str) -> None:
    if not isinstance(value, list) or len(value) > maximum:
        raise SignoffLocalizationError(f"{label} are invalid")
    for connection in value:
        if not isinstance(connection, Mapping) or set(connection) != {"instance", "pin"}:
            raise SignoffLocalizationError(f"{label} entry is invalid")
        if connection["instance"] != "*":
            _identifier(connection["instance"], f"{label} instance")
        _identifier(connection["pin"], f"{label} pin")


def _validate_match(value: Any, label: str) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "net", "connections", "connections_truncated"
    }:
        raise SignoffLocalizationError(f"{label} is invalid")
    _identifier(value["net"], f"{label} net")
    _validate_connections(value["connections"], 16, f"{label} connections")
    if not isinstance(value["connections_truncated"], bool):
        raise SignoffLocalizationError(f"{label} truncation flag is invalid")


def validate_localization(value: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "localization_id", "status", "top_cell", "sources",
        "drc", "lvs", "security",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise SignoffLocalizationError("localization fields are invalid")
    if value["schema_version"] != SCHEMA_VERSION or value["status"] != "DIAGNOSTIC_READY":
        raise SignoffLocalizationError("localization schema or status is invalid")
    if value["localization_id"] != _content_id(value):
        raise SignoffLocalizationError("localization identity does not match content")
    _identifier(value["top_cell"], "localization top cell")
    sources = value["sources"]
    if not isinstance(sources, Mapping) or set(sources) != {
        "drc_report_sha256", "lvs_report_sha256", "def_sha256"
    } or any(not isinstance(item, str) or not HASH_RE.fullmatch(item) for item in sources.values()):
        raise SignoffLocalizationError("localization sources are invalid")
    drc = value["drc"]
    if not isinstance(drc, Mapping) or set(drc) != {"violation_count", "rule_counts", "violations"}:
        raise SignoffLocalizationError("DRC localization is invalid")
    if not isinstance(drc["violations"], list) or len(drc["violations"]) > MAX_DRC_ITEMS:
        raise SignoffLocalizationError("DRC violations are invalid")
    expected_counts: dict[str, int] = {}
    for index, item in enumerate(drc["violations"], start=1):
        if not isinstance(item, Mapping) or set(item) != {
            "index", "rule", "cell", "multiplicity", "bbox_um", "centroid_um",
            "nearest_instances", "nearest_nets",
        } or item["index"] != index:
            raise SignoffLocalizationError("DRC violation entry is invalid")
        _identifier(item["rule"], "DRC rule")
        _identifier(item["cell"], "DRC cell")
        if isinstance(item["multiplicity"], bool) or not isinstance(item["multiplicity"], int) or item["multiplicity"] < 1:
            raise SignoffLocalizationError("DRC multiplicity is invalid")
        expected_counts[item["rule"]] = expected_counts.get(item["rule"], 0) + item["multiplicity"]
        if not isinstance(item["bbox_um"], list) or len(item["bbox_um"]) != 4 or not all(isinstance(number, (int, float)) and math.isfinite(number) for number in item["bbox_um"]):
            raise SignoffLocalizationError("DRC bounding box is invalid")
        bbox = [_finite_number(number, "DRC bounding box") for number in item["bbox_um"]]
        if bbox[0] > bbox[2] or bbox[1] > bbox[3]:
            raise SignoffLocalizationError("DRC bounding box order is invalid")
        expected_centroid = [
            _rounded((bbox[0] + bbox[2]) / 2),
            _rounded((bbox[1] + bbox[3]) / 2),
        ]
        if item["centroid_um"] != expected_centroid:
            raise SignoffLocalizationError("DRC centroid is invalid")
        if not isinstance(item["nearest_instances"], list) or not 1 <= len(item["nearest_instances"]) <= 3:
            raise SignoffLocalizationError("DRC instance candidates are invalid")
        instance_order = []
        for candidate in item["nearest_instances"]:
            if not isinstance(candidate, Mapping) or set(candidate) != {
                "instance", "master", "placement_um", "distance_um"
            }:
                raise SignoffLocalizationError("DRC instance candidate is invalid")
            _identifier(candidate["instance"], "DRC candidate instance")
            _identifier(candidate["master"], "DRC candidate master")
            placement = candidate["placement_um"]
            if not isinstance(placement, list) or len(placement) != 2:
                raise SignoffLocalizationError("DRC candidate placement is invalid")
            for number in placement:
                _finite_number(number, "DRC candidate placement")
            distance = _finite_number(
                candidate["distance_um"], "DRC candidate distance", nonnegative=True
            )
            instance_order.append((distance, candidate["instance"]))
        if instance_order != sorted(instance_order):
            raise SignoffLocalizationError("DRC instance candidates are not canonical")
        if not isinstance(item["nearest_nets"], list) or len(item["nearest_nets"]) > 3:
            raise SignoffLocalizationError("DRC net candidates are invalid")
        net_order = []
        for candidate in item["nearest_nets"]:
            if not isinstance(candidate, Mapping) or set(candidate) != {
                "net", "layer", "distance_um", "connections", "connections_truncated"
            }:
                raise SignoffLocalizationError("DRC net candidate is invalid")
            _identifier(candidate["net"], "DRC candidate net")
            _identifier(candidate["layer"], "DRC candidate layer")
            distance = _finite_number(
                candidate["distance_um"], "DRC net distance", nonnegative=True
            )
            _validate_connections(candidate["connections"], 8, "DRC net connections")
            if not isinstance(candidate["connections_truncated"], bool):
                raise SignoffLocalizationError("DRC net truncation flag is invalid")
            net_order.append((distance, candidate["net"], candidate["layer"]))
        if net_order != sorted(net_order):
            raise SignoffLocalizationError("DRC net candidates are not canonical")
    expected_rule_counts = [
        {"rule": rule, "count": expected_counts[rule]} for rule in sorted(expected_counts)
    ]
    if drc["rule_counts"] != expected_rule_counts or drc["violation_count"] != sum(expected_counts.values()):
        raise SignoffLocalizationError("DRC summary is inconsistent")
    lvs = value["lvs"]
    if not isinstance(lvs, Mapping) or set(lvs) != {
        "layout_top", "reference_top", "mismatch_count", "cross_reference", "messages"
    }:
        raise SignoffLocalizationError("LVS localization is invalid")
    _identifier(lvs["layout_top"], "LVS layout top")
    _identifier(lvs["reference_top"], "LVS reference top")
    if lvs["layout_top"].casefold() != value["top_cell"].casefold():
        raise SignoffLocalizationError("LVS layout top does not match localization top")
    if not isinstance(lvs["cross_reference"], list) or len(lvs["cross_reference"]) > MAX_LVS_MISMATCHES or lvs["mismatch_count"] != len(lvs["cross_reference"]):
        raise SignoffLocalizationError("LVS mismatch summary is inconsistent")
    for mismatch in lvs["cross_reference"]:
        if not isinstance(mismatch, Mapping) or set(mismatch) != {
            "kind", "layout_net", "reference_net", "def_matches"
        }:
            raise SignoffLocalizationError("LVS mismatch entry is invalid")
        layout_net = mismatch["layout_net"]
        reference_net = mismatch["reference_net"]
        if layout_net is not None:
            _eda_name(layout_net, "LVS layout net")
        if reference_net is not None:
            _eda_name(reference_net, "LVS reference net")
        expected_kind = (
            "REFERENCE_ONLY"
            if layout_net is None and reference_net is not None
            else "LAYOUT_ONLY"
            if reference_net is None and layout_net is not None
            else "MISMATCHED"
            if layout_net is not None and reference_net is not None
            else None
        )
        if mismatch["kind"] != expected_kind:
            raise SignoffLocalizationError("LVS mismatch kind is inconsistent")
        if not isinstance(mismatch["def_matches"], list):
            raise SignoffLocalizationError("LVS DEF matches are invalid")
        for match in mismatch["def_matches"]:
            _validate_match(match, "LVS DEF match")
    if not isinstance(lvs["messages"], list) or len(lvs["messages"]) > 4096:
        raise SignoffLocalizationError("LVS messages are invalid")
    for message in lvs["messages"]:
        if not isinstance(message, Mapping) or set(message) != {"severity", "message"}:
            raise SignoffLocalizationError("LVS message entry is invalid")
        if message["severity"] not in {"ERROR", "INFO"}:
            raise SignoffLocalizationError("LVS message severity is invalid")
        if not isinstance(message["message"], str) or not message["message"] or len(message["message"]) > 4096:
            raise SignoffLocalizationError("LVS message text is invalid")
    security = value["security"]
    expected_security = {
        "storage_mode": "EXTERNAL_RUN_DIRECTORY_ONLY",
        "contains_design_identifiers": True,
        "contains_layout_coordinates": True,
        "repository_safe": False,
        "signoff_authority": False,
    }
    if security != expected_security:
        raise SignoffLocalizationError("localization security boundary is invalid")


def write_localization(value: Mapping[str, Any], output: Path) -> None:
    validate_localization(value)
    if output.exists():
        raise SignoffLocalizationError(f"refusing to overwrite localization output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical_bytes(value) + b"\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--drc-report", type=Path, required=True)
    build.add_argument("--lvs-report", type=Path, required=True)
    build.add_argument("--def-file", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("localization", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            value = build_localization(args.drc_report, args.lvs_report, args.def_file)
            write_localization(value, args.output)
        else:
            value = json.loads(_read_regular(args.localization, "localization").decode("utf-8"))
            validate_localization(value)
    except (SignoffLocalizationError, json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "PASS", "identity": value["localization_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
