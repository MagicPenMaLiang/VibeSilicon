"""Compare a reviewed manifest with a deliberately narrow Vivado Tcl source list.

This static G0 check never executes Tcl or claims that Vivado synthesis passed.
Unsupported source-list syntax blocks instead of being guessed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from scripts.quality_gate.rtl_manifest import ManifestError, _bounded_path, validate_manifest


ROOT = Path(__file__).resolve().parents[2]
LIST_BLOCK = re.compile(r"(?ms)^\s*add_files\s+\[list\s*\\\s*\n(.*?)^\s*\]\s*$")
SOURCE_LINE = re.compile(r"\s*\$RTL_DIR/([A-Za-z0-9_./-]+\.(?:v|sv))\s*\\?\s*\Z")
TOP_LINE = re.compile(r"(?m)^\s*set_property\s+top\s+([A-Za-z_][A-Za-z0-9_$]*)\s+\[current_fileset\]\s*$")
RTL_DIR_LINE = re.compile(r'(?m)^\s*set\s+RTL_DIR\s+"([^"\r\n]+)"\s*$')
CLOCK_LINE = re.compile(
    r'(?m)^\s*puts\s+\$fh\s+"create_clock\s+-name\s+([A-Za-z_][A-Za-z0-9_$]*)'
    r'\s+-period\s+([0-9]+(?:\.[0-9]+)?)\s+\[get_ports\s+([A-Za-z_][A-Za-z0-9_$]*)\]"\s*$'
)


def check_parity(manifest_path: Path, tcl_path: str, *, repository_root: Path = ROOT) -> dict:
    root = repository_root.resolve(strict=True)
    manifest = validate_manifest(manifest_path, repository_root=repository_root)
    tcl = _bounded_path(root, tcl_path, kind="Vivado Tcl")
    project = _bounded_path(root, manifest["project_root"], kind="project_root")
    if not tcl.is_file() or tcl.suffix.lower() != ".tcl" or not tcl.is_relative_to(project):
        raise ManifestError("Vivado Tcl must be a project-local .tcl file")
    raw = tcl.read_bytes()
    try:
        content = raw.decode("utf-8")
    except UnicodeError as exc:
        raise ManifestError("Vivado Tcl must be UTF-8") from exc
    active = "\n".join(line for line in content.splitlines() if not line.lstrip().startswith("#"))
    blocks = list(LIST_BLOCK.finditer(active))
    if len(blocks) != 1:
        raise ManifestError("expected exactly one literal add_files [list] block")
    remainder = active[:blocks[0].start()] + active[blocks[0].end():]
    other_additions = re.findall(r"(?m)^\s*add_files\b[^\n]*$", remainder)
    if [line.strip() for line in other_additions] != ["add_files -fileset constrs_1 $XDC_FILE"]:
        raise ManifestError("unsupported additional add_files command")
    if len(manifest["source_roots"]) != 1:
        raise ManifestError("Tcl parity requires one source_root")
    source_root = manifest["source_roots"][0]
    rtl_dirs = RTL_DIR_LINE.findall(active)
    if len(rtl_dirs) != 1 or not rtl_dirs[0].replace("\\", "/").rstrip("/").endswith("/" + source_root):
        raise ManifestError("RTL_DIR does not identify manifest source_root")
    sources = []
    for line in blocks[0].group(1).splitlines():
        if not line.strip():
            continue
        match = SOURCE_LINE.fullmatch(line)
        if not match or ".." in match.group(1).split("/"):
            raise ManifestError("unsupported or unsafe Tcl source entry")
        sources.append(source_root + "/" + match.group(1))
    if len(sources) != len(set(sources)) or set(sources) != set(manifest["sources"]):
        raise ManifestError("Tcl source list differs from manifest selected sources")
    tops = TOP_LINE.findall(active)
    if tops != [manifest["top"]] or len(re.findall(r"(?m)^\s*set_property\s+top\b", active)) != 1:
        raise ManifestError("Tcl top differs from manifest top")
    unescaped = active.replace("\\[", "[").replace("\\]", "]")
    clocks = CLOCK_LINE.findall(unescaped)
    if len(clocks) != len(manifest["clocks"]) or len(re.findall(r"\bcreate_clock\b", active)) != len(clocks) or {port for _, _, port in clocks} != set(manifest["clocks"]):
        raise ManifestError("Tcl clocks differ from manifest clocks")
    if any(name != port for name, _, port in clocks) or len({port for _, _, port in clocks}) != len(clocks):
        raise ManifestError("Tcl clock names or ports are ambiguous")
    try:
        if any(Decimal(period) <= 0 for _, period, _ in clocks):
            raise ManifestError("Tcl clock period must be positive")
    except InvalidOperation as exc:
        raise ManifestError("invalid Tcl clock period") from exc
    if tcl.read_bytes() != raw:
        raise ManifestError("Vivado Tcl changed during parity check")
    return {
        "status": "PASS",
        "gate": "G0_TCL_MANIFEST_PARITY",
        "top": manifest["top"],
        "selected_source_count": len(sources),
        "tcl_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "clock_period_ns": dict(sorted((port, period) for _, period, port in clocks)),
        "limitations": ["static literal Tcl subset only", "Vivado Tcl was not executed", "not synthesis or timing signoff"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("tcl", help="repository-relative Vivado Tcl")
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        report = check_parity(args.manifest, args.tcl, repository_root=args.repository_root)
    except (ManifestError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "gate": "G0_TCL_MANIFEST_PARITY", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
