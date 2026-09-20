#!/usr/bin/env python3
"""
scan_async_reg.py: 扫描 Verilog/SV 中跨时钟域 reg 是否标注 ASYNC_REG

按计划 §6.5.1 ② ASYNC_REG 静态扫描
- 阈值：未标注数 = 0 PASS；> 0 FAIL（计划 §11.2 ② 命令 + 机器判据）
- 输出 JSON：{"missing": [...], "count": N, "pass": bool}

检测逻辑（启发式）：
1. 找所有 `always @(posedge clkX)` 块
2. 找跨 clk 域赋值的 reg（同一 reg 在多个 clk 域被赋值）
3. 检查每个跨域 reg 是否有 (* ASYNC_REG = "TRUE" *) 属性
4. 缺失则报告位置

已知边界（已知漏检模式，formal L2 兜底）：
- **wire input 跨 clk 域**：reg 从外部输入采样（如 2-FF 同步器），不会被标记
  - 例：`always @(posedge clk_b) sync_d1 <= data_a;` → 当前不报警
  - 兜底：Phase 1 用 Vivado report_cdc 做 formal 检查（Tier 5 延后实现）
- 复杂 hierarchical CDC / 多 bit 总线 → 同样兜底 Vivado report_cdc

L1 沙箱用此脚本提供 fast feedback；L2 Quality Gate ⑤ 必须由 vivado-mcp 调用 report_cdc 兜底。
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

# 匹配 always 块内的赋值目标（LHS），如 `sync_d1 <= ...` 或 `sync_d1 = ...`
ASSIGN_LHS_RE = re.compile(r'\b(\w+)\s*(?:<=|=)\s*[^=]', re.MULTILINE)

ASYNC_REG_ATTR_RE = re.compile(
    r'\(\*\s*ASYNC_REG\s*=\s*"TRUE"\s*\*\)',
    re.IGNORECASE,
)

RESET_KEYWORDS = {"rst_n", "rst", "reset", "reset_n", "rstn", "arst_n"}


def extract_clk_to_regs(content: str) -> dict[str, set[str]]:
    """解析每个 clk 域中赋值的 reg 集合。

    always 块可能有 posedge clk + negedge rst_n 组合，提取第一个
    posedge/negedge 后的 clk（不复位信号）。"""
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
        # 同时捕获 reg 声明（reg X;）和赋值目标（X <= Y / X = Y）
        declared = set(REG_RE.findall(block))
        assigned = set(ASSIGN_LHS_RE.findall(block))
        result.setdefault(clk, set()).update(declared | assigned)
    return result


def extract_async_marked_regs(content: str) -> set[str]:
    """提取所有带 ASYNC_REG 属性的 reg 名（同一行或下行声明）。"""
    marked = set()
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if ASYNC_REG_ATTR_RE.search(line):
            window = '\n'.join(lines[i:i + 3])
            for m in REG_RE.finditer(window):
                marked.add(m.group(1))
    return marked


def find_cross_domain_regs(clk_to_regs: dict[str, set[str]]) -> set[str]:
    """返回被多个 clk 域赋值的 reg 集合。"""
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
        # 找第一个声明位置
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
    """扫描路径列表中所有 .v/.sv 文件，返回 JSON 报告。"""
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
    parser = argparse.ArgumentParser(description='扫描跨时钟域 reg 的 ASYNC_REG 标注')
    parser.add_argument('paths', nargs='+', help='文件或目录路径')
    parser.add_argument('--output', '-o', help='输出 JSON 文件路径')
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