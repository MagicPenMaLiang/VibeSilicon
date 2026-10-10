#!/usr/bin/env python3
"""
scan_async_reg.py: Heuristic ASYNC_REG scan for Verilog/SystemVerilog registers.

Static scan contract:
- Zero missing attributes is scan PASS; a nonzero count is scan FAIL.
- JSON output: {"missing": [...], "count": N, "pass": bool}.

Detection heuristic:
1. Find edge-triggered always blocks.
2. Find registers assigned in more than one clock domain.
3. Check for the (* ASYNC_REG = "TRUE" *) attribute.
4. Report the location of each missing attribute.

Known limits; scan PASS does not establish CDC correctness:
- A register sampling an external input is not identified as a crossing.
  Example: always @(posedge clk_b) sync_d1 <= data_a; is not flagged.
  Review the crossing with implementation CDC reports and protocol evidence.
- Complex hierarchical crossings and multi-bit buses need dedicated analysis.

Use this scan for L1 feedback; applicable L2 CDC checks require source-bound CDC evidence.
"""

import argparse
import json
import re
import sys
from pathlib import Path


ALWAYS_RE = re.compile(
    r'always\s+@\s*\(\s*(?:posedge|negedge)\s+(\w+)[^)]*\)',
    re.MULTILINE,
)

REG_RE = re.compile(r'\breg\s+(?:\[[^\]]+\]\s+)?(\w+)\s*[;,)\]]', re.MULTILINE)

# Match assignment targets in always blocks, such as sync_d1 <= ... or sync_d1 = ... .
ASSIGN_LHS_RE = re.compile(r'\b(\w+)\s*(?:<=|=)\s*[^=]', re.MULTILINE)

ASYNC_REG_ATTR_RE = re.compile(
    r'\(\*\s*ASYNC_REG\s*=\s*"TRUE"\s*\*\)',
    re.IGNORECASE,
)

RESET_KEYWORDS = {"rst_n", "rst", "reset", "reset_n", "rstn", "arst_n"}


def extract_clk_to_regs(content: str) -> dict[str, set[str]]:
    """Extract the registers assigned within each clock domain.

    For an always block with clock and reset edges, use the first matched
    edge signal as the clock and exclude recognized reset signals."""
    result: dict[str, set[str]] = {}
    for match in ALWAYS_RE.finditer(content):
        clk = match.group(1)
        if clk in RESET_KEYWORDS or clk.startswith("arst") or clk.startswith("rst"):
            continue
        block_start = match.end()
        block_end = content.find('\nend', block_start)
        if block_end == -1:
            block_end = len(content)
        block = content[block_start:block_end]
        # Collect both register declarations and assignment targets.
        declared = set(REG_RE.findall(block))
        assigned = set(ASSIGN_LHS_RE.findall(block))
        result.setdefault(clk, set()).update(declared | assigned)
    return result


def extract_async_marked_regs(content: str) -> set[str]:
    """Extract registers carrying ASYNC_REG near their declaration."""
    marked = set()
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if ASYNC_REG_ATTR_RE.search(line):
            window = '\n'.join(lines[i:i + 3])
            for m in REG_RE.finditer(window):
                marked.add(m.group(1))
    return marked


def find_cross_domain_regs(clk_to_regs: dict[str, set[str]]) -> set[str]:
    """Return registers assigned in more than one clock domain."""
    reg_to_clks: dict[str, list[str]] = {}
    for clk, regs in clk_to_regs.items():
        for r in regs:
            reg_to_clks.setdefault(r, []).append(clk)
    return {r for r, clks in reg_to_clks.items() if len(clks) > 1}


def scan_file(filepath: Path) -> list[dict]:
    try:
        content = filepath.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return []

    async_marked = extract_async_marked_regs(content)
    clk_to_regs = extract_clk_to_regs(content)
    cross_domain = find_cross_domain_regs(clk_to_regs)

    missing: list[dict] = []
    if not cross_domain:
        return missing

    for reg in sorted(cross_domain):
        if reg in async_marked:
            continue
        # Find the first declaration location.
        for line_num, line in enumerate(content.split('\n'), 1):
            if re.search(rf'\breg\s+(?:\[[^\]]+\]\s+)?{re.escape(reg)}\b', line):
                missing.append({
                    "file": str(filepath),
                    "line": line_num,
                    "signal": reg,
                    "snippet": line.strip()[:80],
                })
                break
    return missing


def scan(paths: list[Path]) -> dict:
    """Scan .v/.sv paths and return the JSON report."""
    all_missing: list[dict] = []
    files_scanned = 0
    suffixes = {'.v', '.sv', '.svh'}

    targets: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix in suffixes:
            targets.append(p)
        elif p.is_dir():
            for ext in suffixes:
                targets.extend(p.rglob(f'*{ext}'))

    for f in targets:
        files_scanned += 1
        all_missing.extend(scan_file(f))

    return {
        "missing": all_missing,
        "count": len(all_missing),
        "files_scanned": files_scanned,
        "pass": len(all_missing) == 0,
    }


def main():
    parser = argparse.ArgumentParser(description='Scan cross-domain registers for ASYNC_REG attributes')
    parser.add_argument('paths', nargs='+', help='File or directory paths')
    parser.add_argument('--output', '-o', help='Output JSON file path')
    args = parser.parse_args()

    paths = [Path(p) for p in args.paths]
    result = scan(paths)

    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(output, encoding='utf-8')
    print(output)

    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
