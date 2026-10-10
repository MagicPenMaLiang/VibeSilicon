#!/usr/bin/env python3
"""Select a usable Python runtime and launch a VibeSilicon MCP server over stdio."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER_PATHS = {
    "python-sim": ROOT / "mcp" / "python-sim-mcp" / "server.py",
    "vitis-hls": ROOT / "mcp" / "vitis-hls-mcp" / "server.py",
    "vivado": ROOT / "mcp" / "vivado-mcp" / "server.py",
}
PROBE_IMPORTS = "import mcp.server, numpy, yaml"
LOCAL_TOOL_ENV = ROOT / ".vibesilicon" / "mcp-env.json"
LOCAL_TOOL_KEYS = {"VIVADO_BIN", "VIVADO_SETTINGS", "VITIS_RUN_BIN"}


def load_tool_environment(path: Path, environment: dict[str, str]) -> dict[str, str]:
    """Merge ignored, machine-local tool paths without overriding explicit env vars."""
    result = environment.copy()
    if not path.is_file():
        return result
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict) or set(values) - LOCAL_TOOL_KEYS:
        raise ValueError("local MCP environment must contain only supported tool-path keys")
    for key, value in values.items():
        if not isinstance(value, str) or not value or not Path(value).is_absolute():
            raise ValueError(f"{key} must be an absolute tool path")
        if key not in result:
            if not Path(value).is_file():
                raise ValueError(f"configured tool path does not exist: {key}")
            result[key] = value
    return result


def _conda_python(prefix: str | None) -> Path | None:
    if not prefix:
        return None
    base = Path(prefix)
    return base / ("python.exe" if os.name == "nt" else "bin/python")


def _venv_python(prefix: str | None) -> Path | None:
    if not prefix:
        return None
    base = Path(prefix)
    return base / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def runtime_candidates() -> list[Path]:
    """Return de-duplicated Python candidates in preference order."""
    candidates: list[Path | None] = [
        Path(os.environ["VIBESILICON_MCP_PYTHON"])
        if os.environ.get("VIBESILICON_MCP_PYTHON")
        else None,
        Path(sys.executable),
        ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"),
        _conda_python(os.environ.get("CONDA_PREFIX")),
        _venv_python(os.environ.get("VIRTUAL_ENV")),
    ]
    for command in ("python", "python3"):
        resolved = shutil.which(command)
        candidates.append(Path(resolved) if resolved else None)

    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        key = str(candidate.resolve(strict=False)).lower() if os.name == "nt" else str(candidate)
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def probe_runtime(candidate: Path, timeout: int = 10) -> tuple[bool, str]:
    if not candidate.is_file():
        return False, "runtime does not exist"
    try:
        probe = subprocess.run(
            [str(candidate), "-B", "-c", PROBE_IMPORTS],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    detail = (probe.stderr or probe.stdout).strip()
    return probe.returncode == 0, detail[-500:]


def select_runtime() -> tuple[Path | None, list[dict[str, str | bool]]]:
    attempts: list[dict[str, str | bool]] = []
    for candidate in runtime_candidates():
        ok, detail = probe_runtime(candidate)
        attempts.append({"runtime": str(candidate), "ok": ok, "detail": detail})
        if ok:
            return candidate, attempts
    return None, attempts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("server", choices=sorted(SERVER_PATHS))
    parser.add_argument("--probe", action="store_true", help="print selection result without launching")
    args = parser.parse_args()

    try:
        tool_env = load_tool_environment(LOCAL_TOOL_ENV, dict(os.environ))
    except (OSError, ValueError) as exc:
        print(f"VibeSilicon MCP local configuration failed: {exc}", file=sys.stderr)
        return 1

    runtime, attempts = select_runtime()
    server = SERVER_PATHS[args.server]
    if args.probe:
        print(
            json.dumps(
                {
                    "status": "PASS" if runtime and server.is_file() else "FAIL",
                    "server": args.server,
                    "server_path": str(server),
                    "runtime": str(runtime) if runtime else None,
                    "attempts": attempts,
                    "tool_paths": {key: tool_env[key] for key in sorted(LOCAL_TOOL_KEYS) if key in tool_env},
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0 if runtime and server.is_file() else 1

    if runtime is None:
        print(
            "VibeSilicon MCP launch failed: no Python runtime provides mcp, numpy and yaml. "
            "Set VIBESILICON_MCP_PYTHON to a compatible interpreter.",
            file=sys.stderr,
        )
        for attempt in attempts:
            print(f"- {attempt['runtime']}: {attempt['detail']}", file=sys.stderr)
        return 1
    if not server.is_file():
        print(f"VibeSilicon MCP server is missing: {server}", file=sys.stderr)
        return 1

    env = tool_env
    env["VIBESILICON_ROOT"] = str(ROOT)
    # Server modules import repository packages (e.g. scripts.vivado_backend).
    # When the interpreter runs a server script directly, sys.path[0] is the
    # server's own directory, so the repository root must be provided explicitly.
    existing_python_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(ROOT) if not existing_python_path else str(ROOT) + os.pathsep + existing_python_path
    )
    completed = subprocess.run(
        [str(runtime), "-B", str(server)],
        cwd=ROOT,
        env=env,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
