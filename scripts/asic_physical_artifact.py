#!/usr/bin/env python3
"""Run the fixed A03 OpenROAD flow and finalize RTL-to-GDS evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

try:
    from scripts import asic_backend_contract as backend
    from scripts import asic_input_evidence as input_contract
    from scripts import asic_signoff_localization as signoff_localization
    from scripts import asic_synth_sta_adapter as synth_sta
except ImportError:  # pragma: no cover - standalone execution
    import asic_backend_contract as backend
    import asic_input_evidence as input_contract
    import asic_signoff_localization as signoff_localization
    import asic_synth_sta_adapter as synth_sta


SCHEMA_VERSION = 1
RUN_STATUS = "A03_PHYSICAL_RUN_COMPLETE"
FINAL_STATUS = "A03_RTL_TO_GDS_FINALIZED"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
DRC_RE = re.compile(r"\bVIBESILICON_DRC_COUNT=(\d+)\b")
TRACK_LINE_RE = re.compile(
    r"^make_tracks ([A-Za-z_][A-Za-z0-9_]*) "
    r"-x_offset ([0-9]+(?:\.[0-9]+)?) -x_pitch ([0-9]+(?:\.[0-9]+)?) "
    r"-y_offset ([0-9]+(?:\.[0-9]+)?) -y_pitch ([0-9]+(?:\.[0-9]+)?)$"
)
RC_NUMBER = r"[0-9]+(?:\.[0-9]+)?(?:[Ee][+-]?[0-9]+)?"
RC_LAYER_RE = re.compile(
    rf"^set_layer_rc -layer ([A-Za-z_][A-Za-z0-9_]*) "
    rf"-capacitance ({RC_NUMBER}) -resistance ({RC_NUMBER})$"
)
RC_VIA_RE = re.compile(
    rf"^set_layer_rc -via ([A-Za-z_][A-Za-z0-9_]*) -resistance ({RC_NUMBER})$"
)
RC_WIRE_RE = re.compile(
    r"^set_wire_rc -(signal|clock) -layer ([A-Za-z_][A-Za-z0-9_]*)$"
)
PHYSICAL_CONFIG_SCHEMA_VERSION = 2
CONFIG_FIELDS = {
    "schema_version",
    "floorplan",
    "placement",
    "optimization",
    "routing",
}
FLOORPLAN_FIELDS = {"die_area_um", "core_area_um", "site"}
PLACEMENT_FIELDS = {"pin_horizontal_layer", "pin_vertical_layer", "filler_cells"}
OPTIMIZATION_FIELDS = {
    "placement_density",
    "timing_driven_placement",
    "routability_driven_placement",
    "force_center_initial_place",
    "min_phi_coefficient",
    "max_phi_coefficient",
    "match_cell_footprint",
    "cts_sink_clustering",
    "cts_repair_clock_nets",
    "post_global_route_repair",
}
ROUTING_FIELDS = {
    "signal_layers",
    "clock_layers",
    "signal_wire_rc_layer",
    "clock_wire_rc_layer",
    "global_layer_adjustment",
    "via_in_pin_layer",
    "detailed_route_end_iteration",
    "detailed_route_seed",
    "detailed_route_k",
}
PHYSICAL_RULE_FIELDS = {
    "schema_version",
    "global_connections",
    "tapcell",
    "pdn",
}
GLOBAL_CONNECTION_FIELDS = {"net", "pin", "type"}
TAPCELL_FIELDS = {"distance_um", "tapcell_master"}
PDN_FIELDS = {"voltage_domains", "grids", "stripes", "connects"}
VOLTAGE_DOMAIN_FIELDS = {"name", "power_net", "ground_net"}
STANDARD_GRID_FIELDS = {"name", "kind", "voltage_domain", "pins"}
MACRO_GRID_FIELDS = {
    "name",
    "kind",
    "voltage_domain",
    "orientations",
    "halo_um",
    "default",
    "grid_over_boundary",
}
PDN_STRIPE_FIELDS = {
    "grid",
    "layer",
    "width_um",
    "pitch_um",
    "offset_um",
    "followpins",
}
PDN_CONNECT_FIELDS = {"grid", "layers"}
ORIENTATIONS = {"R0", "R90", "R180", "R270", "MX", "MY", "MXR90", "MYR90"}
APPROVAL_FIELDS = {
    "schema_version",
    "status",
    "scope",
    "approved_by",
    "approved_at",
    "expires_at",
    "backend_contract_id",
    "capability_id",
    "input_evidence_id",
    "a02_evidence_id",
    "physical_config_sha256",
}
RUN_FIELDS = {
    "schema_version",
    "evidence_id",
    "policy_id",
    "backend_id",
    "backend_contract_id",
    "capability_id",
    "input_evidence_id",
    "a02_evidence_id",
    "approval_sha256",
    "physical_config_sha256",
    "executed_at",
    "status",
    "result_status",
    "tools",
    "commands",
    "metrics",
    "artifacts",
    "execution_mode",
    "execution_authorized",
    "network_access",
    "raw_paths_exposed",
    "source_copied_into_repository",
    "asic_metrics_mixed_with_fpga",
    "next_gate",
    "closure_status",
}
RUN_METRIC_FIELDS = {
    "standard_cell_area_um2",
    "wns_ns",
    "tns_ns",
    "timing_met",
    "drc_count",
    "drc_rule_counts",
    "drc_clean",
}
RUN_ARTIFACT_ROLES = (
    "cdl",
    "drc_report",
    "drc_stderr",
    "drc_stdout",
    "route_drc_report",
    "lvs_extracted",
    "lvs_reference",
    "lvs_report",
    "signoff_localization",
    "lvs_stderr",
    "lvs_stdout",
    "def",
    "gds",
    "gds_export_script",
    "klayout_stderr",
    "klayout_stdout",
    "openroad_stderr",
    "openroad_stdout",
    "physical_script",
    "postroute_netlist",
    "spef",
)
KLAYOUT_EXPORT_SCRIPT = """import sys

import pya


technology = pya.Technology()
technology.load(tech_file)
options = technology.load_layout_options
options.lefdef_config.lef_files = [tech_lef, cell_lef]

source = pya.Layout()
source.read(in_def, options)
source_top = source.cell(design_name)
if source_top is None:
    print(f"[ERROR] DEF top cell is missing: {design_name}")
    sys.exit(1)

top_index = source_top.cell_index()
for cell in source.each_cell():
    if cell.cell_index() != top_index:
        if not cell.name.startswith("VIA_") and not cell.name.endswith("_DEF_FILL"):
            cell.clear()

source.read(in_gds)
output = pya.Layout()
output.dbu = source.dbu
output_top = output.create_cell(design_name)
output_top.copy_tree(source_top)

errors = 0
for cell in output.each_cell():
    if cell.is_empty():
        print(f"[ERROR] Referenced cell has no stream geometry: {cell.name}")
        errors += 1
    if cell.name != design_name and cell.parent_cells() == 0:
        print(f"[ERROR] Orphan cell in final stream: {cell.name}")
        errors += 1
if errors:
    sys.exit(errors)

output.write(out_file)
print(f"VIBESILICON_GDS_EXPORT={out_file}")
"""
LVS_FIELDS = {
    "schema_version",
    "receipt_id",
    "status",
    "checker_id",
    "checker_version",
    "checked_at",
    "reviewed_by",
    "pdk_input_evidence_id",
    "gds_sha256",
    "reference_netlist_sha256",
    "lvs_rules_sha256",
    "top_cell",
    "report_path",
    "report_sha256",
    "report_bytes",
    "layout_instance_count",
    "schematic_instance_count",
    "mismatched_nets",
    "mismatched_devices",
}
FINAL_FIELDS = {
    "schema_version",
    "manifest_id",
    "policy_id",
    "backend_id",
    "input_evidence_id",
    "a02_evidence_id",
    "physical_evidence_id",
    "lvs_receipt_id",
    "status",
    "result_status",
    "checks",
    "metrics",
    "artifacts",
    "gds_alone_is_pass",
    "additional_execution_authorized",
    "raw_paths_exposed",
    "asic_metrics_mixed_with_fpga",
    "next_gate",
    "closure_status",
}
FINAL_ARTIFACT_ROLES = (
    "cdl",
    "lvs_reference",
    "def",
    "drc_report",
    "gds",
    "lvs_report",
    "postroute_netlist",
    "spef",
)
Runner = Callable[..., subprocess.CompletedProcess[str]]
Resolver = Callable[[str], str | None]


class AsicPhysicalError(ValueError):
    """Raised when A03 execution or artifact finalization fails closed."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _content_id(value: Mapping[str, Any], field: str) -> str:
    payload = {key: item for key, item in value.items() if key != field}
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _write_lvs_reference(output: Path, top_cdl: Path, master_spice: Path) -> None:
    """Create the exact combined netlist consumed by transistor-level LVS."""
    if output.exists():
        raise AsicPhysicalError("A03 LVS reference already exists")
    try:
        with output.open("xb") as destination:
            for source in (top_cdl, master_spice):
                with source.open("rb") as stream:
                    shutil.copyfileobj(stream, destination)
                destination.write(b"\n")
    except OSError as exc:
        raise AsicPhysicalError("A03 LVS reference could not be created") from exc


def _signoff_drc_summary(report: Path) -> tuple[int, list[dict[str, Any]]]:
    """Count signoff DRC items and group them by KLayout rule category."""
    try:
        root = ET.parse(report).getroot()
    except (OSError, ET.ParseError) as exc:
        raise AsicPhysicalError("A03 signoff DRC report is invalid") from exc
    if root.tag != "report-database":
        raise AsicPhysicalError("A03 signoff DRC report root is invalid")
    counts: dict[str, int] = {}
    for item in root.iter("item"):
        category = item.findtext("category")
        if category is None:
            raise AsicPhysicalError("A03 signoff DRC item has no rule category")
        raw_rule = category.strip()
        rule = (
            raw_rule[1:-1]
            if len(raw_rule) >= 2 and raw_rule[0] == raw_rule[-1] == "'"
            else raw_rule
        )
        if (
            not rule
            or len(rule) > 128
            or any(ord(character) < 32 for character in rule)
        ):
            raise AsicPhysicalError("A03 signoff DRC rule category is invalid")
        counts[rule] = counts.get(rule, 0) + 1
    grouped = [{"rule": rule, "count": counts[rule]} for rule in sorted(counts)]
    return sum(counts.values()), grouped


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AsicPhysicalError(f"cannot load A03 JSON: {path}") from exc


def _fields(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise AsicPhysicalError(f"{label} fields are invalid")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise AsicPhysicalError(f"{label} is invalid")
    if any(word in value.lower() for word in input_contract.BLOCKED_WORDS):
        raise AsicPhysicalError(f"{label} contains placeholder text")
    return value


def _coordinates(value: Any, label: str) -> tuple[float, float, float, float]:
    if not isinstance(value, list) or len(value) != 4:
        raise AsicPhysicalError(f"{label} must contain four coordinates")
    numbers = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise AsicPhysicalError(f"{label} coordinates must be numeric")
        number = float(item)
        if not math.isfinite(number) or number < 0:
            raise AsicPhysicalError(f"{label} coordinates are invalid")
        numbers.append(number)
    x1, y1, x2, y2 = numbers
    if x1 >= x2 or y1 >= y2:
        raise AsicPhysicalError(f"{label} has an invalid rectangle")
    return x1, y1, x2, y2


def _number(value: Any, label: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AsicPhysicalError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (not allow_zero and number == 0):
        raise AsicPhysicalError(f"{label} is outside the allowlisted range")
    if number > 10000:
        raise AsicPhysicalError(f"{label} is outside the allowlisted range")
    return number


def _number_text(value: Any) -> str:
    return format(float(value), ".15g")


def _identifier_list(
    value: Any, label: str, *, maximum: int = 16
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > maximum
        or not all(isinstance(item, str) for item in value)
        or len(set(value)) != len(value)
    ):
        raise AsicPhysicalError(f"{label} is invalid")
    return tuple(_identifier(item, label) for item in value)


def _physical_rule_commands(path: Path) -> tuple[str, ...]:
    """Translate declarative, evidence-bound PDK data into fixed OpenROAD commands."""
    try:
        if path.stat().st_size > 64 * 1024:
            raise AsicPhysicalError("A03 physical rules are too large")
        value = json.loads(path.read_text(encoding="utf-8"))
    except AsicPhysicalError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AsicPhysicalError("cannot read A03 physical rules JSON") from exc
    rules = _fields(value, PHYSICAL_RULE_FIELDS, "A03 physical rules")
    if rules["schema_version"] != SCHEMA_VERSION:
        raise AsicPhysicalError("A03 physical rules schema_version is invalid")

    connections = rules["global_connections"]
    if not isinstance(connections, list) or not 2 <= len(connections) <= 64:
        raise AsicPhysicalError("A03 global connections must contain 2 to 64 rules")
    connection_commands = []
    connection_keys = set()
    connection_pins = set()
    primary_power_nets = set()
    primary_ground_nets = set()
    for item in connections:
        connection = _fields(
            item, GLOBAL_CONNECTION_FIELDS, "A03 global connection"
        )
        net = _identifier(connection["net"], "A03 global connection net")
        pin = _identifier(connection["pin"], "A03 global connection pin")
        connection_type = connection["type"]
        if connection_type not in {"POWER", "GROUND", "SECONDARY"}:
            raise AsicPhysicalError("A03 global connection type is invalid")
        key = (net, pin)
        if key in connection_keys or pin in connection_pins:
            raise AsicPhysicalError("A03 global connections contain duplicates")
        connection_keys.add(key)
        connection_pins.add(pin)
        flag = ""
        if connection_type == "POWER":
            primary_power_nets.add(net)
            flag = " -power"
        elif connection_type == "GROUND":
            primary_ground_nets.add(net)
            flag = " -ground"
        connection_commands.append(
            f"add_global_connection -net {{{net}}} -inst_pattern {{.*}} "
            f"-pin_pattern {{^{pin}$}}{flag}"
        )
    if not primary_power_nets or not primary_ground_nets:
        raise AsicPhysicalError("A03 physical rules require primary power and ground")
    if primary_power_nets & primary_ground_nets:
        raise AsicPhysicalError("A03 power and ground nets must be disjoint")
    if {item[0] for item in connection_keys} - (
        primary_power_nets | primary_ground_nets
    ):
        raise AsicPhysicalError("A03 secondary supply rule has no primary net")

    tapcell = _fields(rules["tapcell"], TAPCELL_FIELDS, "A03 tapcell rules")
    tap_master = _identifier(tapcell["tapcell_master"], "A03 tapcell master")
    _number(tapcell["distance_um"], "A03 tapcell distance")

    pdn = _fields(rules["pdn"], PDN_FIELDS, "A03 PDN rules")
    domains = pdn["voltage_domains"]
    if not isinstance(domains, list) or not 1 <= len(domains) <= 16:
        raise AsicPhysicalError("A03 PDN voltage domains are invalid")
    domain_commands = []
    domain_names = set()
    for item in domains:
        domain = _fields(item, VOLTAGE_DOMAIN_FIELDS, "A03 PDN voltage domain")
        name = _identifier(domain["name"], "A03 PDN voltage domain name")
        power = _identifier(domain["power_net"], "A03 PDN power net")
        ground = _identifier(domain["ground_net"], "A03 PDN ground net")
        if name in domain_names or power == ground:
            raise AsicPhysicalError("A03 PDN voltage domain is duplicated or invalid")
        if power not in primary_power_nets or ground not in primary_ground_nets:
            raise AsicPhysicalError("A03 PDN domain is not bound to primary supply rules")
        domain_names.add(name)
        domain_commands.append(
            f"set_voltage_domain -name {{{name}}} -power {{{power}}} -ground {{{ground}}}"
        )

    grids = pdn["grids"]
    if not isinstance(grids, list) or not 1 <= len(grids) <= 32:
        raise AsicPhysicalError("A03 PDN grids are invalid")
    grid_commands = []
    grid_names = set()
    standard_grids = set()
    for item in grids:
        if not isinstance(item, dict) or item.get("kind") not in {"STANDARD", "MACRO"}:
            raise AsicPhysicalError("A03 PDN grid kind is invalid")
        kind = item["kind"]
        expected = STANDARD_GRID_FIELDS if kind == "STANDARD" else MACRO_GRID_FIELDS
        grid = _fields(item, expected, "A03 PDN grid")
        name = _identifier(grid["name"], "A03 PDN grid name")
        domain = _identifier(grid["voltage_domain"], "A03 PDN grid domain")
        if name in grid_names or domain not in domain_names:
            raise AsicPhysicalError("A03 PDN grid identity or domain is invalid")
        grid_names.add(name)
        if kind == "STANDARD":
            pins = _identifier_list(grid["pins"], "A03 PDN grid pin layer")
            standard_grids.add(name)
            grid_commands.append(
                f"define_pdn_grid -name {{{name}}} -voltage_domains {{{domain}}} "
                f"-pins {{{' '.join(pins)}}}"
            )
        else:
            orientations = _identifier_list(
                grid["orientations"], "A03 PDN macro orientation", maximum=8
            )
            if not set(orientations).issubset(ORIENTATIONS):
                raise AsicPhysicalError("A03 PDN macro orientation is invalid")
            halo = grid["halo_um"]
            if not isinstance(halo, list) or len(halo) != 4:
                raise AsicPhysicalError("A03 PDN macro halo must contain four values")
            for number in halo:
                _number(number, "A03 PDN macro halo", allow_zero=True)
            if not isinstance(grid["default"], bool) or not isinstance(
                grid["grid_over_boundary"], bool
            ):
                raise AsicPhysicalError("A03 PDN macro flags are invalid")
            flags = ""
            if grid["default"]:
                flags += " -default"
            if grid["grid_over_boundary"]:
                flags += " -grid_over_boundary"
            grid_commands.append(
                f"define_pdn_grid -name {{{name}}} -voltage_domains {{{domain}}} -macro "
                f"-orient {{{' '.join(orientations)}}} "
                f"-halo {{{' '.join(_number_text(number) for number in halo)}}}{flags}"
            )
    if not standard_grids:
        raise AsicPhysicalError("A03 PDN requires a standard-cell grid")

    stripes = pdn["stripes"]
    if not isinstance(stripes, list) or not 1 <= len(stripes) <= 64:
        raise AsicPhysicalError("A03 PDN stripes are invalid")
    stripe_commands = []
    stripe_keys = set()
    striped_grids = set()
    for item in stripes:
        stripe = _fields(item, PDN_STRIPE_FIELDS, "A03 PDN stripe")
        grid = _identifier(stripe["grid"], "A03 PDN stripe grid")
        layer = _identifier(stripe["layer"], "A03 PDN stripe layer")
        if grid not in grid_names or (grid, layer) in stripe_keys:
            raise AsicPhysicalError("A03 PDN stripe target is invalid or duplicated")
        for field in ("width_um", "pitch_um"):
            _number(stripe[field], f"A03 PDN stripe {field}")
        _number(stripe["offset_um"], "A03 PDN stripe offset", allow_zero=True)
        if float(stripe["width_um"]) >= float(stripe["pitch_um"]):
            raise AsicPhysicalError("A03 PDN stripe width must be below pitch")
        if float(stripe["offset_um"]) >= float(stripe["pitch_um"]):
            raise AsicPhysicalError("A03 PDN stripe offset must be below pitch")
        if not isinstance(stripe["followpins"], bool):
            raise AsicPhysicalError("A03 PDN stripe followpins must be boolean")
        stripe_keys.add((grid, layer))
        striped_grids.add(grid)
        followpins = " -followpins" if stripe["followpins"] else ""
        stripe_commands.append(
            f"add_pdn_stripe -grid {{{grid}}} -layer {{{layer}}} "
            f"-width {{{_number_text(stripe['width_um'])}}} "
            f"-pitch {{{_number_text(stripe['pitch_um'])}}} "
            f"-offset {{{_number_text(stripe['offset_um'])}}}{followpins}"
        )
    if not standard_grids.issubset(striped_grids):
        raise AsicPhysicalError("A03 standard PDN grids require at least one stripe")

    connects = pdn["connects"]
    if not isinstance(connects, list) or not 1 <= len(connects) <= 64:
        raise AsicPhysicalError("A03 PDN connects are invalid")
    connect_commands = []
    connect_keys = set()
    connected_grids = set()
    for item in connects:
        connect = _fields(item, PDN_CONNECT_FIELDS, "A03 PDN connect")
        grid = _identifier(connect["grid"], "A03 PDN connect grid")
        layers = _identifier_list(
            connect["layers"], "A03 PDN connect layer", maximum=2
        )
        if len(layers) != 2 or grid not in grid_names:
            raise AsicPhysicalError("A03 PDN connect target is invalid")
        key = (grid, tuple(sorted(layers)))
        if key in connect_keys:
            raise AsicPhysicalError("A03 PDN connects contain duplicates")
        connect_keys.add(key)
        connected_grids.add(grid)
        connect_commands.append(
            f"add_pdn_connect -grid {{{grid}}} -layers {{{' '.join(layers)}}}"
        )
    if not grid_names.issubset(connected_grids):
        raise AsicPhysicalError("A03 each PDN grid requires a layer connection")

    return tuple(
        [
            *connection_commands,
            f"tapcell -distance {_number_text(tapcell['distance_um'])} "
            f"-tapcell_master {tap_master}",
            "global_connect",
            *domain_commands,
            *grid_commands,
            *stripe_commands,
            *connect_commands,
            "pdngen",
        ]
    )


def validate_config(value: Any) -> None:
    config = _fields(value, CONFIG_FIELDS, "A03 physical config")
    if config["schema_version"] != PHYSICAL_CONFIG_SCHEMA_VERSION:
        raise AsicPhysicalError("A03 physical config schema_version is invalid")
    floorplan = _fields(config["floorplan"], FLOORPLAN_FIELDS, "A03 floorplan")
    die = _coordinates(floorplan["die_area_um"], "A03 die area")
    core = _coordinates(floorplan["core_area_um"], "A03 core area")
    if not (die[0] <= core[0] < core[2] <= die[2] and die[1] <= core[1] < core[3] <= die[3]):
        raise AsicPhysicalError("A03 core area must be inside die area")
    _identifier(floorplan["site"], "A03 placement site")
    placement = _fields(config["placement"], PLACEMENT_FIELDS, "A03 placement")
    _identifier(placement["pin_horizontal_layer"], "A03 horizontal pin layer")
    _identifier(placement["pin_vertical_layer"], "A03 vertical pin layer")
    cells = placement["filler_cells"]
    if (
        not isinstance(cells, list)
        or not cells
        or len(cells) > 64
        or not all(isinstance(item, str) for item in cells)
        or len(set(cells)) != len(cells)
    ):
        raise AsicPhysicalError("A03 filler cells are invalid")
    for cell in cells:
        _identifier(cell, "A03 filler cell")
    optimization = _fields(
        config["optimization"], OPTIMIZATION_FIELDS, "A03 optimization"
    )
    for name in (
        "timing_driven_placement",
        "routability_driven_placement",
        "force_center_initial_place",
        "match_cell_footprint",
        "cts_sink_clustering",
        "cts_repair_clock_nets",
        "post_global_route_repair",
    ):
        if not isinstance(optimization[name], bool):
            raise AsicPhysicalError(f"A03 {name} must be boolean")
    for name, minimum, maximum in (
        ("placement_density", 0.30, 0.90),
        ("min_phi_coefficient", 0.50, 1.50),
        ("max_phi_coefficient", 0.50, 1.50),
    ):
        item = optimization[name]
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise AsicPhysicalError(f"A03 {name} must be numeric")
        number = float(item)
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise AsicPhysicalError(f"A03 {name} is outside the allowlisted range")
    if optimization["min_phi_coefficient"] > optimization["max_phi_coefficient"]:
        raise AsicPhysicalError(
            "A03 min_phi_coefficient must not exceed max_phi_coefficient"
        )
    routing = _fields(config["routing"], ROUTING_FIELDS, "A03 routing")
    for name in ("signal_wire_rc_layer", "clock_wire_rc_layer", "via_in_pin_layer"):
        _identifier(routing[name], f"A03 {name}")
    for name in ("signal_layers", "clock_layers"):
        value = routing[name]
        if not isinstance(value, str) or len(value.split("-")) != 2:
            raise AsicPhysicalError(f"A03 {name} must be an explicit layer range")
        for layer in value.split("-"):
            _identifier(layer, f"A03 {name}")
    adjustment = synth_sta._number(
        routing["global_layer_adjustment"], "A03 global layer adjustment"
    )
    if not 0 <= adjustment <= 1:
        raise AsicPhysicalError("A03 global layer adjustment must be between zero and one")
    for name, minimum, maximum in (
        ("detailed_route_end_iteration", 1, 128),
        ("detailed_route_seed", 0, 2_147_483_647),
        ("detailed_route_k", 1, 64),
    ):
        item = routing[name]
        if (
            isinstance(item, bool)
            or not isinstance(item, int)
            or not minimum <= item <= maximum
        ):
            raise AsicPhysicalError(f"A03 {name} is outside the allowlisted range")


def config_sha256(value: Any) -> str:
    validate_config(value)
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _track_commands(path: Path) -> tuple[str, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AsicPhysicalError("cannot read A03 track definition") from exc
    if len(text.encode("utf-8")) > 64 * 1024:
        raise AsicPhysicalError("A03 track definition is too large")
    commands = []
    layers = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = TRACK_LINE_RE.fullmatch(line)
        if match is None:
            raise AsicPhysicalError("A03 track definition contains non-allowlisted Tcl")
        layer, x_offset, x_pitch, y_offset, y_pitch = match.groups()
        if layer in layers:
            raise AsicPhysicalError("A03 track definition contains duplicate layers")
        if float(x_pitch) <= 0 or float(y_pitch) <= 0:
            raise AsicPhysicalError("A03 track pitches must be positive")
        layers.add(layer)
        commands.append(
            f"make_tracks {layer} -x_offset {x_offset} -x_pitch {x_pitch} "
            f"-y_offset {y_offset} -y_pitch {y_pitch}"
        )
    if not commands or len(commands) > 64:
        raise AsicPhysicalError("A03 track definition must contain 1 to 64 layers")
    return tuple(commands)


def _rc_commands(path: Path) -> tuple[str, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AsicPhysicalError("cannot read A03 RC definition") from exc
    if len(text.encode("utf-8")) > 64 * 1024:
        raise AsicPhysicalError("A03 RC definition is too large")
    commands = []
    keys = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        layer = RC_LAYER_RE.fullmatch(line)
        via = RC_VIA_RE.fullmatch(line)
        wire = RC_WIRE_RE.fullmatch(line)
        if layer:
            key = ("layer", layer.group(1))
            if float(layer.group(2)) <= 0 or float(layer.group(3)) <= 0:
                raise AsicPhysicalError("A03 RC layer values must be positive")
        elif via:
            key = ("via", via.group(1))
            if float(via.group(2)) <= 0:
                raise AsicPhysicalError("A03 RC via resistance must be positive")
        elif wire:
            key = ("wire", wire.group(1))
        else:
            raise AsicPhysicalError("A03 RC definition contains non-allowlisted Tcl")
        if key in keys:
            raise AsicPhysicalError("A03 RC definition contains duplicate targets")
        keys.add(key)
        commands.append(line)
    if not commands or len(commands) > 64:
        raise AsicPhysicalError("A03 RC definition must contain 1 to 64 commands")
    return tuple(commands)


def validate_approval(
    value: Any,
    contract: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    input_evidence: Mapping[str, Any],
    a02_evidence: Mapping[str, Any],
    physical_config: Mapping[str, Any],
    *,
    now: datetime,
) -> None:
    approval = _fields(value, APPROVAL_FIELDS, "A03 approval")
    if approval["schema_version"] != SCHEMA_VERSION or approval["status"] != "APPROVED":
        raise AsicPhysicalError("A03 approval status or schema_version is invalid")
    if approval["scope"] != [
        "floorplan",
        "place",
        "cts",
        "route",
        "drc",
        "export_gds",
        "lvs",
    ]:
        raise AsicPhysicalError("A03 approval scope is invalid")
    try:
        input_contract._reviewer(approval["approved_by"], "A03 approver")
        approved_at = synth_sta._parse_time(approval["approved_at"], "A03 approved_at")
        expires_at = synth_sta._parse_time(approval["expires_at"], "A03 expires_at")
    except (input_contract.AsicInputError, synth_sta.AsicSynthStaError) as exc:
        raise AsicPhysicalError(str(exc)) from exc
    current = now.astimezone(timezone.utc)
    if approved_at > current or expires_at <= current or expires_at <= approved_at:
        raise AsicPhysicalError("A03 approval is not currently valid")
    expected = {
        "backend_contract_id": contract["contract_id"],
        "capability_id": capabilities["capability_id"],
        "input_evidence_id": input_evidence["evidence_id"],
        "a02_evidence_id": a02_evidence["evidence_id"],
        "physical_config_sha256": config_sha256(physical_config),
    }
    if any(approval[field] != item for field, item in expected.items()):
        raise AsicPhysicalError("A03 approval does not bind the exact evidence set")


def _verify_a02_artifacts(run_root: Path, evidence: Mapping[str, Any]) -> Path:
    names = {
        "abc_constraints": "abc.constr",
        "netlist": "netlist.v",
        "openroad_stderr": "openroad.stderr.log",
        "openroad_stdout": "openroad.stdout.log",
        "sta_script": "sta.tcl",
        "synthesis_script": "synth.ys",
        "synthesis_stat": "synthesis-stat.json",
        "yosys_stderr": "yosys.stderr.log",
        "yosys_stdout": "yosys.stdout.log",
    }
    stored = {item["role"]: item for item in evidence["artifacts"]}
    if set(stored) != set(names):
        raise AsicPhysicalError("A02 artifact set is incomplete")
    for role, name in names.items():
        try:
            actual = synth_sta._artifact(run_root / name, run_root, f"A02 {role}")
        except synth_sta.AsicSynthStaError as exc:
            raise AsicPhysicalError(str(exc)) from exc
        if actual != {"sha256": stored[role]["sha256"], "bytes": stored[role]["bytes"]}:
            raise AsicPhysicalError(f"A02 artifact drift: {role}")
    return run_root / names["netlist"]


def _result_status(timing_met: bool, drc_clean: bool) -> str:
    if timing_met and drc_clean:
        return "PASS"
    if not timing_met and not drc_clean:
        return "TIMING_AND_DRC_VIOLATION"
    return "TIMING_VIOLATION" if not timing_met else "DRC_VIOLATION"


def run_physical(
    physical_config: Mapping[str, Any],
    asic_manifest: Mapping[str, Any],
    policy: Mapping[str, Any],
    contract: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    input_evidence: Mapping[str, Any],
    a02_evidence: Mapping[str, Any],
    a02_approval: Mapping[str, Any],
    approval: Mapping[str, Any],
    *,
    repository_root: Path,
    pdk_root: Path,
    design_root: Path,
    a02_run_directory: Path,
    run_directory: Path,
    runner: Runner = subprocess.run,
    resolver: Resolver = shutil.which,
    now: datetime | None = None,
) -> dict[str, Any]:
    backend.validate_policy(policy)
    backend.validate_contract(contract, policy)
    backend.validate_capabilities(capabilities, policy)
    input_contract.validate_evidence(input_evidence, policy, contract)
    synth_sta.validate_evidence(
        a02_evidence, policy, contract, capabilities, input_evidence, a02_approval
    )
    if capabilities["status"] != "CAPABILITIES_PRESENT_UNQUALIFIED":
        raise AsicPhysicalError("A03 requires present OpenROAD capability")
    validate_config(physical_config)
    execution_time = datetime.now(timezone.utc) if now is None else now
    if execution_time.tzinfo is None:
        raise AsicPhysicalError("A03 execution time must be timezone-aware")
    execution_time = execution_time.astimezone(timezone.utc).replace(microsecond=0)
    validate_approval(
        approval,
        contract,
        capabilities,
        input_evidence,
        a02_evidence,
        physical_config,
        now=execution_time,
    )
    try:
        repository_root, pdk_root, design_root, a02_run_directory = synth_sta._disjoint_roots(
            (repository_root, "repository"),
            (pdk_root, "PDK"),
            (design_root, "design"),
            (a02_run_directory, "A02 run"),
        )
        rebuilt = input_contract.build_evidence(
            asic_manifest,
            policy,
            contract,
            repository_root=repository_root,
            pdk_root=pdk_root,
            design_root=design_root,
        )
    except (input_contract.AsicInputError, synth_sta.AsicSynthStaError) as exc:
        raise AsicPhysicalError(str(exc)) from exc
    if rebuilt != input_evidence:
        raise AsicPhysicalError("A03 external inputs drift from A01 evidence")
    netlist = _verify_a02_artifacts(a02_run_directory, a02_evidence)
    paths = synth_sta._resolve_manifest_paths(asic_manifest, pdk_root, design_root)
    track_commands = _track_commands(paths["views"]["tracks"])
    rc_commands = _rc_commands(paths["rc_tech"])
    physical_rule_commands = _physical_rule_commands(
        paths["views"]["physical_rules"]
    )
    capability_by_name = {item["name"]: item for item in capabilities["tools"]}
    openroad_capability = capability_by_name["openroad"]
    strmrun_capability = capability_by_name["strmrun"]
    try:
        openroad = synth_sta._safe_tool("openroad", openroad_capability, resolver)
        strmrun = synth_sta._safe_tool("strmrun", strmrun_capability, resolver)
    except synth_sta.AsicSynthStaError as exc:
        raise AsicPhysicalError(str(exc)) from exc

    if not run_directory.is_absolute() or run_directory.exists():
        raise AsicPhysicalError("A03 run directory must be an absent absolute path")
    run_parent = input_contract._root(run_directory.parent, "A03 run parent")
    for other in (repository_root, pdk_root, design_root, a02_run_directory):
        try:
            input_contract._require_disjoint(run_parent, other, "A03 run")
        except input_contract.AsicInputError as exc:
            raise AsicPhysicalError(str(exc)) from exc
    run_directory.mkdir()
    run_directory = run_directory.resolve(strict=True)

    floorplan = physical_config["floorplan"]
    placement = physical_config["placement"]
    optimization = physical_config["optimization"]
    routing = physical_config["routing"]
    die = " ".join(str(float(item)) for item in floorplan["die_area_um"])
    core = " ".join(str(float(item)) for item in floorplan["core_area_um"])
    fillers = " ".join(placement["filler_cells"])
    design = asic_manifest["design"]
    global_placement = [
        "global_placement",
        "-density",
        _number_text(optimization["placement_density"]),
    ]
    if optimization["routability_driven_placement"]:
        global_placement.append("-routability_driven")
    if optimization["timing_driven_placement"]:
        global_placement.append("-timing_driven")
    if optimization["force_center_initial_place"]:
        global_placement.append("-force_center_initial_place")
    global_placement.extend(
        [
            "-min_phi_coef",
            _number_text(optimization["min_phi_coefficient"]),
            "-max_phi_coef",
            _number_text(optimization["max_phi_coefficient"]),
        ]
    )
    footprint = " -match_cell_footprint" if optimization["match_cell_footprint"] else ""
    repair_design = f"repair_design -slew_margin 20 -cap_margin 20{footprint} -verbose"
    repair_setup = f"repair_timing -setup -repair_tns 100{footprint} -verbose"
    repair_hold = f"repair_timing -hold{footprint} -verbose"
    cts = ["clock_tree_synthesis"]
    if optimization["cts_sink_clustering"]:
        cts.append("-sink_clustering_enable")
    if optimization["cts_repair_clock_nets"]:
        cts.append("-repair_clock_nets")
    post_global_route = []
    if optimization["post_global_route_repair"]:
        post_global_route = [
            "estimate_parasitics -global_routing",
            repair_design,
            "global_route -start_incremental",
            "detailed_placement",
            "global_route -end_incremental",
            "estimate_parasitics -global_routing",
            repair_setup,
            repair_hold,
            "global_route -start_incremental",
            "detailed_placement",
            "global_route -end_incremental",
            "estimate_parasitics -global_routing",
        ]
    script = "\n".join(
        [
            "set_cmd_units -time ns -distance um",
            f"read_liberty {synth_sta._quoted(paths['liberty'])}",
            f"read_lef {synth_sta._quoted(paths['views']['tech_lef'])}",
            f"read_lef {synth_sta._quoted(paths['views']['cell_lef'])}",
            f"read_verilog {synth_sta._quoted(netlist)}",
            f"link_design {design['top_module']}",
            f"read_sdc {synth_sta._quoted(paths['views']['sdc'])}",
            f"read_sdc {synth_sta._quoted(paths['constraints'])}",
            f"initialize_floorplan -die_area {{{die}}} -core_area {{{core}}} -site {floorplan['site']}",
            *track_commands,
            *rc_commands,
            *physical_rule_commands,
            f"place_pins -hor_layers {placement['pin_horizontal_layer']} -ver_layers {placement['pin_vertical_layer']}",
            f"set_wire_rc -signal -layer {routing['signal_wire_rc_layer']}",
            f"set_wire_rc -clock -layer {routing['clock_wire_rc_layer']}",
            " ".join(global_placement),
            "estimate_parasitics -placement",
            repair_design,
            "detailed_placement",
            "estimate_parasitics -placement",
            repair_setup,
            "detailed_placement",
            " ".join(cts),
            "set_propagated_clock [all_clocks]",
            "estimate_parasitics -placement",
            repair_setup,
            repair_hold,
            "detailed_placement",
            (
                "set_global_routing_layer_adjustment "
                f"{routing['signal_layers']} {routing['global_layer_adjustment']}"
            ),
            f"set_routing_layers -signal {routing['signal_layers']} -clock {routing['clock_layers']}",
            (
                "pin_access "
                f"-via_in_pin_bottom_layer {routing['via_in_pin_layer']} "
                f"-via_in_pin_top_layer {routing['via_in_pin_layer']}"
            ),
            "global_route",
            *post_global_route,
            (
                "detailed_route "
                f"-droute_end_iter {routing['detailed_route_end_iteration']} "
                f"-via_in_pin_bottom_layer {routing['via_in_pin_layer']} "
                f"-via_in_pin_top_layer {routing['via_in_pin_layer']} "
                f"-or_seed {routing['detailed_route_seed']} "
                f"-or_k {routing['detailed_route_k']} "
                "-drc_report_iter_step 5 -verbose 1"
            ),
            f"filler_placement {{{fillers}}}",
            "global_connect",
            (
                "extract_parasitics -ext_model_file "
                f"{synth_sta._quoted(paths['views']['rcx_rules'])}"
            ),
            "set vibesilicon_drc_count [detailed_route_num_drvs]",
            'set vibesilicon_drc_stream [open "drc.rpt" "w"]',
            'puts $vibesilicon_drc_stream "DRC violations: $vibesilicon_drc_count"',
            "close $vibesilicon_drc_stream",
            'puts "VIBESILICON_DRC_COUNT=$vibesilicon_drc_count"',
            "report_checks -path_delay max -group_count 20",
            "report_worst_slack -max",
            "report_tns",
            "report_design_area",
            'write_def "final.def"',
            (
                "write_cdl -masters "
                f"{synth_sta._quoted(paths['views']['spice'])} \"final.cdl\""
            ),
            'write_verilog "postroute.v"',
            'write_spef "final.spef"',
            "exit",
            "",
        ]
    )
    synth_sta._write_new(run_directory / "physical.tcl", script)
    synth_sta._write_new(run_directory / "gds_export.py", KLAYOUT_EXPORT_SCRIPT)
    openroad_command = [str(openroad), "-no_init", "-exit", "physical.tcl"]
    try:
        openroad_completed = runner(
            openroad_command,
            cwd=str(run_directory),
            text=True,
            capture_output=True,
            shell=False,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AsicPhysicalError("A03 OpenROAD execution failed to start") from exc
    synth_sta._write_new(
        run_directory / "openroad.stdout.log", openroad_completed.stdout or "\n"
    )
    synth_sta._write_new(
        run_directory / "openroad.stderr.log", openroad_completed.stderr or "\n"
    )
    if openroad_completed.returncode != 0:
        raise AsicPhysicalError(
            "A03 OpenROAD failed with exit code "
            f"{openroad_completed.returncode}; run directory retained"
        )
    _write_lvs_reference(
        run_directory / "lvs_reference.cdl",
        run_directory / "final.cdl",
        paths["views"]["spice"],
    )
    klayout_command = [
        str(strmrun),
        "-v",
        f"tech_file={paths['views']['klayout_tech']}",
        "-v",
        f"tech_lef={paths['views']['tech_lef']}",
        "-v",
        f"cell_lef={paths['views']['cell_lef']}",
        "-v",
        "in_def=final.def",
        "-v",
        f"design_name={design['top_module']}",
        "-v",
        f"in_gds={paths['views']['gds']}",
        "-v",
        "out_file=final.gds",
        "gds_export.py",
    ]
    try:
        klayout_completed = runner(
            klayout_command,
            cwd=str(run_directory),
            text=True,
            capture_output=True,
            shell=False,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AsicPhysicalError("A03 KLayout execution failed to start") from exc
    synth_sta._write_new(
        run_directory / "klayout.stdout.log", klayout_completed.stdout or "\n"
    )
    synth_sta._write_new(
        run_directory / "klayout.stderr.log", klayout_completed.stderr or "\n"
    )
    if klayout_completed.returncode != 0:
        raise AsicPhysicalError(
            "A03 KLayout failed with exit code "
            f"{klayout_completed.returncode}; run directory retained"
        )
    drc_command = [
        str(strmrun),
        "-v",
        "in_gds=final.gds",
        "-v",
        "report_file=signoff-drc.lyrdb",
        str(paths["views"]["drc_rules"]),
    ]
    try:
        drc_completed = runner(
            drc_command,
            cwd=str(run_directory),
            text=True,
            capture_output=True,
            shell=False,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AsicPhysicalError("A03 signoff DRC execution failed to start") from exc
    synth_sta._write_new(
        run_directory / "drc.stdout.log", drc_completed.stdout or "\n"
    )
    synth_sta._write_new(
        run_directory / "drc.stderr.log", drc_completed.stderr or "\n"
    )
    if drc_completed.returncode != 0:
        raise AsicPhysicalError(
            "A03 signoff DRC failed with exit code "
            f"{drc_completed.returncode}; run directory retained"
        )
    drc_count, drc_rule_counts = _signoff_drc_summary(
        run_directory / "signoff-drc.lyrdb"
    )
    lvs_command = [
        str(strmrun),
        "-v",
        "in_gds=final.gds",
        "-v",
        "report_file=lvs.lvsdb",
        "-v",
        "cdl_file=lvs_reference.cdl",
        "-v",
        "target_netlist=lvs-extracted.cdl",
        "-v",
        f"top_cell={design['top_module']}",
        str(paths["views"]["lvs_rules"]),
    ]
    try:
        lvs_completed = runner(
            lvs_command,
            cwd=str(run_directory),
            text=True,
            capture_output=True,
            shell=False,
            timeout=3600,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AsicPhysicalError("A03 LVS execution failed to start") from exc
    synth_sta._write_new(
        run_directory / "lvs.stdout.log", lvs_completed.stdout or "\n"
    )
    synth_sta._write_new(
        run_directory / "lvs.stderr.log", lvs_completed.stderr or "\n"
    )
    if lvs_completed.returncode != 0:
        raise AsicPhysicalError(
            "A03 LVS failed with exit code "
            f"{lvs_completed.returncode}; run directory retained"
        )
    try:
        localization = signoff_localization.build_localization(
            run_directory / "signoff-drc.lyrdb",
            run_directory / "lvs.lvsdb",
            run_directory / "final.def",
        )
        signoff_localization.write_localization(
            localization, run_directory / "signoff-localization.json"
        )
    except signoff_localization.SignoffLocalizationError as exc:
        raise AsicPhysicalError(
            f"A03 signoff localization failed for drc_report/lvs_report/def: {exc}"
        ) from exc
    stdout = openroad_completed.stdout or ""
    try:
        wns = synth_sta._match_metric(synth_sta.WNS_RE, stdout, "WNS")
        tns = synth_sta._match_metric(synth_sta.TNS_RE, stdout, "TNS")
        area = synth_sta._match_metric(synth_sta.AREA_RE, stdout, "area")
    except synth_sta.AsicSynthStaError as exc:
        raise AsicPhysicalError(str(exc)) from exc
    if tns > 0:
        raise AsicPhysicalError("A03 TNS must be zero or negative")
    drc_matches = DRC_RE.findall(stdout)
    if len(drc_matches) != 1:
        raise AsicPhysicalError("A03 DRC count must appear exactly once")
    route_drc_count = int(drc_matches[0])
    if route_drc_count < 0:  # pragma: no cover - regex only accepts digits
        raise AsicPhysicalError("A03 route DRC count is invalid")
    timing_met = wns >= 0 and tns == 0
    drc_clean = drc_count == 0
    files = {
        "cdl": "final.cdl",
        "drc_report": "signoff-drc.lyrdb",
        "drc_stderr": "drc.stderr.log",
        "drc_stdout": "drc.stdout.log",
        "route_drc_report": "drc.rpt",
        "lvs_extracted": "lvs-extracted.cdl",
        "lvs_reference": "lvs_reference.cdl",
        "lvs_report": "lvs.lvsdb",
        "signoff_localization": "signoff-localization.json",
        "lvs_stderr": "lvs.stderr.log",
        "lvs_stdout": "lvs.stdout.log",
        "def": "final.def",
        "gds": "final.gds",
        "gds_export_script": "gds_export.py",
        "klayout_stderr": "klayout.stderr.log",
        "klayout_stdout": "klayout.stdout.log",
        "openroad_stderr": "openroad.stderr.log",
        "openroad_stdout": "openroad.stdout.log",
        "physical_script": "physical.tcl",
        "postroute_netlist": "postroute.v",
        "spef": "final.spef",
    }
    try:
        artifacts = [
            {
                "role": role,
                **synth_sta._artifact(
                    run_directory / files[role], run_directory, f"A03 {role}"
                ),
            }
            for role in RUN_ARTIFACT_ROLES
        ]
    except synth_sta.AsicSynthStaError as exc:
        raise AsicPhysicalError(str(exc)) from exc
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "evidence_id": "",
        "policy_id": policy["policy_id"],
        "backend_id": policy["backend_id"],
        "backend_contract_id": contract["contract_id"],
        "capability_id": capabilities["capability_id"],
        "input_evidence_id": input_evidence["evidence_id"],
        "a02_evidence_id": a02_evidence["evidence_id"],
        "approval_sha256": "sha256:" + hashlib.sha256(_canonical_bytes(approval)).hexdigest(),
        "physical_config_sha256": config_sha256(physical_config),
        "executed_at": execution_time.isoformat().replace("+00:00", "Z"),
        "status": RUN_STATUS,
        "result_status": _result_status(timing_met, drc_clean),
        "tools": [
            {
                "name": name,
                "version": capability_by_name[name]["version"],
                "binary_sha256": capability_by_name[name]["binary_sha256"],
            }
            for name in ("openroad", "strmrun")
        ],
        "commands": [
            "floorplan",
            "place",
            "cts",
            "route",
            "drc",
            "export_gds",
            "lvs",
        ],
        "metrics": {
            "standard_cell_area_um2": area,
            "wns_ns": wns,
            "tns_ns": tns,
            "timing_met": timing_met,
            "drc_count": drc_count,
            "drc_rule_counts": drc_rule_counts,
            "drc_clean": drc_clean,
        },
        "artifacts": artifacts,
        "execution_mode": "LOCAL_ALLOWLIST_ONLY",
        "execution_authorized": True,
        "network_access": False,
        "raw_paths_exposed": False,
        "source_copied_into_repository": False,
        "asic_metrics_mixed_with_fpga": False,
        "next_gate": "A03_LVS_FINALIZATION",
        "closure_status": "A03_PHYSICAL_ENGINEERING_COMPLETE",
    }
    result["evidence_id"] = _content_id(result, "evidence_id")
    validate_run_evidence(
        result,
        policy,
        contract,
        capabilities,
        input_evidence,
        a02_evidence,
        a02_approval,
        approval,
        physical_config,
    )
    return result


def validate_run_evidence(
    value: Any,
    policy: Mapping[str, Any],
    contract: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    input_evidence: Mapping[str, Any],
    a02_evidence: Mapping[str, Any],
    a02_approval: Mapping[str, Any],
    physical_approval: Mapping[str, Any],
    physical_config: Mapping[str, Any],
) -> None:
    result = _fields(value, RUN_FIELDS, "A03 run evidence")
    backend.validate_policy(policy)
    backend.validate_contract(contract, policy)
    backend.validate_capabilities(capabilities, policy)
    input_contract.validate_evidence(input_evidence, policy, contract)
    synth_sta.validate_evidence(
        a02_evidence,
        policy,
        contract,
        capabilities,
        input_evidence,
        a02_approval,
    )
    if result["schema_version"] != SCHEMA_VERSION:
        raise AsicPhysicalError("A03 run schema_version is invalid")
    if result["evidence_id"] != _content_id(result, "evidence_id"):
        raise AsicPhysicalError("A03 run evidence content ID mismatch")
    executed_at = synth_sta._parse_time(result["executed_at"], "A03 executed_at")
    validate_approval(
        physical_approval,
        contract,
        capabilities,
        input_evidence,
        a02_evidence,
        physical_config,
        now=executed_at,
    )
    fixed = {
        "policy_id": policy["policy_id"],
        "backend_id": policy["backend_id"],
        "backend_contract_id": contract["contract_id"],
        "capability_id": capabilities["capability_id"],
        "input_evidence_id": input_evidence["evidence_id"],
        "a02_evidence_id": a02_evidence["evidence_id"],
        "approval_sha256": "sha256:"
        + hashlib.sha256(_canonical_bytes(physical_approval)).hexdigest(),
        "physical_config_sha256": config_sha256(physical_config),
        "status": RUN_STATUS,
        "commands": [
            "floorplan",
            "place",
            "cts",
            "route",
            "drc",
            "export_gds",
            "lvs",
        ],
        "execution_mode": "LOCAL_ALLOWLIST_ONLY",
        "execution_authorized": True,
        "network_access": False,
        "raw_paths_exposed": False,
        "source_copied_into_repository": False,
        "asic_metrics_mixed_with_fpga": False,
        "next_gate": "A03_LVS_FINALIZATION",
        "closure_status": "A03_PHYSICAL_ENGINEERING_COMPLETE",
    }
    if any(result[field] != item for field, item in fixed.items()):
        raise AsicPhysicalError("A03 run evidence violates reviewed semantics")
    if not isinstance(result["tools"], list) or len(result["tools"]) != 2:
        raise AsicPhysicalError("A03 tool evidence is incomplete")
    expected_by_name = {item["name"]: item for item in capabilities["tools"]}
    for tool, name in zip(result["tools"], ("openroad", "strmrun")):
        tool = _fields(tool, {"name", "version", "binary_sha256"}, "A03 tool")
        expected_tool = expected_by_name[name]
        if (
            tool["name"] != name
            or tool["version"] != expected_tool["version"]
            or tool["binary_sha256"] != expected_tool["binary_sha256"]
            or expected_tool["status"] != "PASS"
        ):
            raise AsicPhysicalError("A03 tool evidence does not match capabilities")
    metrics = _fields(result["metrics"], RUN_METRIC_FIELDS, "A03 metrics")
    area = synth_sta._number(metrics["standard_cell_area_um2"], "A03 area", nonnegative=True)
    wns = synth_sta._number(metrics["wns_ns"], "A03 WNS")
    tns = synth_sta._number(metrics["tns_ns"], "A03 TNS")
    if tns > 0:
        raise AsicPhysicalError("A03 TNS must be zero or negative")
    if (
        isinstance(metrics["drc_count"], bool)
        or not isinstance(metrics["drc_count"], int)
        or metrics["drc_count"] < 0
    ):
        raise AsicPhysicalError("A03 DRC count is invalid")
    rule_counts = metrics["drc_rule_counts"]
    if not isinstance(rule_counts, list) or len(rule_counts) > 4096:
        raise AsicPhysicalError("A03 DRC rule counts are invalid")
    previous_rule = None
    total = 0
    for item in rule_counts:
        entry = _fields(item, {"rule", "count"}, "A03 DRC rule count")
        rule = entry["rule"]
        count = entry["count"]
        if (
            not isinstance(rule, str)
            or not rule
            or len(rule) > 128
            or any(ord(character) < 32 for character in rule)
            or (previous_rule is not None and rule <= previous_rule)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
        ):
            raise AsicPhysicalError("A03 DRC rule count is invalid")
        previous_rule = rule
        total += count
    if total != metrics["drc_count"]:
        raise AsicPhysicalError("A03 DRC rule counts do not sum to the total")
    timing_met = wns >= 0 and tns == 0
    drc_clean = metrics["drc_count"] == 0
    if metrics["timing_met"] is not timing_met or metrics["drc_clean"] is not drc_clean:
        raise AsicPhysicalError("A03 derived metric status is inconsistent")
    if result["result_status"] != _result_status(timing_met, drc_clean):
        raise AsicPhysicalError("A03 result_status is inconsistent")
    if not math.isfinite(area):
        raise AsicPhysicalError("A03 area is invalid")
    if not isinstance(result["artifacts"], list) or len(result["artifacts"]) != len(RUN_ARTIFACT_ROLES):
        raise AsicPhysicalError("A03 run artifacts are incomplete")
    roles = []
    for item in result["artifacts"]:
        artifact = _fields(item, {"role", "sha256", "bytes"}, "A03 run artifact")
        roles.append(artifact["role"])
        if not HASH_RE.fullmatch(str(artifact["sha256"])):
            raise AsicPhysicalError("A03 run artifact hash is invalid")
        if isinstance(artifact["bytes"], bool) or not isinstance(artifact["bytes"], int) or artifact["bytes"] <= 0:
            raise AsicPhysicalError("A03 run artifact size is invalid")
    if roles != list(RUN_ARTIFACT_ROLES):
        raise AsicPhysicalError("A03 run artifacts must be ordered and complete")


def validate_lvs_receipt(
    value: Any,
    physical_evidence: Mapping[str, Any],
    input_evidence: Mapping[str, Any],
    run_directory: Path,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    receipt = _fields(value, LVS_FIELDS, "A03 LVS receipt")
    if receipt["schema_version"] != SCHEMA_VERSION:
        raise AsicPhysicalError("A03 LVS receipt schema_version is invalid")
    if receipt["receipt_id"] != _content_id(receipt, "receipt_id"):
        raise AsicPhysicalError("A03 LVS receipt content ID mismatch")
    if receipt["status"] not in {"PASS", "FAIL"}:
        raise AsicPhysicalError("A03 LVS status is invalid")
    _identifier(receipt["checker_id"], "A03 LVS checker")
    if receipt["checker_id"] != "klayout":
        raise AsicPhysicalError("A03 LVS checker must match the fixed backend")
    if not isinstance(receipt["checker_version"], str) or not VERSION_RE.fullmatch(receipt["checker_version"]):
        raise AsicPhysicalError("A03 LVS checker version is invalid")
    try:
        input_contract._reviewer(receipt["reviewed_by"], "A03 LVS reviewer")
        checked_at = synth_sta._parse_time(receipt["checked_at"], "A03 LVS checked_at")
        executed_at = synth_sta._parse_time(physical_evidence["executed_at"], "A03 executed_at")
    except (input_contract.AsicInputError, synth_sta.AsicSynthStaError) as exc:
        raise AsicPhysicalError(str(exc)) from exc
    if now is not None and now.tzinfo is None:
        raise AsicPhysicalError("A03 LVS verification time must be timezone-aware")
    current = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    if checked_at < executed_at or checked_at > current:
        raise AsicPhysicalError("A03 LVS checked_at is outside the valid window")
    physical_artifacts = {item["role"]: item for item in physical_evidence["artifacts"]}
    expected = {
        "pdk_input_evidence_id": input_evidence["evidence_id"],
        "gds_sha256": physical_artifacts["gds"]["sha256"],
        "reference_netlist_sha256": physical_artifacts["lvs_reference"]["sha256"],
        "lvs_rules_sha256": {
            item["role"]: item for item in input_evidence["pdk"]["views"]
        }["lvs_rules"]["sha256"],
        "top_cell": input_evidence["design"]["top_module"],
    }
    if any(receipt[field] != item for field, item in expected.items()):
        raise AsicPhysicalError("A03 LVS receipt does not bind physical artifacts")
    counts = (
        "layout_instance_count",
        "schematic_instance_count",
        "mismatched_nets",
        "mismatched_devices",
        "report_bytes",
    )
    if any(
        isinstance(receipt[field], bool)
        or not isinstance(receipt[field], int)
        or receipt[field] < 0
        for field in counts
    ) or receipt["report_bytes"] == 0:
        raise AsicPhysicalError("A03 LVS counts or report size are invalid")
    lvs_passed = (
        receipt["layout_instance_count"] == receipt["schematic_instance_count"]
        and receipt["mismatched_nets"] == 0
        and receipt["mismatched_devices"] == 0
    )
    if receipt["status"] != ("PASS" if lvs_passed else "FAIL"):
        raise AsicPhysicalError("A03 LVS status does not match mismatch counts")
    try:
        _, report = input_contract._artifact(run_directory, receipt["report_path"], "A03 LVS report")
    except input_contract.AsicInputError as exc:
        raise AsicPhysicalError(str(exc)) from exc
    if receipt["report_path"] != "lvs.lvsdb" or report != {
        "sha256": receipt["report_sha256"],
        "bytes": receipt["report_bytes"],
    } or report != {
        "sha256": physical_artifacts["lvs_report"]["sha256"],
        "bytes": physical_artifacts["lvs_report"]["bytes"],
    }:
        raise AsicPhysicalError("A03 LVS report identity mismatch")
    return report


def finalize_manifest(
    physical_evidence: Mapping[str, Any],
    lvs_receipt: Mapping[str, Any],
    policy: Mapping[str, Any],
    contract: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    input_evidence: Mapping[str, Any],
    a02_evidence: Mapping[str, Any],
    a02_approval: Mapping[str, Any],
    physical_approval: Mapping[str, Any],
    physical_config: Mapping[str, Any],
    *,
    run_directory: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    synth_sta.validate_evidence(
        a02_evidence, policy, contract, capabilities, input_evidence, a02_approval
    )
    validate_run_evidence(
        physical_evidence,
        policy,
        contract,
        capabilities,
        input_evidence,
        a02_evidence,
        a02_approval,
        physical_approval,
        physical_config,
    )
    run_directory = input_contract._root(run_directory, "A03 run")
    stored = {item["role"]: item for item in physical_evidence["artifacts"]}
    names = {
        "cdl": "final.cdl",
        "drc_report": "signoff-drc.lyrdb",
        "drc_stderr": "drc.stderr.log",
        "drc_stdout": "drc.stdout.log",
        "route_drc_report": "drc.rpt",
        "lvs_extracted": "lvs-extracted.cdl",
        "lvs_reference": "lvs_reference.cdl",
        "lvs_report": "lvs.lvsdb",
        "signoff_localization": "signoff-localization.json",
        "lvs_stderr": "lvs.stderr.log",
        "lvs_stdout": "lvs.stdout.log",
        "def": "final.def",
        "gds": "final.gds",
        "gds_export_script": "gds_export.py",
        "klayout_stderr": "klayout.stderr.log",
        "klayout_stdout": "klayout.stdout.log",
        "openroad_stderr": "openroad.stderr.log",
        "openroad_stdout": "openroad.stdout.log",
        "physical_script": "physical.tcl",
        "postroute_netlist": "postroute.v",
        "spef": "final.spef",
    }
    for role, name in names.items():
        try:
            actual = synth_sta._artifact(
                run_directory / name, run_directory, f"A03 {role}"
            )
        except synth_sta.AsicSynthStaError as exc:
            raise AsicPhysicalError(str(exc)) from exc
        if actual != {"sha256": stored[role]["sha256"], "bytes": stored[role]["bytes"]}:
            raise AsicPhysicalError(f"A03 artifact drift: {role}")
    try:
        localization = _load(run_directory / names["signoff_localization"])
        rebuilt_localization = signoff_localization.build_localization(
            run_directory / names["drc_report"],
            run_directory / names["lvs_report"],
            run_directory / names["def"],
        )
        signoff_localization.validate_localization(localization)
    except (AsicPhysicalError, signoff_localization.SignoffLocalizationError) as exc:
        raise AsicPhysicalError(f"A03 signoff localization is invalid: {exc}") from exc
    if localization != rebuilt_localization:
        raise AsicPhysicalError("A03 signoff localization does not match source reports")
    drc_count, drc_rule_counts = _signoff_drc_summary(
        run_directory / names["drc_report"]
    )
    if (
        physical_evidence["metrics"]["drc_count"] != drc_count
        or physical_evidence["metrics"]["drc_rule_counts"] != drc_rule_counts
    ):
        raise AsicPhysicalError("A03 DRC metrics do not match the signoff report")
    lvs_report = validate_lvs_receipt(
        lvs_receipt, physical_evidence, input_evidence, run_directory, now=now
    )
    metrics = dict(physical_evidence["metrics"])
    checks = {
        "timing": "PASS" if metrics["timing_met"] else "FAIL",
        "drc": "PASS" if metrics["drc_clean"] else "FAIL",
        "lvs": lvs_receipt["status"],
        "artifact_completeness": "PASS",
    }
    passed = all(item == "PASS" for item in checks.values())
    artifacts = []
    for role in FINAL_ARTIFACT_ROLES:
        digest = lvs_report if role == "lvs_report" else stored[role]
        artifacts.append({"role": role, "sha256": digest["sha256"], "bytes": digest["bytes"]})
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "manifest_id": "",
        "policy_id": policy["policy_id"],
        "backend_id": policy["backend_id"],
        "input_evidence_id": input_evidence["evidence_id"],
        "a02_evidence_id": a02_evidence["evidence_id"],
        "physical_evidence_id": physical_evidence["evidence_id"],
        "lvs_receipt_id": lvs_receipt["receipt_id"],
        "status": FINAL_STATUS,
        "result_status": "PASS" if passed else "BLOCKED",
        "checks": checks,
        "metrics": metrics,
        "artifacts": artifacts,
        "gds_alone_is_pass": False,
        "additional_execution_authorized": False,
        "raw_paths_exposed": False,
        "asic_metrics_mixed_with_fpga": False,
        "next_gate": "A04_REPRODUCTION_ACCEPTANCE" if passed else "A03_REMEDIATE_AND_RERUN",
        "closure_status": "A03_ENGINEERING_COMPLETE",
    }
    result["manifest_id"] = _content_id(result, "manifest_id")
    validate_final_manifest(result, physical_evidence, lvs_receipt, policy, input_evidence, a02_evidence)
    return result


def validate_final_manifest(
    value: Any,
    physical_evidence: Mapping[str, Any],
    lvs_receipt: Mapping[str, Any],
    policy: Mapping[str, Any],
    input_evidence: Mapping[str, Any],
    a02_evidence: Mapping[str, Any],
) -> None:
    result = _fields(value, FINAL_FIELDS, "A03 RTL-to-GDS manifest")
    if result["schema_version"] != SCHEMA_VERSION:
        raise AsicPhysicalError("A03 final manifest schema_version is invalid")
    if result["manifest_id"] != _content_id(result, "manifest_id"):
        raise AsicPhysicalError("A03 final manifest content ID mismatch")
    fixed = {
        "policy_id": policy["policy_id"],
        "backend_id": policy["backend_id"],
        "input_evidence_id": input_evidence["evidence_id"],
        "a02_evidence_id": a02_evidence["evidence_id"],
        "physical_evidence_id": physical_evidence["evidence_id"],
        "lvs_receipt_id": lvs_receipt["receipt_id"],
        "status": FINAL_STATUS,
        "gds_alone_is_pass": False,
        "additional_execution_authorized": False,
        "raw_paths_exposed": False,
        "asic_metrics_mixed_with_fpga": False,
        "closure_status": "A03_ENGINEERING_COMPLETE",
    }
    if any(result[field] != item for field, item in fixed.items()):
        raise AsicPhysicalError("A03 final manifest violates reviewed semantics")
    checks = _fields(result["checks"], {"timing", "drc", "lvs", "artifact_completeness"}, "A03 checks")
    metrics = _fields(result["metrics"], RUN_METRIC_FIELDS, "A03 final metrics")
    expected_checks = {
        "timing": "PASS" if metrics["timing_met"] else "FAIL",
        "drc": "PASS" if metrics["drc_clean"] else "FAIL",
        "lvs": lvs_receipt["status"],
        "artifact_completeness": "PASS",
    }
    if checks != expected_checks:
        raise AsicPhysicalError("A03 final checks do not match source evidence")
    passed = all(item == "PASS" for item in checks.values())
    if result["result_status"] != ("PASS" if passed else "BLOCKED"):
        raise AsicPhysicalError("A03 final result_status is inconsistent")
    expected_gate = "A04_REPRODUCTION_ACCEPTANCE" if passed else "A03_REMEDIATE_AND_RERUN"
    if result["next_gate"] != expected_gate:
        raise AsicPhysicalError("A03 final next_gate is inconsistent")
    if result["metrics"] != physical_evidence["metrics"]:
        raise AsicPhysicalError("A03 final metrics drift from physical evidence")
    physical_artifacts = {item["role"]: item for item in physical_evidence["artifacts"]}
    expected_artifacts = []
    for role in FINAL_ARTIFACT_ROLES:
        digest = (
            {
                "sha256": lvs_receipt["report_sha256"],
                "bytes": lvs_receipt["report_bytes"],
            }
            if role == "lvs_report"
            else physical_artifacts[role]
        )
        expected_artifacts.append({"role": role, "sha256": digest["sha256"], "bytes": digest["bytes"]})
    if result["artifacts"] != expected_artifacts:
        raise AsicPhysicalError("A03 final artifacts drift from source evidence")


def _repo_path(root: Path, path: Path, *, must_exist: bool) -> Path:
    try:
        return input_contract._repo_path(root, path, must_exist=must_exist)
    except input_contract.AsicInputError as exc:
        raise AsicPhysicalError(str(exc)) from exc


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise AsicPhysicalError(f"refusing to overwrite A03 output: {path}") from exc


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "finalize", "verify-run", "verify-final"))
    parser.add_argument("input", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=Path("config/asic_backend_policy.json"))
    parser.add_argument("--backend-contract", type=Path, required=True)
    parser.add_argument("--capabilities", type=Path, required=True)
    parser.add_argument("--input-evidence", type=Path, required=True)
    parser.add_argument("--a02-evidence", type=Path, required=True)
    parser.add_argument("--a02-approval", type=Path, required=True)
    parser.add_argument("--physical-config", type=Path)
    parser.add_argument("--physical-approval", type=Path)
    parser.add_argument("--asic-manifest", type=Path)
    parser.add_argument("--pdk-root", type=Path)
    parser.add_argument("--design-root", type=Path)
    parser.add_argument("--a02-run-directory", type=Path)
    parser.add_argument("--physical-run-directory", type=Path)
    parser.add_argument("--physical-evidence", type=Path)
    parser.add_argument("--lvs-receipt", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--authorize-local-execution", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        policy = _load(_repo_path(root, args.policy, must_exist=True))
        contract = _load(_repo_path(root, args.backend_contract, must_exist=True))
        capabilities = _load(_repo_path(root, args.capabilities, must_exist=True))
        input_evidence = _load(_repo_path(root, args.input_evidence, must_exist=True))
        a02_evidence = _load(_repo_path(root, args.a02_evidence, must_exist=True))
        a02_approval = _load(_repo_path(root, args.a02_approval, must_exist=True))
        common = (policy, contract, capabilities, input_evidence, a02_evidence, a02_approval)
        if not all(isinstance(item, dict) for item in common):
            raise AsicPhysicalError("A03 bound evidence roots must be objects")
        if args.command == "run":
            required = (
                args.physical_approval,
                args.asic_manifest,
                args.pdk_root,
                args.design_root,
                args.a02_run_directory,
                args.physical_run_directory,
                args.output,
            )
            if not args.authorize_local_execution or any(item is None for item in required):
                raise AsicPhysicalError("A03 run requires explicit authorization and all inputs")
            config = _load(_repo_path(root, args.input, must_exist=True))
            manifest = _load(_repo_path(root, args.asic_manifest, must_exist=True))
            approval = _load(_repo_path(root, args.physical_approval, must_exist=True))
            result = run_physical(
                config,
                manifest,
                *common,
                approval,
                repository_root=root,
                pdk_root=args.pdk_root,
                design_root=args.design_root,
                a02_run_directory=args.a02_run_directory,
                run_directory=args.physical_run_directory,
            )
        elif args.command in {"finalize", "verify-final"}:
            required = (
                args.physical_config,
                args.physical_approval,
                args.physical_run_directory,
                args.lvs_receipt,
            )
            if any(item is None for item in required) or args.authorize_local_execution:
                raise AsicPhysicalError("A03 finalization requires physical evidence inputs only")
            if args.command == "verify-final" and args.physical_evidence is None:
                raise AsicPhysicalError("A03 final verification requires --physical-evidence")
            physical = _load(_repo_path(root, args.input if args.command == "finalize" else args.physical_evidence, must_exist=True))
            config = _load(_repo_path(root, args.physical_config, must_exist=True))
            approval = _load(_repo_path(root, args.physical_approval, must_exist=True))
            receipt = _load(_repo_path(root, args.lvs_receipt, must_exist=True))
            result = finalize_manifest(
                physical,
                receipt,
                *common,
                approval,
                config,
                run_directory=args.physical_run_directory,
            )
            if args.command == "verify-final":
                stored = _load(_repo_path(root, args.input, must_exist=True))
                if stored != result:
                    raise AsicPhysicalError("A03 final manifest does not rebuild exactly")
                result = stored
        else:
            required = (args.physical_config, args.physical_approval)
            if any(item is None for item in required) or args.authorize_local_execution:
                raise AsicPhysicalError("A03 run verification requires config and approval")
            result = _load(_repo_path(root, args.input, must_exist=True))
            config = _load(_repo_path(root, args.physical_config, must_exist=True))
            approval = _load(_repo_path(root, args.physical_approval, must_exist=True))
            validate_run_evidence(result, *common, approval, config)
        if args.command in {"run", "finalize"}:
            if args.output is None:
                raise AsicPhysicalError("A03 output is required")
            _write_json(_repo_path(root, args.output, must_exist=False), result)
    except (
        OSError,
        backend.AsicContractError,
        input_contract.AsicInputError,
        synth_sta.AsicSynthStaError,
        AsicPhysicalError,
    ) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}), file=sys.stderr)
        return 2
    identity = result.get("evidence_id", result.get("manifest_id"))
    print(json.dumps({"status": result["status"], "result_status": result["result_status"], "identity": identity}))
    return 0 if result["result_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
