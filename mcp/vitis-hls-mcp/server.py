#!/usr/bin/env python3
"""
vitis-hls-mcp: Bounded Vitis HLS integration MCP server.

Exposes four tools:
- csim: C simulation against a project-supplied self-checking testbench.
- csynth: C synthesis producing RTL and resource reports.
- co_sim: RTL co-simulation
- export: Export IP-XACT, Vivado IP or Vitis kernel artifacts.

Usage (registered in opencode.json):
  python mcp/vitis-hls-mcp/server.py

Tool selection comes from the launcher environment or PATH:
  VITIS_RUN_BIN: Selected vitis-run or legacy vitis_hls executable.
  VITIS_HLS_PATH: Optional HLS installation root used by the launcher.
"""

import asyncio
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


VITIS_RUN_BIN = (
    os.environ.get("VITIS_RUN_BIN")
    or shutil.which("vitis-run")
    or shutil.which("vitis_hls")
    or "vitis-run"
)
VITIS_HLS_BIN = VITIS_RUN_BIN

PROJECT_ROOT = Path(os.environ.get("VIBESILICON_ROOT", os.getcwd())).resolve()
DEFAULT_CLOCK_NS = 10.0
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PART_RE = re.compile(r"^xc[a-z0-9-]+$", re.IGNORECASE)

app = Server("vitis-hls")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="csim",
            description="Run HLS C simulation; correctness requires independent checks against the frozen golden reference",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_dir": {
                        "type": "string",
                        "description": "HLS project directory within the declared project root",
                    },
                    "top_function": {
                        "type": "string",
                        "description": "Top-level function name used by set_top",
                    },
                    "testbench": {
                        "type": "string",
                        "description": "Testbench .cpp path relative to project_dir",
                        "default": "testbench.cpp",
                    },
                },
                "required": ["project_dir", "top_function"],
            },
        ),
        Tool(
            name="csynth",
            description="Run HLS C synthesis to produce RTL and BRAM/URAM/DSP/LUT/FF reports",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_dir": {"type": "string"},
                    "top_function": {"type": "string"},
                    "clock_period_ns": {
                        "type": "number",
                        "default": DEFAULT_CLOCK_NS,
                        "description": "Clock period in ns (default 10 ns, equivalent to 100 MHz)",
                    },
                    "part": {
                        "type": "string",
                        "description": "Complete reviewed FPGA part name; no repository-default device",
                    },
                },
                "required": ["project_dir", "top_function", "part"],
            },
        ),
        Tool(
            name="co_sim",
            description="Run RTL co-simulation against the C++ testbench using the configured simulation flow",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_dir": {"type": "string"},
                    "top_function": {"type": "string"},
                },
                "required": ["project_dir", "top_function"],
            },
        ),
        Tool(
            name="export",
            description="Export IP: ipxact, vivado_ip or vitis_kernel (.xo)",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_dir": {"type": "string"},
                    "top_function": {"type": "string"},
                    "format": {
                        "type": "string",
                        "enum": ["ipxact", "vivado_ip", "vitis_kernel"],
                        "default": "ipxact",
                    },
                },
                "required": ["project_dir", "top_function", "format"],
            },
        ),
    ]


def _run_vitis_hls(tcl_path: Path, cwd: Path) -> dict[str, Any]:
    """Execute the selected HLS tool and capture bounded stdout/stderr excerpts."""
    arguments = [VITIS_RUN_BIN, "--mode", "hls", "--tcl", str(tcl_path)]
    cmd = ["cmd", "/c", *arguments] if os.name == "nt" and VITIS_RUN_BIN.lower().endswith((".bat", ".cmd")) else arguments
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=900,  # 15 minutes; synthesis can take longer than C simulation.
            shell=False,
        )
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout_tail": result.stdout[-3000:] if result.stdout else "",
            "stderr_tail": result.stderr[-3000:] if result.stderr else "",
            "tcl_script": str(tcl_path),
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Timeout (900s)", "tcl_script": str(tcl_path)}
    except FileNotFoundError as e:
        return {
            "success": False,
            "error": f"Vitis HLS launcher not found: {VITIS_HLS_BIN}",
            "hint": "Set VITIS_RUN_BIN or add vitis-run to PATH.",
            "exception": str(e),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "tcl_script": str(tcl_path)}


def _write_tcl(project_dir: Path, content: str) -> Path:
    """Write one unique generated Tcl script under the ignored tool state directory."""
    state_dir = project_dir / ".vibesilicon" / "vitis-hls"
    state_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".tcl", prefix="run_", dir=state_dir, delete=False
    ) as stream:
        stream.write(content)
        return Path(stream.name)


def _resolve_project_dir(arg: str) -> Path:
    """Resolve an existing project directory and confine it to the declared root."""
    raw = Path(arg)
    path = (raw if raw.is_absolute() else PROJECT_ROOT / raw).resolve(strict=True)
    try:
        path.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError("project_dir escapes the allowed project root") from exc
    if not path.is_dir():
        raise ValueError("project_dir must be a directory")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", path.name):
        raise ValueError("project_dir name contains unsafe Tcl characters")
    return path


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field} contains unsafe characters")
    return value


def _part(value: Any) -> str:
    if not isinstance(value, str) or not PART_RE.fullmatch(value):
        raise ValueError("invalid part name")
    return value


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    project_dir = _resolve_project_dir(arguments["project_dir"])
    top = _identifier(arguments["top_function"], "top_function")

    if not project_dir.exists():
        return [
            TextContent(
                type="text",
                text=f"ERROR: project_dir does not exist: {project_dir}",
            )
        ]

    if name == "csim":
        testbench = arguments.get("testbench", "testbench.cpp")
        tcl = (
            f"open_project {project_dir.name}\n"
            f"set_top {top}\n"
            f"add_files {testbench}\n"
            f'open_solution "solution1"\n'
            f"csim_design\n"
            f"exit\n"
        )
        tcl_path = _write_tcl(project_dir, tcl)
        result = _run_vitis_hls(tcl_path, project_dir)
        return [TextContent(type="text", text=str(result))]

    elif name == "csynth":
        clock_ns = arguments.get("clock_period_ns", DEFAULT_CLOCK_NS)
        if isinstance(clock_ns, bool) or not isinstance(clock_ns, (int, float)) or not math.isfinite(clock_ns) or clock_ns <= 0:
            return [TextContent(type="text", text="ERROR: clock_period_ns must be a positive finite number")]
        part = _part(arguments["part"])
        tcl = (
            f"open_project {project_dir.name}\n"
            f"set_top {top}\n"
            f"add_files {project_dir.name}.cpp\n"
            f'open_solution "solution1" -flow_target vivado\n'
            f"set_part {part}\n"
            f"create_clock -period {clock_ns} -name default\n"
            f"csynth_design\n"
            f"exit\n"
        )
        tcl_path = _write_tcl(project_dir, tcl)
        result = _run_vitis_hls(tcl_path, project_dir)

        # Preserve a bounded synthesis-report excerpt for review.
        csynth_report = project_dir / "solution1" / "syn" / "report" / "csynth.rpt"
        if csynth_report.exists():
            result["csynth_report_excerpt"] = csynth_report.read_text(
                encoding="utf-8", errors="ignore"
            )[-3000:]
        return [TextContent(type="text", text=str(result))]

    elif name == "co_sim":
        tcl = (
            f"open_project {project_dir.name}\n"
            f"set_top {top}\n"
            f'open_solution "solution1"\n'
            f"cosim_design -trace_level all\n"
            f"exit\n"
        )
        tcl_path = _write_tcl(project_dir, tcl)
        result = _run_vitis_hls(tcl_path, project_dir)
        return [TextContent(type="text", text=str(result))]

    elif name == "export":
        fmt = arguments.get("format", "ipxact")
        if fmt == "ipxact":
            cmd = "export_design -format ipxact"
        elif fmt == "vivado_ip":
            cmd = "export_design -format vivado"
        elif fmt == "vitis_kernel":
            cmd = "export_design -format vitis_kernel"
        else:
            return [
                TextContent(type="text", text=f"ERROR: unknown format: {fmt}")
            ]

        tcl = (
            f"open_project {project_dir.name}\n"
            f"set_top {top}\n"
            f'open_solution "solution1"\n'
            f"{cmd}\n"
            f"exit\n"
        )
        tcl_path = _write_tcl(project_dir, tcl)
        result = _run_vitis_hls(tcl_path, project_dir)
        return [TextContent(type="text", text=str(result))]

    return [TextContent(type="text", text=f"ERROR: unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream, write_stream, app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
