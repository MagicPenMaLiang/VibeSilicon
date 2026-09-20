#!/usr/bin/env python3
"""Run and verify the allowlisted P4.6 A02 Yosys/OpenROAD adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

try:
    from scripts import asic_backend_contract as backend
    from scripts import asic_input_evidence as inputs
except ImportError:  # pragma: no cover - standalone script execution
    import asic_backend_contract as backend
    import asic_input_evidence as inputs


SCHEMA_VERSION = 1
STATUS = "A02_SYNTH_STA_COMPLETE"
NEXT_GATE = "A03_PHYSICAL_IMPLEMENTATION_ARTIFACTS"
CLOSURE_STATUS = "A02_ENGINEERING_COMPLETE"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
NUMBER = r"(-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
SDC_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
SDC_PERIOD_RE = re.compile(
    rf"(?:^|[ \t])-period[ \t]+(\$[A-Za-z_][A-Za-z0-9_]*|{SDC_NUMBER})"
    r"(?=[ \t]|$)"
)
CELL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,127}$")
WNS_RE = re.compile(
    r"(?m)^[ \t]*worst\s+slack(?:\s+max)?\s+" + NUMBER + r"\b",
    re.IGNORECASE,
)
TNS_RE = re.compile(
    r"(?m)^[ \t]*tns(?:\s+max)?\s+" + NUMBER + r"\b",
    re.IGNORECASE,
)
AREA_RE = re.compile(
    r"(?m)^[ \t]*Design\s+area\s+" + NUMBER + r"\s+u(?:m)?\^?2\b",
    re.IGNORECASE,
)
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
}
EVIDENCE_FIELDS = {
    "schema_version",
    "evidence_id",
    "policy_id",
    "backend_id",
    "backend_contract_id",
    "capability_id",
    "input_evidence_id",
    "approval_sha256",
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
TOOL_FIELDS = {"name", "version", "binary_sha256"}
SYNTHESIS_RULE_FIELDS = {"schema_version", "dont_use_cells", "abc"}
ABC_RULE_FIELDS = {"driver_cell", "load_in_ff"}
METRIC_FIELDS = {
    "cell_count",
    "synth_cell_area_um2",
    "standard_cell_area_um2",
    "wns_ns",
    "tns_ns",
    "timing_met",
}
ARTIFACT_FIELDS = {"role", "sha256", "bytes"}
ARTIFACT_ROLES = (
    "abc_constraints",
    "netlist",
    "openroad_stderr",
    "openroad_stdout",
    "sta_script",
    "synthesis_script",
    "synthesis_stat",
    "yosys_stderr",
    "yosys_stdout",
)
Runner = Callable[..., subprocess.CompletedProcess[str]]
Resolver = Callable[[str], str | None]


class AsicSynthStaError(ValueError):
    """Raised when A02 authorization, execution, or evidence fails closed."""


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


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AsicSynthStaError(f"cannot load A02 JSON: {path}") from exc


def _fields(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise AsicSynthStaError(f"{label} fields are invalid")
    return value


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AsicSynthStaError(f"{label} must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AsicSynthStaError(f"{label} must be an RFC3339 UTC timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise AsicSynthStaError(f"{label} must use UTC")
    return parsed


def validate_approval(
    value: Any,
    contract: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    input_evidence: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    approval = _fields(value, APPROVAL_FIELDS, "A02 approval")
    if approval["schema_version"] != SCHEMA_VERSION or approval["status"] != "APPROVED":
        raise AsicSynthStaError("A02 approval status or schema_version is invalid")
    if approval["scope"] != ["synthesize", "sta"]:
        raise AsicSynthStaError("A02 approval scope must be synthesize then sta")
    try:
        inputs._reviewer(approval["approved_by"], "A02 approver")
    except inputs.AsicInputError as exc:
        raise AsicSynthStaError(str(exc)) from exc
    approved_at = _parse_time(approval["approved_at"], "A02 approved_at")
    expires_at = _parse_time(approval["expires_at"], "A02 expires_at")
    current = datetime.now(timezone.utc) if now is None else now
    if current.tzinfo is None:
        raise AsicSynthStaError("A02 current time must be timezone-aware")
    current = current.astimezone(timezone.utc)
    if approved_at > current or expires_at <= current or expires_at <= approved_at:
        raise AsicSynthStaError("A02 approval is not currently valid")
    expected = {
        "backend_contract_id": contract["contract_id"],
        "capability_id": capabilities["capability_id"],
        "input_evidence_id": input_evidence["evidence_id"],
    }
    if any(approval[field] != item for field, item in expected.items()):
        raise AsicSynthStaError("A02 approval does not bind the exact evidence set")


def _disjoint_roots(*roots: tuple[Path, str]) -> list[Path]:
    resolved = [inputs._root(path, label) for path, label in roots]
    for index, left in enumerate(resolved):
        for right in resolved[index + 1 :]:
            try:
                inputs._require_disjoint(left, right, "A02")
            except inputs.AsicInputError as exc:
                raise AsicSynthStaError(str(exc)) from exc
    return resolved


def _safe_tool(
    name: str,
    capability: Mapping[str, Any],
    resolver: Resolver,
) -> Path:
    executable = resolver(name)
    if not executable:
        raise AsicSynthStaError(f"required ASIC tool is missing: {name}")
    path = Path(executable)
    try:
        if not path.is_file() or inputs._is_reparse(path):
            raise AsicSynthStaError(f"ASIC tool is not a regular file: {name}")
        actual_hash = backend._sha256_file(path)
    except OSError as exc:
        raise AsicSynthStaError(f"cannot identify ASIC tool: {name}") from exc
    if capability["status"] != "PASS" or actual_hash != capability["binary_sha256"]:
        raise AsicSynthStaError(f"ASIC tool identity drift: {name}")
    return path.resolve(strict=True)


def _quoted(path: Path) -> str:
    value = path.resolve(strict=True).as_posix()
    if any(character in value for character in ('"', "\r", "\n")):
        raise AsicSynthStaError("ASIC tool path contains unsupported characters")
    return f'"{value}"'


def _write_new(path: Path, text: str) -> None:
    try:
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    except FileExistsError as exc:
        raise AsicSynthStaError(f"refusing to overwrite A02 run artifact: {path}") from exc


def _artifact(path: Path, root: Path, label: str) -> dict[str, Any]:
    try:
        resolved = path.resolve(strict=True)
        if (
            not inputs._within(resolved, root)
            or not resolved.is_file()
            or inputs._is_reparse(path)
        ):
            raise AsicSynthStaError(f"{label} is not a regular A02 run artifact")
        digest = backend._sha256_file(resolved)
        size = resolved.stat().st_size
    except OSError as exc:
        raise AsicSynthStaError(f"cannot inspect {label}") from exc
    if size <= 0:
        raise AsicSynthStaError(f"{label} is empty")
    return {"sha256": digest, "bytes": size}


def _number(value: Any, label: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AsicSynthStaError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0):
        raise AsicSynthStaError(f"{label} is invalid")
    return result


def _synthesis_rules(path: Path) -> tuple[list[str], str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AsicSynthStaError("PDK synthesis rules are missing or malformed") from exc
    rules = _fields(value, SYNTHESIS_RULE_FIELDS, "PDK synthesis rules")
    if rules["schema_version"] != SCHEMA_VERSION:
        raise AsicSynthStaError("PDK synthesis rules schema_version is invalid")
    dont_use = rules["dont_use_cells"]
    if (
        not isinstance(dont_use, list)
        or not 1 <= len(dont_use) <= 512
        or not all(isinstance(item, str) and CELL_RE.fullmatch(item) for item in dont_use)
        or len(set(dont_use)) != len(dont_use)
    ):
        raise AsicSynthStaError("PDK synthesis dont_use_cells are invalid")
    abc = _fields(rules["abc"], ABC_RULE_FIELDS, "PDK synthesis ABC rules")
    driver_cell = abc["driver_cell"]
    if not isinstance(driver_cell, str) or not CELL_RE.fullmatch(driver_cell):
        raise AsicSynthStaError("PDK synthesis ABC driver_cell is invalid")
    if driver_cell in dont_use:
        raise AsicSynthStaError("PDK synthesis ABC driver_cell cannot be dont-use")
    load = _number(abc["load_in_ff"], "PDK synthesis ABC load_in_ff")
    if not 0.001 <= load <= 1000:
        raise AsicSynthStaError("PDK synthesis ABC load_in_ff is outside the supported range")
    load_text = format(Decimal(str(abc["load_in_ff"])).normalize(), "f")
    return sorted(dont_use), driver_cell, load_text


def _parse_synthesis(path: Path, top: str) -> tuple[int, float]:
    try:
        value = _load(path)
    except AsicSynthStaError as exc:
        raise AsicSynthStaError("Yosys synthesis stat is missing or malformed") from exc
    if not isinstance(value, dict) or not isinstance(value.get("modules"), dict):
        raise AsicSynthStaError("Yosys synthesis stat is malformed")
    module = value["modules"].get(top, value["modules"].get("\\" + top))
    if not isinstance(module, dict):
        raise AsicSynthStaError("Yosys synthesis stat does not contain the top module")
    count_value = module.get("num_cells")
    if isinstance(count_value, dict):
        if not {"count", "area"}.issubset(count_value):
            raise AsicSynthStaError("Yosys hierarchical cell statistics are incomplete")
        try:
            count = int(count_value["count"])
            area_value = float(count_value["area"])
        except (TypeError, ValueError) as exc:
            raise AsicSynthStaError("Yosys hierarchical cell statistics are invalid") from exc
    else:
        count = count_value
        area_value = module.get("area")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise AsicSynthStaError("Yosys cell count is invalid")
    area = _number(area_value, "Yosys cell area", nonnegative=True)
    return count, area


def _match_metric(pattern: re.Pattern[str], text: str, label: str) -> float:
    matches = pattern.findall(text)
    if len(matches) != 1:
        raise AsicSynthStaError(f"OpenROAD {label} must appear exactly once")
    return _number(float(matches[0]), f"OpenROAD {label}", nonnegative=label == "area")


def _abc_delay_target_ps(*sdc_paths: Path) -> str:
    variables: dict[str, Decimal] = {}
    periods: list[Decimal] = []
    for path in sdc_paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise AsicSynthStaError("cannot read approved SDC for ABC timing target") from exc
        if "\x00" in text:
            raise AsicSynthStaError("approved SDC contains unsupported binary data")
        for line in text.splitlines():
            command = line.partition("#")[0].strip()
            if not command:
                continue
            tokens = command.split()
            if tokens[0] == "set" and len(tokens) >= 3:
                name = tokens[1]
                raw = " ".join(tokens[2:])
                if re.fullmatch(SDC_NUMBER, raw):
                    try:
                        variables[name] = Decimal(raw)
                    except InvalidOperation as exc:  # pragma: no cover - regex guarded
                        raise AsicSynthStaError(
                            "approved SDC numeric variable is invalid"
                        ) from exc
                else:
                    variables.pop(name, None)
                continue
            if tokens[0] != "create_clock":
                continue
            match = SDC_PERIOD_RE.search(command)
            if match is None:
                raise AsicSynthStaError(
                    "each approved create_clock must have a literal or numeric-variable period"
                )
            raw = match.group(1)
            if raw.startswith("$"):
                name = raw[1:]
                if name not in variables:
                    raise AsicSynthStaError(
                        "approved create_clock period variable is not a literal number"
                    )
                period = variables[name]
            else:
                try:
                    period = Decimal(raw)
                except InvalidOperation as exc:  # pragma: no cover - guarded by regex
                    raise AsicSynthStaError("approved create_clock period is invalid") from exc
            if not period.is_finite() or period <= 0:
                raise AsicSynthStaError("approved create_clock period must be positive")
            periods.append(period)

    if not periods:
        raise AsicSynthStaError("approved SDC must define at least one create_clock period")
    target = min(periods) * Decimal(1000)
    if target < 1 or target > Decimal("1000000000"):
        raise AsicSynthStaError("ABC delay target is outside the supported range")
    return format(target.normalize(), "f")


def _resolve_manifest_paths(
    manifest: Mapping[str, Any], pdk_root: Path, design_root: Path
) -> dict[str, Any]:
    try:
        pdk = manifest["pdk"]
        corner = pdk["corner"]
        views = {
            item["role"]: inputs._artifact(
                pdk_root, item["path"], f"PDK {item['role']} view"
            )[0]
            for item in pdk["views"]
        }
        sources = [
            inputs._artifact(design_root, item, "RTL source")[0]
            for item in manifest["design"]["sources"]
        ]
        return {
            "liberty": inputs._artifact(
                pdk_root, corner["liberty_path"], "corner Liberty"
            )[0],
            "rc_tech": inputs._artifact(
                pdk_root, corner["rc_tech_path"], "corner RC tech"
            )[0],
            "views": views,
            "sources": sources,
            "constraints": inputs._artifact(
                design_root, manifest["design"]["constraints_path"], "ASIC constraints"
            )[0],
        }
    except (KeyError, TypeError, inputs.AsicInputError) as exc:
        raise AsicSynthStaError("cannot resolve A02 manifest artifacts") from exc


def run_adapter(
    manifest: Any,
    policy: Mapping[str, Any],
    contract: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    input_evidence: Mapping[str, Any],
    approval: Any,
    *,
    repository_root: Path,
    pdk_root: Path,
    design_root: Path,
    run_directory: Path,
    runner: Runner = subprocess.run,
    resolver: Resolver = shutil.which,
    now: datetime | None = None,
) -> dict[str, Any]:
    backend.validate_policy(policy)
    backend.validate_contract(contract, policy)
    backend.validate_capabilities(capabilities, policy)
    inputs.validate_evidence(input_evidence, policy, contract)
    if capabilities["status"] != "CAPABILITIES_PRESENT_UNQUALIFIED":
        raise AsicSynthStaError("A02 requires present Yosys and OpenROAD capabilities")
    execution_time = datetime.now(timezone.utc) if now is None else now
    if execution_time.tzinfo is None:
        raise AsicSynthStaError("A02 execution time must be timezone-aware")
    execution_time = execution_time.astimezone(timezone.utc).replace(microsecond=0)
    validate_approval(
        approval, contract, capabilities, input_evidence, now=execution_time
    )
    repository_root, pdk_root, design_root = _disjoint_roots(
        (repository_root, "repository"),
        (pdk_root, "PDK"),
        (design_root, "design"),
    )
    try:
        rebuilt = inputs.build_evidence(
            manifest,
            policy,
            contract,
            repository_root=repository_root,
            pdk_root=pdk_root,
            design_root=design_root,
        )
    except inputs.AsicInputError as exc:
        raise AsicSynthStaError(str(exc)) from exc
    if rebuilt != input_evidence:
        raise AsicSynthStaError("A02 external inputs drift from approved A01 evidence")
    paths = _resolve_manifest_paths(manifest, pdk_root, design_root)
    abc_delay_target_ps = _abc_delay_target_ps(
        paths["views"]["sdc"], paths["constraints"]
    )
    dont_use_cells, abc_driver_cell, abc_load_in_ff = _synthesis_rules(
        paths["views"]["synthesis_rules"]
    )
    capability_by_name = {item["name"]: item for item in capabilities["tools"]}
    yosys = _safe_tool("yosys", capability_by_name["yosys"], resolver)
    openroad = _safe_tool("openroad", capability_by_name["openroad"], resolver)

    if not run_directory.is_absolute() or run_directory.exists():
        raise AsicSynthStaError("A02 run directory must be an absent absolute path")
    run_parent = inputs._root(run_directory.parent, "A02 run parent")
    for other in (repository_root, pdk_root, design_root):
        try:
            inputs._require_disjoint(run_parent, other, "A02 run")
        except inputs.AsicInputError as exc:
            raise AsicSynthStaError(str(exc)) from exc
    run_directory.mkdir()
    run_directory = run_directory.resolve(strict=True)

    abc_constraints = "\n".join(
        [
            f"set_driving_cell {abc_driver_cell}",
            f"set_load {abc_load_in_ff}",
            "",
        ]
    )
    _write_new(run_directory / "abc.constr", abc_constraints)

    design = manifest["design"]
    read_sources = "\n".join(
        f"read_verilog -sv {_quoted(path)}" for path in paths["sources"]
    )
    synthesis_script = "\n".join(
        [
            read_sources,
            f"hierarchy -check -top {design['top_module']}",
            f"synth -flatten -noabc -top {design['top_module']}",
            f"dfflibmap -liberty {_quoted(paths['liberty'])}",
            " ".join(
                [
                    "abc",
                    "-D",
                    abc_delay_target_ps,
                    "-constr",
                    '"abc.constr"',
                    *(item for cell in dont_use_cells for item in ("-dont_use", cell)),
                    "-liberty",
                    _quoted(paths["liberty"]),
                ]
            ),
            "clean -purge",
            'write_verilog -noattr "netlist.v"',
            (
                f'tee -o "synthesis-stat.json" stat -top {design["top_module"]} '
                f'-hierarchy -liberty {_quoted(paths["liberty"])} -json'
            ),
            "",
        ]
    )
    sta_script = "\n".join(
        [
            "set_cmd_units -time ns -distance um",
            f"read_liberty {_quoted(paths['liberty'])}",
            f"read_lef {_quoted(paths['views']['tech_lef'])}",
            f"read_lef {_quoted(paths['views']['cell_lef'])}",
            'read_verilog "netlist.v"',
            f"link_design {design['top_module']}",
            f"read_sdc {_quoted(paths['views']['sdc'])}",
            f"read_sdc {_quoted(paths['constraints'])}",
            "report_checks -path_delay max -group_count 20",
            "report_worst_slack -max",
            "report_tns",
            "report_design_area",
            "exit",
            "",
        ]
    )
    _write_new(run_directory / "synth.ys", synthesis_script)
    _write_new(run_directory / "sta.tcl", sta_script)

    tool_records = []
    for name in ("yosys", "openroad"):
        item = capability_by_name[name]
        tool_records.append(
            {
                "name": name,
                "version": item["version"],
                "binary_sha256": item["binary_sha256"],
            }
        )
    commands = ([str(yosys), "-q", "-s", "synth.ys"], [str(openroad), "-no_init", "-exit", "sta.tcl"])
    for name, command in zip(("yosys", "openroad"), commands):
        try:
            completed = runner(
                list(command),
                cwd=str(run_directory),
                text=True,
                capture_output=True,
                shell=False,
                timeout=900,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AsicSynthStaError(f"A02 {name} execution failed to start") from exc
        _write_new(run_directory / f"{name}.stdout.log", completed.stdout or "\n")
        _write_new(run_directory / f"{name}.stderr.log", completed.stderr or "\n")
        if completed.returncode != 0:
            raise AsicSynthStaError(
                f"A02 {name} failed with exit code {completed.returncode}; run directory retained"
            )

    synthesis_stat = run_directory / "synthesis-stat.json"
    netlist = run_directory / "netlist.v"
    sta_log = run_directory / "openroad.stdout.log"
    cell_count, synth_area = _parse_synthesis(synthesis_stat, design["top_module"])
    sta_text = sta_log.read_text(encoding="utf-8")
    wns = _match_metric(WNS_RE, sta_text, "WNS")
    tns = _match_metric(TNS_RE, sta_text, "TNS")
    area = _match_metric(AREA_RE, sta_text, "area")
    if tns > 0:
        raise AsicSynthStaError("OpenROAD TNS must be zero or negative")
    if max(synth_area, area) > 0 and abs(synth_area - area) / max(synth_area, area) > 0.05:
        raise AsicSynthStaError("Yosys and OpenROAD standard-cell area differ by more than 5%")
    timing_met = wns >= 0 and tns == 0
    artifact_paths = {
        "abc_constraints": run_directory / "abc.constr",
        "netlist": netlist,
        "openroad_stderr": run_directory / "openroad.stderr.log",
        "openroad_stdout": sta_log,
        "sta_script": run_directory / "sta.tcl",
        "synthesis_script": run_directory / "synth.ys",
        "synthesis_stat": synthesis_stat,
        "yosys_stderr": run_directory / "yosys.stderr.log",
        "yosys_stdout": run_directory / "yosys.stdout.log",
    }
    artifacts = [
        {
            "role": role,
            **_artifact(artifact_paths[role], run_directory, f"A02 {role}"),
        }
        for role in ARTIFACT_ROLES
    ]
    approval_sha256 = "sha256:" + hashlib.sha256(_canonical_bytes(approval)).hexdigest()
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "evidence_id": "",
        "policy_id": policy["policy_id"],
        "backend_id": policy["backend_id"],
        "backend_contract_id": contract["contract_id"],
        "capability_id": capabilities["capability_id"],
        "input_evidence_id": input_evidence["evidence_id"],
        "approval_sha256": approval_sha256,
        "executed_at": execution_time.isoformat().replace("+00:00", "Z"),
        "status": STATUS,
        "result_status": "PASS" if timing_met else "TIMING_VIOLATION",
        "tools": tool_records,
        "commands": ["synthesize", "sta"],
        "metrics": {
            "cell_count": cell_count,
            "synth_cell_area_um2": synth_area,
            "standard_cell_area_um2": area,
            "wns_ns": wns,
            "tns_ns": tns,
            "timing_met": timing_met,
        },
        "artifacts": artifacts,
        "execution_mode": "LOCAL_ALLOWLIST_ONLY",
        "execution_authorized": True,
        "network_access": False,
        "raw_paths_exposed": False,
        "source_copied_into_repository": False,
        "asic_metrics_mixed_with_fpga": False,
        "next_gate": NEXT_GATE,
        "closure_status": CLOSURE_STATUS,
    }
    result["evidence_id"] = _content_id(result, "evidence_id")
    validate_evidence(
        result, policy, contract, capabilities, input_evidence, approval
    )
    return result


def validate_evidence(
    value: Any,
    policy: Mapping[str, Any],
    contract: Mapping[str, Any],
    capabilities: Mapping[str, Any],
    input_evidence: Mapping[str, Any],
    approval: Mapping[str, Any],
) -> None:
    backend.validate_policy(policy)
    backend.validate_contract(contract, policy)
    backend.validate_capabilities(capabilities, policy)
    inputs.validate_evidence(input_evidence, policy, contract)
    result = _fields(value, EVIDENCE_FIELDS, "A02 evidence")
    if result["schema_version"] != SCHEMA_VERSION:
        raise AsicSynthStaError("A02 evidence schema_version is invalid")
    if result["evidence_id"] != _content_id(result, "evidence_id"):
        raise AsicSynthStaError("A02 evidence content ID mismatch")
    fixed = {
        "policy_id": policy["policy_id"],
        "backend_id": policy["backend_id"],
        "backend_contract_id": contract["contract_id"],
        "capability_id": capabilities["capability_id"],
        "input_evidence_id": input_evidence["evidence_id"],
        "status": STATUS,
        "commands": ["synthesize", "sta"],
        "execution_mode": "LOCAL_ALLOWLIST_ONLY",
        "execution_authorized": True,
        "network_access": False,
        "raw_paths_exposed": False,
        "source_copied_into_repository": False,
        "asic_metrics_mixed_with_fpga": False,
        "next_gate": NEXT_GATE,
        "closure_status": CLOSURE_STATUS,
    }
    if any(result[field] != item for field, item in fixed.items()):
        raise AsicSynthStaError("A02 evidence violates reviewed semantics")
    executed_at = _parse_time(result["executed_at"], "A02 executed_at")
    validate_approval(
        approval,
        contract,
        capabilities,
        input_evidence,
        now=executed_at,
    )
    expected_approval = "sha256:" + hashlib.sha256(
        _canonical_bytes(approval)
    ).hexdigest()
    if result["approval_sha256"] != expected_approval:
        raise AsicSynthStaError("A02 approval hash does not match the approval record")
    if not isinstance(result["tools"], list) or len(result["tools"]) != 2:
        raise AsicSynthStaError("A02 tool evidence is incomplete")
    expected_tools = {item["name"]: item for item in capabilities["tools"]}
    for index, name in enumerate(("yosys", "openroad")):
        tool = _fields(result["tools"][index], TOOL_FIELDS, "A02 tool")
        expected = expected_tools[name]
        if (
            tool["name"] != name
            or tool["version"] != expected["version"]
            or tool["binary_sha256"] != expected["binary_sha256"]
            or expected["status"] != "PASS"
        ):
            raise AsicSynthStaError("A02 tool evidence does not match capabilities")
    metrics = _fields(result["metrics"], METRIC_FIELDS, "A02 metrics")
    if (
        isinstance(metrics["cell_count"], bool)
        or not isinstance(metrics["cell_count"], int)
        or metrics["cell_count"] < 0
    ):
        raise AsicSynthStaError("A02 cell_count is invalid")
    synth_area = _number(metrics["synth_cell_area_um2"], "A02 synthesis area", nonnegative=True)
    area = _number(metrics["standard_cell_area_um2"], "A02 area", nonnegative=True)
    wns = _number(metrics["wns_ns"], "A02 WNS")
    tns = _number(metrics["tns_ns"], "A02 TNS")
    if tns > 0:
        raise AsicSynthStaError("A02 TNS must be zero or negative")
    timing_met = wns >= 0 and tns == 0
    if metrics["timing_met"] is not timing_met:
        raise AsicSynthStaError("A02 timing_met does not match WNS/TNS")
    expected_result = "PASS" if timing_met else "TIMING_VIOLATION"
    if result["result_status"] != expected_result:
        raise AsicSynthStaError("A02 result_status does not match timing metrics")
    if max(synth_area, area) > 0 and abs(synth_area - area) / max(synth_area, area) > 0.05:
        raise AsicSynthStaError("A02 area cross-check exceeds 5%")
    if not isinstance(result["artifacts"], list) or len(result["artifacts"]) != len(
        ARTIFACT_ROLES
    ):
        raise AsicSynthStaError("A02 artifact evidence is incomplete")
    roles = []
    for item in result["artifacts"]:
        artifact = _fields(item, ARTIFACT_FIELDS, "A02 artifact")
        roles.append(artifact["role"])
        if not HASH_RE.fullmatch(str(artifact["sha256"])):
            raise AsicSynthStaError("A02 artifact hash is invalid")
        if (
            isinstance(artifact["bytes"], bool)
            or not isinstance(artifact["bytes"], int)
            or artifact["bytes"] <= 0
        ):
            raise AsicSynthStaError("A02 artifact size is invalid")
    if roles != list(ARTIFACT_ROLES):
        raise AsicSynthStaError("A02 artifacts must be ordered and complete")


def _repo_path(root: Path, path: Path, *, must_exist: bool) -> Path:
    try:
        return inputs._repo_path(root, path, must_exist=must_exist)
    except inputs.AsicInputError as exc:
        raise AsicSynthStaError(str(exc)) from exc


def _write_evidence(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise AsicSynthStaError(f"refusing to overwrite A02 evidence: {path}") from exc


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "verify"))
    parser.add_argument("input", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path, default=Path("config/asic_backend_policy.json"))
    parser.add_argument("--backend-contract", type=Path, required=True)
    parser.add_argument("--capabilities", type=Path, required=True)
    parser.add_argument("--input-evidence", type=Path, required=True)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--pdk-root", type=Path)
    parser.add_argument("--design-root", type=Path)
    parser.add_argument("--run-directory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--authorize-local-execution", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        policy = _load(_repo_path(root, args.policy, must_exist=True))
        contract = _load(_repo_path(root, args.backend_contract, must_exist=True))
        capabilities = _load(_repo_path(root, args.capabilities, must_exist=True))
        input_evidence = _load(_repo_path(root, args.input_evidence, must_exist=True))
        if args.approval is None:
            raise AsicSynthStaError("A02 requires an approval record")
        approval = _load(_repo_path(root, args.approval, must_exist=True))
        if not all(
            isinstance(item, dict)
            for item in (policy, contract, capabilities, input_evidence, approval)
        ):
            raise AsicSynthStaError("A02 bound evidence roots must be objects")
        if args.command == "run":
            if (
                not args.authorize_local_execution
                or args.pdk_root is None
                or args.design_root is None
                or args.run_directory is None
                or args.output is None
            ):
                raise AsicSynthStaError("A02 run requires explicit authorization and all run inputs")
            manifest = _load(_repo_path(root, args.input, must_exist=True))
            result = run_adapter(
                manifest,
                policy,
                contract,
                capabilities,
                input_evidence,
                approval,
                repository_root=root,
                pdk_root=args.pdk_root,
                design_root=args.design_root,
                run_directory=args.run_directory,
            )
            _write_evidence(_repo_path(root, args.output, must_exist=False), result)
        else:
            if any(
                item is not None
                for item in (
                    args.pdk_root,
                    args.design_root,
                    args.run_directory,
                    args.output,
                )
            ) or args.authorize_local_execution:
                raise AsicSynthStaError("A02 verify accepts no execution inputs")
            result = _load(_repo_path(root, args.input, must_exist=True))
            validate_evidence(
                result,
                policy,
                contract,
                capabilities,
                input_evidence,
                approval,
            )
    except (
        OSError,
        backend.AsicContractError,
        inputs.AsicInputError,
        AsicSynthStaError,
    ) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": result["status"],
                "result_status": result["result_status"],
                "identity": result["evidence_id"],
            }
        )
    )
    return 0 if result["result_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
