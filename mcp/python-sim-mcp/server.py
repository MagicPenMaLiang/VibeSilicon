#!/usr/bin/env python3
"""
python-sim-mcp: Python 定点仿真 + numpy diff MCP 服务器

按计划 §6.2.2 暴露 4 个工具：
- fxp_sim：fxpmath 定点模拟（与 HLS C-Sim 对照）
- numpy_diff：numpy 数组 bit-match 检查
- load_vectors：从 test_vectors.yaml 加载测试输入/黄金输出
- psnr_ssim：图像质量评估（PSNR/SSIM，针对图像 IP）

用法（opencode.json 已注册）：
  python mcp/python-sim-mcp/server.py
"""

import asyncio
import json
import os
from pathlib import Path

import numpy as np
import yaml

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


try:
    import fxpmath
    HAS_FXPMATH = True
except ImportError:
    HAS_FXPMATH = False

try:
    from skimage.metrics import peak_signal_noise_ratio as psnr
    from skimage.metrics import structural_similarity as ssim
    HAS_SKIMAGE = True
except ImportError:
    HAS_SKIMAGE = False


PROJECT_ROOT = Path(os.environ.get("VIBESILICON_ROOT", os.getcwd())).resolve()
MAX_ARRAY_ELEMENTS = int(os.environ.get("VIBESILICON_MAX_ARRAY_ELEMENTS", "10000000"))

app = Server("python-sim")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="fxp_sim",
            description="fxpmath 定点模拟：将 Python float 转 Q_FRAC 定点（与 HLS C-Sim 对照）",
            inputSchema={
                "type": "object",
                "properties": {
                    "values": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "浮点输入列表",
                    },
                    "n_word": {
                        "type": "integer",
                        "default": 16,
                        "description": "总位宽",
                    },
                    "n_frac": {
                        "type": "integer",
                        "default": 8,
                        "description": "小数位数（Q_FRAC）",
                    },
                    "signed": {
                        "type": "boolean",
                        "default": False,
                        "description": "是否带符号",
                    },
                },
                "required": ["values"],
            },
        ),
        Tool(
            name="numpy_diff",
            description="numpy 数组 bit-match 检查（两个 numpy 数组是否完全相等）",
            inputSchema={
                "type": "object",
                "properties": {
                    "array_a": {"type": "string", "description": "数组 A 文件路径（.npy）或内联数组"},
                    "array_b": {"type": "string", "description": "数组 B 文件路径（.npy）或内联数组"},
                    "rtol": {"type": "number", "default": 0, "description": "相对容差"},
                    "atol": {"type": "number", "default": 0, "description": "绝对容差"},
                },
                "required": ["array_a", "array_b"],
            },
        ),
        Tool(
            name="load_vectors",
            description="从 test_vectors.yaml 加载测试用例 + 黄金参考数据",
            inputSchema={
                "type": "object",
                "properties": {
                    "yaml_path": {
                        "type": "string",
                        "description": "test_vectors.yaml 路径",
                    },
                },
                "required": ["yaml_path"],
            },
        ),
        Tool(
            name="psnr_ssim",
            description="图像质量评估：PSNR / SSIM（针对图像处理 IP）",
            inputSchema={
                "type": "object",
                "properties": {
                    "image_ref": {
                        "type": "string",
                        "description": "参考图像路径（.npy 或 .png）",
                    },
                    "image_test": {
                        "type": "string",
                        "description": "待评估图像路径（.npy 或 .png）",
                    },
                    "data_range": {
                        "type": "number",
                        "default": 255,
                        "description": "像素值范围（默认 8bit）",
                    },
                },
                "required": ["image_ref", "image_test"],
            },
        ),
    ]


def _resolve_project_file(arg: str, suffixes: set[str]) -> Path:
    """Resolve a user path inside PROJECT_ROOT and reject traversal/symlink escapes."""
    raw = Path(arg)
    try:
        candidate = (raw if raw.is_absolute() else PROJECT_ROOT / raw).resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError(f"输入文件不存在或无法访问：{arg}") from exc
    try:
        candidate.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"路径超出项目根目录：{candidate}") from exc
    if not candidate.is_file():
        raise ValueError(f"不是普通文件：{candidate}")
    if candidate.suffix.lower() not in suffixes:
        raise ValueError(f"不支持的文件类型：{candidate.suffix}")
    return candidate


def _validate_array(array: np.ndarray) -> np.ndarray:
    if array.dtype.kind not in "biufc":
        raise ValueError(f"只允许数值数组，实际 dtype={array.dtype}")
    if array.ndim > 4:
        raise ValueError(f"数组维度过高：{array.ndim} > 4")
    if array.size > MAX_ARRAY_ELEMENTS:
        raise ValueError(f"数组元素过多：{array.size} > {MAX_ARRAY_ELEMENTS}")
    return array


def _reject_json_constant(value: str):
    raise ValueError(f"JSON 不允许非常量数值：{value}")


def _load_array(arg: str) -> np.ndarray:
    """Load a root-confined .npy file or a strict JSON numeric array."""
    if not isinstance(arg, str):
        raise ValueError("数组输入必须是 .npy 路径或 JSON 数组字符串")

    stripped = arg.strip()
    if stripped.startswith("["):
        try:
            data = json.loads(stripped, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("无法解析严格 JSON 数组") from exc
        if not isinstance(data, list):
            raise ValueError("内联输入必须是 JSON 数组")
        return _validate_array(np.asarray(data))

    path = _resolve_project_file(stripped, {".npy"})
    return _validate_array(np.load(path, allow_pickle=False))


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "fxp_sim":
        if not HAS_FXPMATH:
            return [TextContent(type="text", text="ERROR: fxpmath 未安装（pip install fxpmath）")]
        values = arguments["values"]
        n_word = arguments.get("n_word", 16)
        n_frac = arguments.get("n_frac", 8)
        signed = arguments.get("signed", False)
        try:
            x = fxpmath.Fxp(values, signed=signed, n_word=n_word, n_frac=n_frac)
            return [TextContent(
                type="text",
                text=str({"input": values, "fxp_repr": str(x), "fxp_value": x.get_val().tolist()}),
            )]
        except Exception as e:
            return [TextContent(type="text", text=f"ERROR: {e}")]

    elif name == "numpy_diff":
        try:
            a = _load_array(arguments["array_a"])
            b = _load_array(arguments["array_b"])
            rtol = arguments.get("rtol", 0)
            atol = arguments.get("atol", 0)
            if a.shape != b.shape:
                return [TextContent(type="text", text=(
                    f"FAIL: shape mismatch {a.shape} vs {b.shape}"
                ))]
            if np.allclose(a, b, rtol=rtol, atol=atol):
                return [TextContent(type="text", text=str({
                    "pass": True, "shape": a.shape, "rtol": rtol, "atol": atol,
                }))]
            diff = np.abs(a.astype(int) - b.astype(int))
            return [TextContent(type="text", text=str({
                "pass": False,
                "shape": a.shape,
                "max_abs_diff": int(diff.max()),
                "mean_abs_diff": float(diff.mean()),
                "mismatch_count": int((diff > 0).sum()),
                "total_elements": int(a.size),
            }))]
        except Exception as e:
            return [TextContent(type="text", text=f"ERROR: {e}")]

    elif name == "load_vectors":
        try:
            yaml_path = _resolve_project_file(arguments["yaml_path"], {".yaml", ".yml"})
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return [TextContent(type="text", text=str(data))]
        except Exception as e:
            return [TextContent(type="text", text=f"ERROR: {e}")]

    elif name == "psnr_ssim":
        if not HAS_SKIMAGE:
            return [TextContent(type="text", text="ERROR: scikit-image 未安装（pip install scikit-image）")]
        try:
            ref = _load_array(arguments["image_ref"])
            test = _load_array(arguments["image_test"])
            data_range = arguments.get("data_range", 255)
            p = float(psnr(ref, test, data_range=data_range))
            channel_axis = -1 if ref.ndim == 3 else None
            s = float(ssim(ref, test, data_range=data_range, channel_axis=channel_axis))
            return [TextContent(type="text", text=str({
                "psnr_db": p, "ssim": s,
                "pass": p >= 45.0 and s >= 0.99,
                "thresholds": {"psnr_db": 45.0, "ssim": 0.99},
            }))]
        except Exception as e:
            return [TextContent(type="text", text=f"ERROR: {e}")]

    return [TextContent(type="text", text=f"ERROR: 未知 tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream, write_stream, app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
