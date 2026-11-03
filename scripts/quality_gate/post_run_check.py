#!/usr/bin/env python3
"""Run portable RTL checks and consume verified target-tool reports."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

try:
    from scripts.evidence_contract import EvidenceContractError
    from scripts.quality_gate.rtl_readability import analyze as analyze_rtl_readability
    from scripts.quality_gate.rtl_project_lint import _environment as verilator_environment
    from scripts.quality_gate.rtl_quality_config import load_policy
    from scripts.quality_gate.vivado_evidence import load_verified_report
    from scripts.quality_gate.vivado_reports import (
        ReportParseError,
    )
except ModuleNotFoundError:  # Direct execution from scripts/quality_gate.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.evidence_contract import EvidenceContractError
    from rtl_readability import analyze as analyze_rtl_readability  # type: ignore
    from scripts.quality_gate.rtl_project_lint import _environment as verilator_environment
    from rtl_quality_config import load_policy  # type: ignore
    from scripts.quality_gate.vivado_evidence import load_verified_report
    from vivado_reports import (  # type: ignore
        ReportParseError,
    )


PROJECT_ROOT = Path(os.environ.get("VIBESILICON_ROOT", Path.cwd())).resolve()
REPORTS_DIR = PROJECT_ROOT / "scripts" / "quality_gate" / "reports"
ASYNC_REG_SCAN = PROJECT_ROOT / "scripts" / "quality_gate" / "scan_async_reg.py"

VERILATOR = os.environ.get("VERILATOR_BIN") or shutil.which("verilator_bin") or shutil.which(
    "verilator"
)
VERILATOR_ROOT = os.environ.get("VERILATOR_ROOT")

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
ERROR = "ERROR"

THRESHOLDS = load_policy()["legacy_gate_thresholds"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _result(status: str, **details) -> dict:
    """Create a backwards-compatible, explicit check result."""
    if status not in {PASS, FAIL, SKIP, ERROR}:
        raise ValueError(f"invalid quality-gate status: {status}")
    result = {
        "status": status,
        "pass": status == PASS,
        "skipped": status == SKIP,
    }
    result.update(details)
    return result


def _required(result: dict, required: bool) -> dict:
    result["required"] = required
    return result


def _infer_profile(source: Path | None, project_dir: Path) -> str:
    """Infer the minimum applicable gate profile without silently dropping checks."""
    is_rtl = bool(source and source.suffix.lower() in {".v", ".sv", ".svh"})
    has_csynth = (project_dir / "solution1" / "syn" / "report" / "csynth.rpt").exists()
    if is_rtl and has_csynth:
        return "mixed"
    if is_rtl:
        return "rtl"
    if has_csynth:
        return "hls"
    return "rtl"


def check_lint(source: Path) -> dict:
    """1. Verilator lint for .v/.sv sources."""
    if not source or not source.exists():
        return _result(SKIP, reason="no source file")
    if source.suffix not in ('.v', '.sv', '.svh'):
        return _result(SKIP, reason=f"not a .v/.sv file: {source.suffix}")
    if not VERILATOR:
        return _result(ERROR, reason="verilator not found; set VERILATOR_BIN or add it to PATH")

    cmd = [
        VERILATOR,
        "--lint-only",
        "-Wall",
        "-Wno-fatal",
        "-Wno-DECLFILENAME",
        str(source),
    ]
    # verilator_bin.exe needs VERILATOR_ROOT to locate includes on Windows.
    env = verilator_environment(Path(VERILATOR))
    if VERILATOR_ROOT:
        env["VERILATOR_ROOT"] = VERILATOR_ROOT
    try:
        # Windows helper processes may inherit pipe handles. With PIPE,
        # communicate() can wait for EOF after the parent process exits.
        # Temporary files avoid this wait and pipe-buffer exhaustion.
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as output_file:
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=output_file,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
                env=env,
            )
            output_file.seek(0)
            output = output_file.read()
        errors = len(
            [
                line
                for line in output.splitlines()
                if line.startswith("%Error") and "Exiting due to" not in line
            ]
        )
        warnings = sum(1 for line in output.splitlines() if line.startswith("%Warning"))
        passed = result.returncode == 0 and errors <= THRESHOLDS["lint_errors"]
        return _result(
            PASS if passed else FAIL,
            tool="verilator",
            command=" ".join(cmd),
            errors=errors,
            warnings=warnings,
            exit_code=result.returncode,
            level="WARN" if passed and warnings else ("PASS" if passed else "FAIL"),
            output_tail=output[-1000:] if errors or warnings else "",
        )
    except FileNotFoundError:
        return _result(ERROR, reason=f"verilator not found at {VERILATOR}")
    except subprocess.TimeoutExpired:
        return _result(ERROR, reason="timeout (10s)")
    except Exception as e:
        return _result(ERROR, error=str(e))


def check_async_reg(source: Path) -> dict:
    """2. Static ASYNC_REG scan using scan_async_reg.py."""
    if not source or not source.exists():
        return _result(SKIP, reason="no source file")
    if source.suffix not in ('.v', '.sv', '.svh'):
        return _result(SKIP, reason=f"not a .v/.sv file: {source.suffix}")

    try:
        result = subprocess.run(
            [sys.executable, str(ASYNC_REG_SCAN), str(source)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return _result(
                ERROR,
                tool="scan_async_reg.py",
                exit_code=result.returncode,
                error=(result.stderr or result.stdout)[-1000:],
            )
        if result.stdout.strip():
            data = json.loads(result.stdout)
        else:
            data = {"count": 0, "missing": []}
        missing = data.get("count", 0)
        return _result(
            PASS if missing <= THRESHOLDS["async_reg_missing"] else FAIL,
            tool="scan_async_reg.py",
            missing=missing,
            items=data.get("missing", []),
        )
    except subprocess.TimeoutExpired:
        return _result(ERROR, reason="scan_async_reg timeout (10s)")
    except Exception as e:
        return _result(ERROR, error=str(e))


def check_readability(source: Path) -> dict:
    """RTL readability rules RTL-R001 through RTL-R010."""
    if not source or not source.exists():
        return _result(SKIP, reason="no source file")
    if source.suffix.lower() not in {".v", ".sv", ".svh"}:
        return _result(SKIP, reason=f"not an RTL file: {source.suffix}")
    try:
        report = analyze_rtl_readability(source, root=PROJECT_ROOT)
        level = "FAIL" if report["status"] == FAIL else (
            "WARN" if report["summary"]["warnings"] else "PASS"
        )
        return _result(
            report["status"],
            tool="rtl_readability.py",
            level=level,
            report=report,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        return _result(ERROR, reason=str(exc), tool="rtl_readability.py")


def check_csynth(project_dir: Path) -> dict:
    """3. HLS resource estimation; C synthesis must already have run.

    Vitis HLS 2024.2 csynth.rpt layout (single column, no availability column):
    | BRAM | DSP | FF |    LUT   | URAM|
    |   -  |  -  |  -| 41 (~0%)|  - |
    """
    rpt = project_dir / "solution1" / "syn" / "report" / "csynth.rpt"
    if not rpt.exists():
        return _result(
            SKIP,
            reason=f"csynth.rpt does not exist; run HLS csynth first: {rpt}",
        )

    try:
        content = rpt.read_text(encoding="utf-8", errors='ignore')

        def find_used(name):
            """Vitis HLS 2024.2 header: `| BRAM | DSP | FF | LUT | URAM|`.
            Data row: `|+ gain | ... | ... | - | - | - | 41 (~0%)| - |`.

            Locate the resource header and its column index, then find the
            following module data row and extract the corresponding cell.
            """
            # 1. Locate the header.
            header_pat = re.compile(r'\|\s*BRAM\s*\|\s*DSP\s*\|\s*FF\s*\|\s*LUT\s*\|\s*URAM\s*\|')
            header_m = header_pat.search(content)
            if not header_m:
                return None, None
            header_cols = [c.strip() for c in header_m.group(0).split('|') if c.strip()]
            if name not in header_cols:
                return None, None
            col_idx = header_cols.index(name)

            # 2. Find the next module row in the same report section.
            # DOTALL includes all cells before the row-ending newline.
            data_pat = re.compile(r'\|\+[^\n]+', re.MULTILINE)
            data_m = data_pat.search(content, header_m.end())
            if not data_m:
                return None, None
            data_line = data_m.group(0)
            # Split on pipes and use the resource column index.
            # The data row has a module prefix and additional non-resource cells.
            # Access the resource cells through the observed row offset.
            split_parts = data_line.split('|')
            # Data row: module | issue | slack | latency_cycles | latency_ns |
            #                  iter_latency | interval | trip_count | pipelined |
            #                  BRAM | DSP | FF | LUT | URAM|`
            # Nine non-resource columns precede the resource columns.
            # BRAM/DSP/FF/LUT/URAM start at split_parts[10].
            # Header BRAM index 0 corresponds to split_parts[10].
            # The offset is 10.
            RESOURCE_OFFSET = 10
            target_idx = col_idx + RESOURCE_OFFSET
            if target_idx >= len(split_parts):
                return None, None
            cell = split_parts[target_idx].strip()
            # Whitespace has already been stripped before this match.

            # 3. Parse cells such as `41 (~0%)`, `12 (5%)`, `12` or `-`.
            # The tilde in ~N% denotes an approximate percentage.
            m = re.match(r'(\d+)(?:\s*\(\s*~?([\d.]+)%\s*\))?', cell)
            if m:
                used = int(m.group(1))
                pct_val = float(m.group(2)) if m.group(2) else None
                return used, pct_val
            if cell == '-':
                return None, 0.0
            return None, None

        bram_used, bram_pct = find_used("BRAM")
        uram_used, uram_pct = find_used("URAM")
        dsp_used, dsp_pct = find_used("DSP")
        lut_used, lut_pct = find_used("LUT")
        ff_used, ff_pct = find_used("FF")

        result = {
            "tool": "csynth.rpt",
            "bram_used": bram_used, "bram_pct": bram_pct,
            "uram_used": uram_used, "uram_pct": uram_pct,
            "dsp_used": dsp_used, "dsp_pct": dsp_pct,
            "lut_used": lut_used, "lut_pct": lut_pct,
            "ff_used": ff_used, "ff_pct": ff_pct,
        }

        # BRAM utilization is a key resource-risk metric.
        if bram_pct is not None:
            if bram_pct > THRESHOLDS["bram_pct_csyn_fail"]:
                result["level"] = "FAIL"
                status = FAIL
            elif bram_pct > THRESHOLDS["bram_pct_csyn_warn"]:
                result["level"] = "WARN"
                status = PASS
            else:
                result["level"] = "PASS"
                status = PASS
        else:
            return _result(ERROR, reason="csynth.rpt exists but BRAM utilization cannot be parsed", **result)

        return _result(status, **result)
    except Exception as e:
        return _result(ERROR, error=str(e))


def _path_text(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _report_search_dirs(vivado_project: Path | None) -> list[Path]:
    if vivado_project is None:
        return []
    anchor = vivado_project.resolve(strict=False)
    start = anchor if anchor.is_dir() else anchor.parent
    directories: list[Path] = []
    seen: set[Path] = set()
    for base in (start, *start.parents):
        for candidate in (base, base / "impl", base / "reports", base / "reports" / "impl"):
            resolved = candidate.resolve(strict=False)
            if resolved not in seen:
                seen.add(resolved)
                directories.append(resolved)
        if base == PROJECT_ROOT:
            break
    return directories


def _find_vivado_report(vivado_project: Path | None, names: tuple[str, ...]) -> Path | None:
    for directory in _report_search_dirs(vivado_project):
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def check_timing(vivado_project: Path) -> dict:
    """4. Vivado report_timing_summary checks."""
    report = _find_vivado_report(
        vivado_project, ("impl_timing_summary.rpt", "timing_summary.rpt", "impl_timing.rpt")
    )
    if report is None:
        return _result(ERROR, reason="Vivado timing report not found", project=_path_text(vivado_project))
    try:
        verified = load_verified_report(report, root=PROJECT_ROOT, kind="timing_report")
        metrics = verified["metrics"]
        if not metrics["constraints_met"] or metrics["wns_ns"] < THRESHOLDS["wns_ns_fail"]:
            status, level = FAIL, "FAIL"
        elif metrics["wns_ns"] < THRESHOLDS["wns_ns_warn"]:
            status, level = PASS, "WARN"
        else:
            status, level = PASS, "PASS"
        return _result(status, level=level, evidence=verified)
    except (OSError, json.JSONDecodeError, EvidenceContractError, ReportParseError, ValueError) as exc:
        return _result(ERROR, reason=str(exc), report=str(report))


def check_cdc(vivado_project: Path) -> dict:
    """5. CDC topology from Vivado report_cdc."""
    report = _find_vivado_report(vivado_project, ("impl_cdc.rpt", "cdc.rpt"))
    if report is None:
        return _result(ERROR, reason="Vivado CDC report not found", project=_path_text(vivado_project))
    try:
        verified = load_verified_report(report, root=PROJECT_ROOT, kind="cdc_report")
        metrics = verified["metrics"]
        if metrics["critical"] > THRESHOLDS["cdc_critical"]:
            status, level = FAIL, "FAIL"
        elif metrics["warning"]:
            status, level = PASS, "WARN"
        else:
            status, level = PASS, "PASS"
        return _result(status, level=level, evidence=verified)
    except (OSError, json.JSONDecodeError, EvidenceContractError, ReportParseError, ValueError) as exc:
        return _result(ERROR, reason=str(exc), report=str(report))


def check_impl(vivado_project: Path) -> dict:
    """6. Implemented resource usage from Vivado impl_1."""
    report_names = {
        "timing": ("impl_timing_summary.rpt", "timing_summary.rpt", "impl_timing.rpt"),
        "cdc": ("impl_cdc.rpt", "cdc.rpt"),
        "utilization": ("impl_util.rpt", "utilization.rpt"),
        "drc": ("impl_drc.rpt", "drc.rpt"),
    }
    reports = {
        name: _find_vivado_report(vivado_project, candidates)
        for name, candidates in report_names.items()
    }
    missing = [name for name, path in reports.items() if path is None]
    if missing:
        return _result(
            ERROR,
            reason=f"required implementation reports not found: {missing}",
            project=_path_text(vivado_project),
        )
    try:
        timing = load_verified_report(reports["timing"], root=PROJECT_ROOT, kind="timing_report")
        cdc = load_verified_report(reports["cdc"], root=PROJECT_ROOT, kind="cdc_report")
        utilization = load_verified_report(
            reports["utilization"], root=PROJECT_ROOT, kind="utilization_report"
        )
        drc = load_verified_report(reports["drc"], root=PROJECT_ROOT, kind="drc_report")
    except (OSError, json.JSONDecodeError, EvidenceContractError, ReportParseError, ValueError) as exc:
        return _result(ERROR, reason=str(exc), reports={k: str(v) for k, v in reports.items()})

    blockers = []
    warnings = []
    if not timing["metrics"]["constraints_met"]:
        blockers.append("timing_constraints_not_met")
    if cdc["metrics"]["critical"]:
        blockers.append("critical_cdc")
    if drc["metrics"]["critical"] or drc["metrics"]["error"]:
        blockers.append("critical_drc")
    if utilization["metrics"].get("bram_pct", 0) > THRESHOLDS["bram_pct_csyn_fail"]:
        blockers.append("bram_over_budget")
    elif utilization["metrics"].get("bram_pct", 0) > THRESHOLDS["bram_pct_csyn_warn"]:
        warnings.append("bram_near_budget")
    if drc["metrics"]["warning"]:
        warnings.append("drc_warnings")
    if cdc["metrics"]["warning"]:
        warnings.append("cdc_warnings")

    status = FAIL if blockers else PASS
    level = "FAIL" if blockers else ("WARN" if warnings else "PASS")
    return _result(
        status,
        level=level,
        blockers=blockers,
        warnings=warnings,
        evidence={
            "timing": timing,
            "cdc": cdc,
            "utilization": utilization,
            "drc": drc,
        },
    )


def run_fast(source: Path) -> dict:
    """L1 sandbox: lint, ASYNC_REG and RTL readability."""
    return {
        "mode": "fast (L1 sandbox)",
        "timestamp": _now(),
        "source": str(source) if source else None,
        "checks": {
            "lint": _required(check_lint(source), True),
            "async_reg": _required(check_async_reg(source), True),
            "readability": _required(check_readability(source), True),
        }
    }


def run_full(
    source: Path,
    project_dir: Path,
    vivado_project: Path | None = None,
    profile: str = "auto",
) -> dict:
    """L2 checks: lint, ASYNC_REG, estimated resources, timing and CDC."""
    selected_profile = _infer_profile(source, project_dir) if profile == "auto" else profile
    if selected_profile not in {"rtl", "hls", "mixed"}:
        raise ValueError(f"unknown quality-gate profile: {selected_profile}")
    needs_rtl = selected_profile in {"rtl", "mixed"}
    needs_hls = selected_profile in {"hls", "mixed"}
    return {
        "mode": "full (L2 gate)",
        "profile": selected_profile,
        "timestamp": _now(),
        "source": str(source) if source else None,
        "project_dir": str(project_dir) if project_dir else None,
        "checks": {
            "lint": _required(check_lint(source), needs_rtl),
            "async_reg": _required(check_async_reg(source), needs_rtl),
            "readability": _required(check_readability(source), needs_rtl),
            "csynth": _required(check_csynth(project_dir), needs_hls),
            "timing": _required(check_timing(vivado_project), needs_rtl),
            "cdc": _required(check_cdc(vivado_project), needs_rtl),
        }
    }


def run_impl(vivado_project: Path) -> dict:
    """L2.6: implemented resource checks."""
    return {
        "mode": "impl (resource real layer)",
        "timestamp": _now(),
        "vivado_project": str(vivado_project),
        "checks": {
            "impl_1": _required(check_impl(vivado_project), True),
        }
    }


def summarize(result: dict) -> dict:
    """Summarize checks. Required SKIP/ERROR always fail closed."""
    checks = result.get("checks", {})
    total = len(checks)
    passed = sum(1 for c in checks.values() if c.get("status") == PASS)
    failed = sum(1 for c in checks.values() if c.get("status") == FAIL)
    skipped = sum(1 for c in checks.values() if c.get("status") == SKIP)
    errors = sum(1 for c in checks.values() if c.get("status") == ERROR)
    required_failures = [
        name
        for name, check in checks.items()
        if check.get("required", True) and check.get("status") != PASS
    ]
    advisory_issues = [
        name
        for name, check in checks.items()
        if not check.get("required", True) and check.get("status") in {FAIL, ERROR}
    ]
    warnings = [
        name
        for name, check in checks.items()
        if check.get("status") == PASS and check.get("level") == "WARN"
    ]

    if required_failures:
        overall = "FAIL"
    elif advisory_issues or warnings:
        overall = "WARN"
    else:
        overall = "PASS"

    result["summary"] = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
        "required_failures": required_failures,
        "advisory_issues": advisory_issues,
        "warnings": warnings,
        "overall": overall,
    }
    return result


def exit_code_for(result: dict) -> int:
    """WARN is advisory; FAIL, including required SKIP/ERROR, blocks."""
    return 1 if result["summary"]["overall"] == "FAIL" else 0


def write_report(result: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='Unified entry point for six quality checks')
    parser.add_argument(
        '--fast', action='store_true',
        help='L1 sandbox: lint, ASYNC_REG and RTL readability',
    )
    parser.add_argument('--impl', action='store_true', help='Implemented resource checks only')
    parser.add_argument('--source', '-s', help='Source file path (.v/.sv/.cpp)')
    parser.add_argument('--project', '-p', help='HLS project directory containing solution1/')
    parser.add_argument('--vivado-project', help='Vivado project path (.xpr)')
    parser.add_argument(
        '--profile', choices=['auto', 'rtl', 'hls', 'mixed'], default='auto',
        help='Applicable gate profile; auto infers it from the inputs',
    )
    parser.add_argument('--output', '-o', help='JSON report output path')
    args = parser.parse_args()

    source = Path(args.source).resolve() if args.source else None
    project_dir = Path(args.project).resolve() if args.project else PROJECT_ROOT

    if args.fast:
        result = run_fast(source)
    elif args.impl:
        vp = Path(args.vivado_project).resolve() if args.vivado_project else PROJECT_ROOT
        result = run_impl(vp)
    else:
        vivado_project = Path(args.vivado_project).resolve() if args.vivado_project else None
        result = run_full(source, project_dir, vivado_project, args.profile)

    result = summarize(result)

    if args.output:
        write_report(result, Path(args.output))
    else:
        default_report = REPORTS_DIR / f"qg_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        write_report(result, default_report)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    sys.exit(exit_code_for(result))


if __name__ == "__main__":
    main()
