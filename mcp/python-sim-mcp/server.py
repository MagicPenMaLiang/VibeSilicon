#!/usr/bin/env python3
"""
python-sim-mcp: Fixed-point simulation and NumPy comparison MCP server.

Exposes four bounded tools:
- fxp_sim: fxpmath simulation for comparison with HLS C simulation.
- numpy_diff: NumPy array comparison with declared tolerances.
- load_vectors: Load test inputs and golden outputs from YAML.
- psnr_ssim: PSNR/SSIM evaluation for image-processing IP.

Usage (registered in opencode.json):
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
            description="fxpmath fixed-point simulation: quantize floating-point inputs for comparison with HLS C simulation",
            inputSchema={
                "type": "object",
                "properties": {
                    "values": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "List of floating-point inputs",
                    },
                    "n_word": {
                        "type": "integer",
                        "default": 16,
                        "description": "Total bit width",
                    },
                    "n_frac": {
                        "type": "integer",
                        "default": 8,
                        "description": "Fractional bit count (Q_FRAC)",
                    },
                    "signed": {
                        "type": "boolean",
                        "default": False,
                        "description": "Whether values are signed",
                    },
                },
                "required": ["values"],
            },
        ),
        Tool(
            name="numpy_diff",
            description="Compare NumPy arrays using the declared relative and absolute tolerances",
            inputSchema={
                "type": "object",
                "properties": {
                    "array_a": {"type": "string", "description": "Array A: root-confined .npy path or inline JSON array"},
                    "array_b": {"type": "string", "description": "Array B: root-confined .npy path or inline JSON array"},
                    "rtol": {"type": "number", "default": 0, "description": "Relative tolerance"},
                    "atol": {"type": "number", "default": 0, "description": "Absolute tolerance"},
                },
                "required": ["array_a", "array_b"],
            },
        ),
        Tool(
            name="load_vectors",
            description="Load test cases and golden-reference data from test_vectors.yaml",
            inputSchema={
                "type": "object",
                "properties": {
                    "yaml_path": {
                        "type": "string",
                        "description": "Path to test_vectors.yaml",
                    },
                },
                "required": ["yaml_path"],
            },
        ),
        Tool(
            name="psnr_ssim",
            description="Evaluate image quality using PSNR and SSIM",
            inputSchema={
                "type": "object",
                "properties": {
                    "image_ref": {
                        "type": "string",
                        "description": "Reference image: root-confined .npy path or inline JSON array",
                    },
                    "image_test": {
                        "type": "string",
                        "description": "Test image: root-confined .npy path or inline JSON array",
                    },
                    "data_range": {
                        "type": "number",
                        "default": 255,
                        "description": "Pixel-value range (255 for the default 8-bit range)",
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
        raise ValueError(f"input file does not exist or is inaccessible: {arg}") from exc
    try:
        candidate.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {candidate}") from exc
    if not candidate.is_file():
        raise ValueError(f"not a regular file: {candidate}")
    if candidate.suffix.lower() not in suffixes:
        raise ValueError(f"unsupported file type: {candidate.suffix}")
    return candidate


def _validate_array(array: np.ndarray) -> np.ndarray:
    if array.dtype.kind not in "biufc":
        raise ValueError(f"only numeric arrays are allowed; dtype={array.dtype}")
    if array.ndim > 4:
        raise ValueError(f"too many array dimensions: {array.ndim} > 4")
    if array.size > MAX_ARRAY_ELEMENTS:
        raise ValueError(f"too many array elements: {array.size} > {MAX_ARRAY_ELEMENTS}")
    return array


def _reject_json_constant(value: str):
    raise ValueError(f"non-finite JSON numeric constant is not allowed: {value}")


def _load_array(arg: str) -> np.ndarray:
    """Load a root-confined .npy file or a strict JSON numeric array."""
    if not isinstance(arg, str):
        raise ValueError("array input must be a .npy path or a JSON array string")

    stripped = arg.strip()
    if stripped.startswith("["):
        try:
            data = json.loads(stripped, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError("cannot parse strict JSON array") from exc
        if not isinstance(data, list):
            raise ValueError("inline input must be a JSON array")
        return _validate_array(np.asarray(data))

    path = _resolve_project_file(stripped, {".npy"})
    return _validate_array(np.load(path, allow_pickle=False))


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "fxp_sim":
        if not HAS_FXPMATH:
            return [TextContent(type="text", text="ERROR: fxpmath is not installed (pip install fxpmath)")]
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
            return [TextContent(type="text", text="ERROR: scikit-image is not installed (pip install scikit-image)")]
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

    return [TextContent(type="text", text=f"ERROR: unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream, write_stream, app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
