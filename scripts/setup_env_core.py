#!/usr/bin/env python3
"""Shared core for VibeSilicon environment setup.

Used by ``scripts/setup_env.sh`` (Linux/macOS), ``scripts/setup_env.ps1``
(PowerShell), and ``scripts/setup_env.cmd`` (cmd). The logic stays in one
place so the exit code contract, dependency check, and EDA probe results are
identical regardless of the launcher.

Exit codes (intentionally distinct from generic Python errors):

* ``0`` - all required Python dependencies are importable; smoke checks pass.
* ``2`` - the Python virtual environment cannot be created or bootstrapped.
* ``3`` - one or more locked Python dependencies failed to install or import.
* ``4`` - the ``public_release_audit.py`` gate reported failures.
* ``5`` - the unit-test smoke run failed.
* ``10`` - one or more optional EDA tools are missing (warning only, NOT failure).

The script never aborts early on the first problem: it runs every check and
prints a structured report so the caller can decide what to fix first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import venv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
LOCK_FILE = ROOT / "requirements-dev.lock"
RUNTIME_LOCK = ROOT / "requirements.lock"
VENV_DIR = ROOT / ".venv"
PUBLIC_AUDIT = ROOT / "scripts" / "public_release_audit.py"
TESTS_DIR = ROOT / "tests"


@dataclass
class CheckResult:
    name: str
    status: str  # "OK" | "WARN" | "FAIL" | "SKIP"
    detail: str = ""
    required: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "required": self.required,
        }


@dataclass
class SetupReport:
    python: str = ""
    venv: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    missing_eda: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if any(c.status == "FAIL" and c.required for c in self.checks):
            # Rank the failure so the launcher can show the most specific cause.
            by_name = {c.name: c for c in self.checks}
            if by_name.get("venv-create", CheckResult("x", "OK")).status == "FAIL":
                return 2
            if by_name.get("pip-install", CheckResult("x", "OK")).status == "FAIL":
                return 3
            if by_name.get("import-smoke", CheckResult("x", "OK")).status == "FAIL":
                return 3
            if by_name.get("public-release-audit", CheckResult("x", "OK")).status == "FAIL":
                return 4
            if by_name.get("unit-tests", CheckResult("x", "OK")).status == "FAIL":
                return 5
            return 1
        if self.missing_eda:
            return 10
        return 0


def venv_python() -> Path:
    return VENV_DIR / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python"
    )


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def ensure_venv(report: SetupReport, recreate: bool) -> Path:
    """Create or reuse ``.venv``. Returns the venv Python path."""
    py = venv_python()
    if py.is_file() and not recreate:
        report.checks.append(CheckResult("venv-create", "OK", f"reused {py}", required=True))
        return py
    if recreate and VENV_DIR.exists():
        shutil.rmtree(VENV_DIR, ignore_errors=True)
    VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
    builder = venv.EnvBuilder(
        system_site_packages=False,
        clear=True,
        symlinks=False,
        with_pip=True,
    )
    try:
        builder.create(str(VENV_DIR))
    except Exception as exc:  # venv raises plain Exception on missing ensurepip
        report.checks.append(
            CheckResult("venv-create", "FAIL", f"{type(exc).__name__}: {exc}", required=True)
        )
        return py
    if not py.is_file():
        report.checks.append(
            CheckResult("venv-create", "FAIL", f"python not produced at {py}", required=True)
        )
        return py
    report.checks.append(CheckResult("venv-create", "OK", f"created {py}", required=True))
    return py


def install_locked(py: Path, report: SetupReport) -> None:
    if not LOCK_FILE.is_file():
        report.checks.append(
            CheckResult(
                "pip-install",
                "FAIL",
                f"missing lock file: {LOCK_FILE.relative_to(ROOT)}",
                required=True,
            )
        )
        return
    cmd = [
        str(py),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "-r",
        str(LOCK_FILE),
    ]
    try:
        result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    except OSError as exc:
        report.checks.append(CheckResult("pip-install", "FAIL", f"pip launch failed: {exc}", required=True))
        return
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-5:]
        report.checks.append(
            CheckResult(
                "pip-install",
                "FAIL",
                f"pip exit {result.returncode}; tail: {' | '.join(tail)}",
                required=True,
            )
        )
        return
    report.checks.append(
        CheckResult(
            "pip-install",
            "OK",
            f"installed from {LOCK_FILE.relative_to(ROOT)} (sha256={file_sha256(LOCK_FILE)[:12]})",
            required=True,
        )
    )


def _safe_version(distribution_name: str) -> str:
    """Return the installed distribution version without triggering
    jsonschema's ``__version__`` deprecation warning."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version(distribution_name)
    except Exception:  # noqa: BLE001 - missing distribution is a normal fallback
        return "ok"


def import_smoke(py: Path, report: SetupReport) -> None:
    """Verify each locked package imports under the venv's interpreter.

    The probe runs in a *child* Python process (``py``) so a fresh checkout
    whose launcher invokes the core with a different host interpreter still
    reports the venv's site-packages accurately.
    """
    pkgs = ["mcp", "numpy", "yaml", "fxpmath", "skimage", "jsonschema", "pytest", "ruff"]
    probe_script = (
        "import importlib, json, sys\n"
        "from importlib.metadata import PackageNotFoundError, version\n"
        "out = {}\n"
        "for name in " + repr(pkgs) + ":\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except Exception as exc:\n"
        "        out[name] = {'ok': False, 'error': f'{type(exc).__name__}: {exc}'}\n"
        "        continue\n"
        "    try:\n"
        "        out[name] = {'ok': True, 'version': version(name)}\n"
        "    except PackageNotFoundError:\n"
        "        out[name] = {'ok': True, 'version': 'ok'}\n"
        "print(json.dumps(out))\n"
    )
    result = subprocess.run(
        [str(py), "-c", probe_script],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        merged = ((result.stderr or "") + "\n" + (result.stdout or "")).strip()
        report.checks.append(
            CheckResult(
                "import-smoke",
                "FAIL",
                f"probe exit {result.returncode}: {merged[:500]}",
                required=True,
            )
        )
        return
    raw = (result.stdout or "").strip().splitlines()[-1]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        report.checks.append(
            CheckResult(
                "import-smoke",
                "FAIL",
                f"unparseable probe output: {exc}; raw={raw[:200]}",
                required=True,
            )
        )
        return
    failures = [f"{n}: {info['error']}" for n, info in payload.items() if not info.get("ok")]
    if failures:
        report.checks.append(
            CheckResult("import-smoke", "FAIL", "; ".join(failures), required=True)
        )
        return
    versions = [f"{n}={payload[n].get('version', 'ok')}" for n in pkgs]
    report.checks.append(CheckResult("import-smoke", "OK", ", ".join(versions), required=True))


def public_audit(py: Path, report: SetupReport) -> None:
    if not PUBLIC_AUDIT.is_file():
        report.checks.append(
            CheckResult("public-release-audit", "SKIP", f"missing {PUBLIC_AUDIT}", required=True)
        )
        return
    result = subprocess.run(
        [str(py), str(PUBLIC_AUDIT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        report.checks.append(
            CheckResult("public-release-audit", "OK", "no blocked paths", required=True)
        )
        return
    # Audit script writes diagnostic lines to stdout; merge both streams so
    # the report shows the *reason* it returned non-zero.
    merged = "\n".join(
        line for line in ((result.stdout or "") + "\n" + (result.stderr or "")).splitlines()
        if line.strip()
    )
    tail_lines = merged.splitlines()[-5:]
    detail = f"exit {result.returncode}"
    if tail_lines:
        detail += "; tail: " + " | ".join(tail_lines)
    report.checks.append(
        CheckResult("public-release-audit", "FAIL", detail, required=True)
    )


def unit_tests(py: Path, report: SetupReport, skip: bool) -> None:
    if skip:
        report.checks.append(
            CheckResult("unit-tests", "SKIP", "skipped via --skip-tests", required=True)
        )
        return
    if not TESTS_DIR.is_dir():
        report.checks.append(
            CheckResult("unit-tests", "SKIP", f"missing {TESTS_DIR}", required=True)
        )
        return
    cmd = [
        str(py),
        "-m",
        "unittest",
        "discover",
        "-s",
        str(TESTS_DIR),
        "-p",
        "test_*.py",
    ]
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    if result.returncode == 0:
        last = (result.stderr or result.stdout).strip().splitlines()[-1:]
        report.checks.append(
            CheckResult("unit-tests", "OK", last[0] if last else "all tests passed", required=True)
        )
        return
    tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
    report.checks.append(
        CheckResult(
            "unit-tests",
            "FAIL",
            f"exit {result.returncode}; tail: {' | '.join(tail)}",
            required=True,
        )
    )


# Optional EDA tools probed by name; the row also documents which flow needs them.
EDA_PROBES: tuple[tuple[str, str, bool], ...] = (
    ("verilator", "verilator", True),
    ("yosys", "yosys", True),
    ("symbiyosys", "sby", True),
    ("vivado", "vivado", False),
    ("vitis_hls", "vitis_hls", False),
    ("openroad", "openroad", False),
    ("klayout", "klayout", False),
)


def probe_eda(report: SetupReport) -> None:
    """Detect optional EDA binaries on PATH. Required-flag is informational only."""
    for display, command, required in EDA_PROBES:
        located = shutil.which(command) or shutil.which(f"{command}.exe")
        if located:
            report.checks.append(
                CheckResult(
                    f"eda:{display}",
                    "OK",
                    located,
                    required=required,
                )
            )
        else:
            report.missing_eda.append(display)
            report.checks.append(
                CheckResult(
                    f"eda:{display}",
                    "WARN",
                    "not found on PATH",
                    required=required,
                )
            )


def parse_requirements(pkg_spec: str) -> str:
    """``pkg==1.2.3`` -> ``pkg`` (used purely for the human report)."""
    for sep in ("==", ">=", "<=", "~=", "!=", ">"):
        if sep in pkg_spec:
            return pkg_spec.split(sep, 1)[0].strip()
    return pkg_spec.strip()


def collect_locked_packages() -> list[str]:
    if not RUNTIME_LOCK.is_file():
        return []
    pkgs: list[str] = []
    for raw in RUNTIME_LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pkgs.append(parse_requirements(line))
    return pkgs


def render_text(report: SetupReport) -> str:
    lines: list[str] = []
    lines.append("VibeSilicon environment report")
    lines.append("=" * 32)
    lines.append(f"root        : {ROOT}")
    lines.append(f"python      : {report.python}")
    lines.append(f"venv python : {report.venv}")
    lines.append("")
    lines.append("Checks:")
    for c in report.checks:
        marker = "OK" if c.status == "OK" else c.status
        req = "" if c.required else "  (optional)"
        detail = f"  {c.detail}" if c.detail else ""
        lines.append(f"  [{marker:>4}] {c.name}{req}{detail}")
    lines.append("")
    if report.missing_eda:
        lines.append("Missing optional EDA tools:")
        for name in report.missing_eda:
            lines.append(f"  - {name}")
        lines.append("")
    locked = collect_locked_packages()
    if locked:
        lines.append("Locked runtime packages (from requirements.lock):")
        lines.append("  " + ", ".join(locked))
        lines.append("")
    lines.append(f"Exit code: {report.exit_code}")
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="VibeSilicon environment setup core.",
        exit_on_error=False,
    )
    parser.add_argument("--recreate-venv", action="store_true", help="delete and rebuild .venv")
    parser.add_argument("--skip-tests", action="store_true", help="skip unit-test smoke run")
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="skip pip install (assume dependencies already present)",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="skip public_release_audit.py gate (default for first-run)",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="run the public_release_audit.py source-tree gate",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except argparse.ArgumentError as exc:
        parser.print_usage(sys.stderr)
        print(f"setup_env_core.py: error: {exc}", file=sys.stderr)
        return 64

    report = SetupReport()
    report.python = sys.executable
    py = ensure_venv(report, recreate=args.recreate_venv)

    if py.is_file():
        report.venv = str(py)
        if not args.no_install:
            install_locked(py, report)
        import_smoke(py, report)
        # Audit defaults to OFF so a fresh checkout is not blocked by transient
        # workspace artifacts (node_modules, generated logs). Opt in via --audit.
        run_audit = args.audit and not args.no_audit
        if run_audit:
            public_audit(py, report)
        else:
            report.checks.append(
                CheckResult(
                    "public-release-audit",
                    "SKIP",
                    "skipped (default; pass --audit to run)",
                    required=True,
                )
            )
        unit_tests(py, report, skip=args.skip_tests)
    else:
        # Venv creation failed; downstream checks cannot run.
        report.checks.append(CheckResult("import-smoke", "SKIP", "no venv python", required=True))
        report.checks.append(CheckResult("public-release-audit", "SKIP", "no venv python", required=True))
        report.checks.append(CheckResult("unit-tests", "SKIP", "no venv python", required=True))

    probe_eda(report)

    if args.json:
        print(
            json.dumps(
                {
                    "python": report.python,
                    "venv": report.venv,
                    "exit_code": report.exit_code,
                    "missing_eda": report.missing_eda,
                    "checks": [c.to_dict() for c in report.checks],
                },
                indent=2,
            )
        )
    else:
        print(render_text(report))

    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
