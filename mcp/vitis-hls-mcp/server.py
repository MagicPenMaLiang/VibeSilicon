#!/usr/bin/env python3
"""
vitis-hls-mcp: Vitis HLS 工具集成 MCP 服务器

按计划 §6.2.1 暴露 4 个工具：
- csim：C-Sim（与 Python 黄金参考 diff==0）
- csynth：C-Synth（生成 RTL + 资源报告）
- co_sim：RTL co-simulation
- export：导出 IP-XACT / Vivado IP / Vitis Kernel

用法（opencode.json 已注册）：
  python mcp/vitis-hls-mcp/server.py

环境变量（来自 opencode.json mcpServers.vitis-hls.env）：
  VITIS_HLS_BIN  ：vitis_hls.bat 绝对路径
  VITIS_HLS_PATH ：Vitis HLS 安装根目录
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
            description="HLS C-Sim：编译并运行 .cpp testbench，bit-match Python 黄金参考即 PASS",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_dir": {
                        "type": "string",
                        "description": "HLS 工程目录（绝对路径或相对 cwd）",
                    },
                    "top_function": {
                        "type": "string",
                        "description": "顶层函数名（set_top 的目标）",
                    },
                    "testbench": {
                        "type": "string",
                        "description": "testbench .cpp 路径（相对 project_dir）",
                        "default": "testbench.cpp",
                    },
                },
                "required": ["project_dir", "top_function"],
            },
        ),
        Tool(
            name="csynth",
            description="HLS C-Synth：综合生成 RTL + 资源报告（BRAM/URAM/DSP/LUT/FF）",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_dir": {"type": "string"},
                    "top_function": {"type": "string"},
                    "clock_period_ns": {
                        "type": "number",
                        "default": DEFAULT_CLOCK_NS,
                        "description": "时钟周期（ns），默认 100 MHz",
                    },
                    "part": {
                        "type": "string",
                        "description": "完整 FPGA part 名称；不得依赖仓库内默认器件",
                    },
                },
                "required": ["project_dir", "top_function", "part"],
            },
        ),
        Tool(
            name="co_sim",
            description="RTL Co-Sim：用 Vivado XSim 验证 C-Synth 生成的 RTL 与 C++ 等价",
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
            description="导出 IP：ipxact（Vivado 通用）/ vivado_ip（Vivado IP-XACT 打包）/ vitis_kernel（Vitis .xo）",
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
    """执行 vitis_hls -f <tcl>，捕获 stdout/stderr 尾部避免上下文爆炸。"""
    arguments = [VITIS_RUN_BIN, "--mode", "hls", "--tcl", str(tcl_path)]
    cmd = ["cmd", "/c", *arguments] if os.name == "nt" and VITIS_RUN_BIN.lower().endswith((".bat", ".cmd")) else arguments
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=900,  # 15 分钟（csynth 可能较慢）
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
        raise ValueError("project_dir 超出允许的项目根目录") from exc
    if not path.is_dir():
        raise ValueError("project_dir 必须是目录")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", path.name):
        raise ValueError("project_dir 名称包含不安全的 Tcl 字符")
    return path


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field} 包含不安全字符")
    return value


def _part(value: Any) -> str:
    if not isinstance(value, str) or not PART_RE.fullmatch(value):
        raise ValueError("part 名称无效")
    return value


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    project_dir = _resolve_project_dir(arguments["project_dir"])
    top = _identifier(arguments["top_function"], "top_function")

    if not project_dir.exists():
        return [
            TextContent(
                type="text",
                text=f"ERROR: project_dir 不存在：{project_dir}",
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
            return [TextContent(type="text", text="ERROR: clock_period_ns 必须是正有限数")]
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

        # 解析 csynth 报告（计划 §11.2 ③ 命令 + 预期输出）
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
                TextContent(type="text", text=f"ERROR: 未知 format: {fmt}")
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

    return [TextContent(type="text", text=f"ERROR: 未知 tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream, write_stream, app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
