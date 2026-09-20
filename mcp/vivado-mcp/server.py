#!/usr/bin/env python3
"""Root-confined Vivado MCP server with fail-closed command policy."""

import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from scripts.vivado_backend import BackendBlockedError
from scripts.vivado_backend_selector import close_vivado_backend, select_vivado_backend


VIVADO_BIN = os.environ.get("VIVADO_BIN") or shutil.which("vivado") or "vivado"
VIVADO_SETTINGS = os.environ.get("VIVADO_SETTINGS")
PROJECT_ROOT = Path(os.environ.get("VIBESILICON_ROOT", os.getcwd())).resolve()
DEFAULT_PART = os.environ.get("VIBESILICON_FPGA_PART")
MAX_TIMEOUT_SECONDS = 7200
ALLOW_RUN_SCRIPT = os.environ.get("VIBESILICON_ALLOW_RUN_SCRIPT", "0") == "1"
SCRIPT_HASH_ALLOWLIST = {
    item.strip().lower()
    for item in os.environ.get("VIBESILICON_TCL_ALLOWLIST", "").split(",")
    if item.strip()
}

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
PART_RE = re.compile(r"^xc[a-z0-9-]+$", re.IGNORECASE)
RUN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
ALLOWED_STRATEGIES = {
    "Default",
    "Performance_Explore",
    "Performance_ExplorePostRoutePhysOpt",
    "Performance_NetDelay_high",
    "Flow_RuntimeOptimized",
    "Area_Explore",
}

app = Server("vivado")


def _json_text(payload: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


def _error(message: str, **details) -> list[TextContent]:
    return _json_text({"success": False, "error": message, **details})


def _inside_root(path: Path, root: Path | None = None) -> Path:
    root = PROJECT_ROOT if root is None else root
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"路径超出允许的项目根目录：{path}") from exc
    return path


def _resolve_project_path(arg: str) -> Path:
    raw = Path(arg)
    path = (raw if raw.is_absolute() else PROJECT_ROOT / raw).resolve(strict=True)
    _inside_root(path)
    if not path.is_file() or path.suffix.lower() != ".xpr":
        raise ValueError(f"project_path 必须是项目根目录内的 .xpr 文件：{path}")
    return path


def _resolve_project_file(arg: str, suffix: str) -> Path:
    raw = Path(arg)
    path = (raw if raw.is_absolute() else PROJECT_ROOT / raw).resolve(strict=True)
    _inside_root(path)
    if not path.is_file() or path.suffix.lower() != suffix:
        raise ValueError(f"脚本必须是项目根目录内的 {suffix} 文件：{path}")
    return path


def _resolve_output_path(arg: str | None, default: Path, suffix: str) -> Path:
    raw = Path(arg) if arg else default
    path = (raw if raw.is_absolute() else PROJECT_ROOT / raw).resolve(strict=False)
    _inside_root(path)
    if path.suffix.lower() != suffix:
        raise ValueError(f"输出文件必须使用 {suffix} 后缀：{path}")
    return path


def _validate_identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field} 包含非法 Tcl 字符：{value!r}")
    return value


def _validate_run(value: str) -> str:
    if not isinstance(value, str) or not RUN_RE.fullmatch(value):
        raise ValueError(f"run 名称非法：{value!r}")
    return value


def _validate_part(value: str) -> str:
    if not isinstance(value, str) or not PART_RE.fullmatch(value):
        raise ValueError(f"器件 part 名称非法：{value!r}")
    return value


def _validate_strategy(value: str) -> str:
    if value not in ALLOWED_STRATEGIES:
        raise ValueError(f"不允许的实现策略：{value!r}")
    return value


def _validate_bitstream_name(value: str) -> str:
    name = Path(value)
    if name.name != value or name.suffix.lower() != ".bit":
        raise ValueError("bitstream_name 必须是无目录的 .bit 文件名")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.bit", value, re.IGNORECASE):
        raise ValueError(f"bitstream_name 包含非法字符：{value!r}")
    return value


def _tcl_path(path: Path) -> str:
    value = path.as_posix()
    if any(char in value for char in "{}\n\r"):
        raise ValueError(f"路径不能安全表示为 Tcl：{path}")
    return "{" + value + "}"


def _write_tcl(project_path: Path, content: str) -> Path:
    work_dir = project_path.parent / ".vibesilicon" / "vivado"
    work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".tcl", prefix="run_", dir=work_dir, delete=False
    ) as handle:
        handle.write(content)
        return Path(handle.name)


def _selected_backend():
    return select_vivado_backend(
        root=PROJECT_ROOT,
        vivado_bin=VIVADO_BIN,
        settings_path=VIVADO_SETTINGS,
    )


def _run_vivado(
    tcl_path: Path,
    cwd: Path,
    timeout: int = 3600,
    risk_class: str = "R1",
    reports: list[tuple[Path, str]] | None = None,
) -> dict[str, Any]:
    backend = None
    session = None
    try:
        backend = _selected_backend()
        configured_version = os.environ.get("VIVADO_VERSION")
        capabilities = backend.discover_capabilities(probe=configured_version is None)
        session = backend.start_session(
            cwd,
            mode="batch",
            gui=False,
            tool_version=configured_version or capabilities["vivado_version"],
        )
        result = backend.execute_tcl(
            session,
            tcl_path.read_text(encoding="utf-8", errors="strict"),
            risk_class,
            timeout,
        )
        if result["status"] == "PASS" and reports:
            result["report_evidence"] = {
                kind: backend.record_report_evidence(session, result, path, kind)
                for path, kind in reports
            }
        result["tcl_script"] = str(tcl_path)
        return result
    except BackendBlockedError as exc:
        return {
            "success": False,
            "status": "BLOCKED",
            "error": str(exc),
            "tcl_script": str(tcl_path),
        }
    except Exception as exc:
        return {
            "success": False,
            "status": "ERROR",
            "error": str(exc),
            "tcl_script": str(tcl_path),
        }
    finally:
        try:
            if backend is not None and session is not None and session.state == "ACTIVE":
                backend.stop_session(session)
        finally:
            if backend is not None:
                close_vivado_backend(backend)


def _parse_timing_report(content: str) -> dict[str, Any]:
    result: dict[str, Any] = {"wns": None, "tns": None, "whs": None, "failing_endpoints": None}
    patterns = {
        "wns": [r"WNS\s*[:=]\s*([-+\d.]+)", r"WNS\(ns\).*?\n[-\s]+\n\s*([-+\d.]+)"],
        "tns": [r"TNS\s*[:=]\s*([-+\d.]+)"],
        "whs": [r"WHS\s*[:=]\s*([-+\d.]+)"],
    }
    for key, candidates in patterns.items():
        for pattern in candidates:
            match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
            if match:
                result[key] = float(match.group(1))
                break
    match = re.search(r"failing\s+endpoints?\s*[:=]\s*(\d+)", content, re.IGNORECASE)
    if match:
        result["failing_endpoints"] = int(match.group(1))
    return result


def _parse_cdc_report(content: str) -> dict[str, Any]:
    result: dict[str, Any] = {"critical": 0, "major": 0, "minor": 0}
    for severity in result:
        match = re.search(rf"{severity}\s*[:=]\s*(\d+)", content, re.IGNORECASE)
        if match:
            result[severity] = int(match.group(1))
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


@app.list_tools()
async def list_tools() -> list[Tool]:
    tools = [
        Tool(
            name="backend_capabilities",
            description="发现所选 Vivado backend 能力、隐私默认值和实际可用性",
            inputSchema={
                "type": "object",
                "properties": {"probe": {"type": "boolean", "default": False}},
            },
        ),
        Tool(
            name="synth_design",
            description="Vivado 综合：synth_design + 资源报告",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "top": {"type": "string"},
                    "part": {"type": "string"},
                },
                "required": ["project_path", "top", "part"],
            },
        ),
        Tool(
            name="place_route",
            description="Vivado 实现：place + route + 报告",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "top": {"type": "string"},
                    "strategy": {"type": "string", "enum": sorted(ALLOWED_STRATEGIES)},
                },
                "required": ["project_path", "top"],
            },
        ),
        Tool(
            name="report_timing",
            description="Vivado route/synth timing summary",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "run": {"type": "string", "default": "impl_1"},
                    "output_json": {"type": "string"},
                },
                "required": ["project_path"],
            },
        ),
        Tool(
            name="analyze_checkpoint",
            description="只读打开综合后/实现后 DCP，生成时序摘要、关键路径和时钟交互证据",
            inputSchema={
                "type": "object",
                "properties": {
                    "checkpoint_path": {"type": "string"},
                    "max_paths": {
                        "type": "integer",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100,
                    },
                    "output_json": {"type": "string"},
                },
                "required": ["checkpoint_path"],
            },
        ),
        Tool(
            name="report_cdc",
            description="Vivado CDC report",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "run": {"type": "string", "default": "synth_1"},
                    "output_json": {"type": "string"},
                },
                "required": ["project_path"],
            },
        ),
        Tool(
            name="write_bitstream",
            description="Vivado 生成 bitstream",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "bitstream_name": {"type": "string", "default": "design.bit"},
                },
                "required": ["project_path"],
            },
        ),
    ]
    if ALLOW_RUN_SCRIPT:
        tools.append(
            Tool(
                name="run_script",
                description="运行项目内、SHA-256 allowlist 已批准的 Tcl 脚本",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "project_path": {"type": "string"},
                        "script_path": {"type": "string"},
                        "sha256": {"type": "string"},
                        "timeout": {"type": "integer", "default": 3600, "maximum": MAX_TIMEOUT_SECONDS},
                    },
                    "required": ["project_path", "script_path", "sha256"],
                },
            )
        )
    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    allowed = {
        "backend_capabilities",
        "synth_design",
        "place_route",
        "report_timing",
        "analyze_checkpoint",
        "report_cdc",
        "write_bitstream",
    }
    if ALLOW_RUN_SCRIPT:
        allowed.add("run_script")
    if name not in allowed:
        return _error(f"未知或被策略禁用的 tool: {name}")

    try:
        if name == "backend_capabilities":
            backend = _selected_backend()
            try:
                return _json_text(
                    backend.discover_capabilities(bool(arguments.get("probe", False)))
                )
            finally:
                close_vivado_backend(backend)

        if name == "analyze_checkpoint":
            checkpoint = _resolve_project_file(arguments["checkpoint_path"], ".dcp")
            max_paths = arguments.get("max_paths", 10)
            if (
                isinstance(max_paths, bool)
                or not isinstance(max_paths, int)
                or not 1 <= max_paths <= 100
            ):
                raise ValueError("max_paths 必须是 1 到 100 的整数")
            work_dir = checkpoint.parent / ".vibesilicon" / "vivado" / "dcp_analysis"
            work_dir.mkdir(parents=True, exist_ok=True)
            timing_report = work_dir / "timing_summary.rpt"
            paths_report = work_dir / "critical_paths.rpt"
            clocks_report = work_dir / "clock_interaction.rpt"
            output = _resolve_output_path(
                arguments.get("output_json"), work_dir / "dcp_analysis.json", ".json"
            )
            tcl = (
                f"open_checkpoint {_tcl_path(checkpoint)}\n"
                f"report_timing_summary -delay_type min_max -max_paths {max_paths} "
                f"-file {_tcl_path(timing_report)}\n"
                f"report_timing -delay_type max -max_paths {max_paths} "
                f"-path_type full_clock_expanded -file {_tcl_path(paths_report)}\n"
                f"report_clock_interaction -file {_tcl_path(clocks_report)}\nexit\n"
            )
            tcl_path = _write_tcl(checkpoint, tcl)
            result = _run_vivado(
                tcl_path,
                checkpoint.parent,
                risk_class="R0",
                reports=[(timing_report, "timing_report")],
            )
            if "report_evidence" in result:
                raw_artifacts = (timing_report, paths_report, clocks_report)
                missing = [str(path) for path in raw_artifacts if not path.is_file()]
                if missing:
                    return _error("DCP 分析报告不完整", status="ERROR", missing=missing)
                receipt = result["report_evidence"]["timing_report"]
                analysis = {
                    "schema_version": 1,
                    "mode": "read_only_dcp_analysis",
                    "checkpoint": str(checkpoint),
                    "checkpoint_sha256": "sha256:"
                    + hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                    "timing_evidence_id": receipt["evidence_id"],
                    "metrics": receipt["metrics"],
                    "artifacts": {
                        path.stem: {
                            "path": str(path),
                            "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                        for path in raw_artifacts
                    },
                    "mutation_performed": False,
                }
                _write_json(output, analysis)
                result["analysis"] = analysis
                result["output_json"] = str(output)
            return _json_text(result)

        project_path = _resolve_project_path(arguments["project_path"])

        if name == "synth_design":
            top = _validate_identifier(arguments["top"], "top")
            part = _validate_part(arguments.get("part") or DEFAULT_PART)
            util_report = project_path.parent / "synth_util.rpt"
            checkpoint = project_path.parent / "post_synth.dcp"
            tcl = (
                f"open_project {_tcl_path(project_path)}\n"
                f"set_property top {top} [current_fileset]\n"
                f"set_property part {part} [current_project]\n"
                "update_compile_order -fileset sources_1\n"
                f"synth_design -top {top} -part {part}\n"
                f"report_utilization -file {_tcl_path(util_report)}\n"
                f"write_checkpoint -force {_tcl_path(checkpoint)}\nexit\n"
            )
            tcl_path = _write_tcl(project_path, tcl)
            result = _run_vivado(
                tcl_path,
                project_path.parent,
                risk_class="R1",
                reports=[(util_report, "utilization_report")],
            )
            if util_report.exists():
                result["util_report_excerpt"] = util_report.read_text(
                    encoding="utf-8", errors="ignore"
                )[-2000:]
            return _json_text(result)

        if name == "place_route":
            _validate_identifier(arguments["top"], "top")
            strategy = _validate_strategy(arguments.get("strategy", "Performance_Explore"))
            util_report = project_path.parent / "impl_util.rpt"
            timing_report = project_path.parent / "impl_timing.rpt"
            tcl = (
                f"open_project {_tcl_path(project_path)}\n"
                f"set_property strategy {strategy} [get_runs impl_1]\n"
                "launch_runs impl_1 -to_step route_design\nwait_on_run impl_1\nopen_run impl_1\n"
                f"report_utilization -file {_tcl_path(util_report)}\n"
                f"report_timing_summary -file {_tcl_path(timing_report)}\nexit\n"
            )
            tcl_path = _write_tcl(project_path, tcl)
            result = _run_vivado(
                tcl_path,
                project_path.parent,
                timeout=MAX_TIMEOUT_SECONDS,
                risk_class="R1",
                reports=[
                    (util_report, "utilization_report"),
                    (timing_report, "timing_report"),
                ],
            )
            if "report_evidence" in result:
                result["timing"] = result["report_evidence"]["timing_report"]["metrics"]
            return _json_text(result)

        if name == "report_timing":
            run = _validate_run(arguments.get("run", "impl_1"))
            report = project_path.parent / "timing_summary.rpt"
            output = _resolve_output_path(
                arguments.get("output_json"), project_path.parent / "timing_summary.json", ".json"
            )
            tcl = (
                f"open_project {_tcl_path(project_path)}\nopen_run {run}\n"
                f"report_timing_summary -delay_type min_max -max_paths 10 -file {_tcl_path(report)}\nexit\n"
            )
            tcl_path = _write_tcl(project_path, tcl)
            result = _run_vivado(
                tcl_path,
                project_path.parent,
                risk_class="R0",
                reports=[(report, "timing_report")],
            )
            if "report_evidence" in result:
                result["timing"] = result["report_evidence"]["timing_report"]["metrics"]
                _write_json(output, result["timing"])
                result["output_json"] = str(output)
            return _json_text(result)

        if name == "report_cdc":
            run = _validate_run(arguments.get("run", "synth_1"))
            report = project_path.parent / "cdc.rpt"
            output = _resolve_output_path(
                arguments.get("output_json"), project_path.parent / "cdc.json", ".json"
            )
            tcl = (
                f"open_project {_tcl_path(project_path)}\nopen_run {run}\n"
                f"report_cdc -all_checks_per_endpoint -file {_tcl_path(report)}\nexit\n"
            )
            tcl_path = _write_tcl(project_path, tcl)
            result = _run_vivado(
                tcl_path,
                project_path.parent,
                risk_class="R0",
                reports=[(report, "cdc_report")],
            )
            if "report_evidence" in result:
                result["cdc"] = result["report_evidence"]["cdc_report"]["metrics"]
                _write_json(output, result["cdc"])
                result["output_json"] = str(output)
            return _json_text(result)

        if name == "write_bitstream":
            bit_name = _validate_bitstream_name(arguments.get("bitstream_name", "design.bit"))
            bit_path = project_path.parent / bit_name
            tcl = (
                f"open_project {_tcl_path(project_path)}\nopen_run impl_1\n"
                f"write_bitstream -force -file {_tcl_path(bit_path)}\nexit\n"
            )
            tcl_path = _write_tcl(project_path, tcl)
            result = _run_vivado(tcl_path, project_path.parent, risk_class="R1")
            if bit_path.exists():
                result.update(bitstream_path=str(bit_path), bitstream_size_bytes=bit_path.stat().st_size)
            return _json_text(result)

        script_path = _resolve_project_file(arguments["script_path"], ".tcl")
        supplied_hash = str(arguments["sha256"]).lower()
        actual_hash = hashlib.sha256(script_path.read_bytes()).hexdigest()
        if supplied_hash != actual_hash or actual_hash not in SCRIPT_HASH_ALLOWLIST:
            return _error("Tcl 脚本 SHA-256 未获批准", actual_sha256=actual_hash)
        content = script_path.read_text(encoding="utf-8", errors="strict")
        if re.search(r"(?im)^\s*(exec\b|file\s+(delete|rename)\b)", content):
            return _error("批准脚本仍包含策略禁止的外部执行或文件破坏命令")
        timeout = arguments.get("timeout", 3600)
        return _json_text(_run_vivado(script_path, project_path.parent, timeout=timeout))
    except BackendBlockedError as exc:
        return _error(str(exc), status="BLOCKED")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return _error(str(exc))


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
