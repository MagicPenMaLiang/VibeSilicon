#!/usr/bin/env python3
"""Deterministic RTL readability checks for VibeSilicon G1."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
RULESET_VERSION = 1
RTL_SUFFIXES = {".v", ".sv", ".svh"}
RULES = {
    "RTL-R001": ("ERROR", "Declare every net and enable `default_nettype none`."),
    "RTL-R002": ("ERROR", "Use an explicitly sized constant in arithmetic."),
    "RTL-R003": ("WARNING", "Cast operands to an explicit width and signedness."),
    "RTL-R004": ("ERROR", "Assign defaults or cover every combinational branch."),
    "RTL-R005": ("ERROR", "Use non-blocking assignments for sequential state."),
    "RTL-R006": ("ERROR", "Drive a register or net from exactly one process."),
    "RTL-R007": ("ERROR", "Add the VibeSilicon Module Contract v1 header."),
    "RTL-R008": ("WARNING", "Move payload, valid, ready and sideband as one stage."),
    "RTL-R009": ("ERROR", "Use an approved synchronizer, handshake or async FIFO."),
    "RTL-R010": ("ERROR", "Remove the attribute or reference an approved waiver."),
}
CONTRACT_FIELDS = (
    "Module",
    "Purpose",
    "Clocks",
    "Resets",
    "Interfaces",
    "Numeric",
    "Latency",
    "Throughput",
    "Invariants",
    "Generated",
)
WAIVER_RE = re.compile(
    r"vibesilicon-waive\s+(RTL-R\d{3})\s+id=([A-Z][A-Z0-9-]{2,63})(?:\s+reason=\S.*)?",
)
IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_$]*\b")
ASSIGNMENT_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_$]*)\s*(?:\[[^\]]+\]\s*)?(<=|(?<![<>=!])=(?!=))"
)
STAGE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_$]*?_s(\d+)(?:_[qd])?)\b")
DECLARATION_RE = re.compile(
    r"\b(?:input|output|inout|wire|reg|logic|bit|integer|parameter|localparam)\b"
)
KEYWORDS = {
    "input", "output", "inout", "wire", "reg", "logic", "bit", "integer",
    "parameter", "localparam", "signed", "unsigned", "module", "endmodule",
}


def _strip_comments(lines: list[str]) -> list[str]:
    result: list[str] = []
    in_block = False
    for raw in lines:
        output: list[str] = []
        index = 0
        while index < len(raw):
            if in_block:
                end = raw.find("*/", index)
                if end < 0:
                    index = len(raw)
                    continue
                in_block = False
                index = end + 2
                continue
            if raw.startswith("//", index):
                break
            if raw.startswith("/*", index):
                in_block = True
                index += 2
                continue
            output.append(raw[index])
            index += 1
        result.append("".join(output))
    return result


def _waiver(lines: list[str], rule_id: str, line: int) -> str | None:
    for candidate in (line, line - 1):
        if candidate < 1 or candidate > len(lines):
            continue
        match = WAIVER_RE.search(lines[candidate - 1])
        if match and match.group(1).upper() == rule_id:
            return match.group(2).upper()
    return None


def _violation(
    lines: list[str], rule_id: str, source: str, line: int, evidence: str, suggestion: str | None = None
) -> dict[str, Any]:
    severity, default_suggestion = RULES[rule_id]
    waiver_id = _waiver(lines, rule_id, line)
    return {
        "rule_id": rule_id,
        "severity": severity,
        "file": source,
        "line": line,
        "evidence": evidence.strip()[:500],
        "suggestion": suggestion or default_suggestion,
        "waiver_id": waiver_id,
        "waived": waiver_id is not None,
    }


def _declarations(code: list[str]) -> tuple[set[str], set[str], set[str]]:
    declared: set[str] = set()
    signed: set[str] = set()
    unsigned: set[str] = set()
    for line in code:
        if not DECLARATION_RE.search(line):
            continue
        identifiers = [name for name in IDENTIFIER_RE.findall(line) if name not in KEYWORDS]
        # Drop range literals and type/package qualifiers by retaining identifiers
        # after the declaration keywords. False negatives fail open; findings never
        # claim a signal that was not present on the declaration line.
        for name in identifiers:
            if name.lower() in {"true", "false"}:
                continue
            declared.add(name)
            (signed if re.search(r"\bsigned\b", line) else unsigned).add(name)
    return declared, signed, unsigned


def _always_blocks(code: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    index = 0
    while index < len(code):
        line = code[index]
        start_match = re.search(r"\balways_(ff|comb|latch)\b|\balways\s*@", line)
        if not start_match:
            index += 1
            continue
        if "always_comb" in line:
            kind = "comb"
        elif "always_latch" in line:
            kind = "latch"
        elif "always_ff" in line or re.search(r"\b(?:posedge|negedge)\b", line):
            kind = "seq"
        else:
            kind = "comb"
        depth = len(re.findall(r"\bbegin\b", line)) - len(re.findall(r"\bend\b", line))
        end = index
        if depth > 0:
            end += 1
            while end < len(code):
                depth += len(re.findall(r"\bbegin\b", code[end]))
                depth -= len(re.findall(r"\bend\b", code[end]))
                if depth <= 0:
                    break
                end += 1
        clock_match = re.search(r"\b(?:posedge|negedge)\s+([A-Za-z_]\w*)", line)
        blocks.append(
            {
                "kind": kind,
                "start": index + 1,
                "end": min(end + 1, len(code)),
                "clock": clock_match.group(1) if clock_match else None,
            }
        )
        index = max(index + 1, end + 1)
    return blocks


def _block_assignments(code: list[str], block: dict[str, Any]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for line_number in range(block["start"], block["end"] + 1):
        for match in ASSIGNMENT_RE.finditer(_without_for_control(code[line_number - 1])):
            result.setdefault(match.group(1), []).append(line_number)
    return result


def _block_read_sites(
    code: list[str], block: dict[str, Any]
) -> list[tuple[str, set[str], int]]:
    sites: list[tuple[str, set[str], int]] = []
    for line_number in range(block["start"], block["end"] + 1):
        line = _without_for_control(code[line_number - 1])
        for statement in line.split(";"):
            match = ASSIGNMENT_RE.search(statement)
            if not match:
                continue
            rhs = statement[match.end():]
            sites.append((match.group(1), set(IDENTIFIER_RE.findall(rhs)), line_number))
    return sites


def _has_contract(
    raw_lines: list[str], module_line: int, lower_bound: int = 0
) -> tuple[bool, list[str]]:
    header = "\n".join(raw_lines[lower_bound: max(lower_bound, module_line - 1)])
    marker = "VibeSilicon Module Contract v1" in header
    missing: list[str] = []
    for field in CONTRACT_FIELDS:
        match = re.search(rf"\b{field}\s*:\s*(.+)", header)
        if not match or not match.group(1).strip() or "<" in match.group(1) or ">" in match.group(1):
            missing.append(field)
    return marker and not missing, missing if marker else list(CONTRACT_FIELDS)


def _without_for_control(line: str) -> str:
    """Remove a simple for-loop control clause but preserve its hardware body."""
    match = re.search(r"\bfor\s*\(", line)
    if not match:
        return line
    depth = 0
    for index in range(match.end() - 1, len(line)):
        if line[index] == "(":
            depth += 1
        elif line[index] == ")":
            depth -= 1
            if depth == 0:
                return line[: match.start()] + line[index + 1:]
    return line


def analyze(source_path: Path, *, root: Path | None = None) -> dict[str, Any]:
    path = source_path.resolve(strict=True)
    if path.suffix.lower() not in RTL_SUFFIXES:
        raise ValueError(f"RTL readability only accepts {sorted(RTL_SUFFIXES)}: {path}")
    project_root = root.resolve(strict=True) if root else path.parent
    try:
        source = path.relative_to(project_root).as_posix()
    except ValueError:
        source = str(path)
    text = path.read_text(encoding="utf-8", errors="strict")
    raw_lines = text.splitlines()
    code = _strip_comments(raw_lines)
    declared, signed, unsigned = _declarations(code)
    blocks = _always_blocks(code)
    violations: list[dict[str, Any]] = []

    module_lines = [index for index, line in enumerate(code, 1) if re.search(r"^\s*module\b", line)]
    first_module = module_lines[0] if module_lines else 1

    # RTL-R001: guard against and detect simple implicit continuous-assignment nets.
    has_nettype_none = any("`default_nettype none" in line for line in code)
    if not has_nettype_none:
        violations.append(
            _violation(raw_lines, "RTL-R001", source, first_module, "missing `default_nettype none`")
        )
    else:
        nonempty = [(number, line) for number, line in enumerate(code, 1) if line.strip()]
        if nonempty and "`default_nettype wire" not in nonempty[-1][1]:
            number, line = nonempty[-1]
            violations.append(
                _violation(
                    raw_lines,
                    "RTL-R001",
                    source,
                    number,
                    f"file does not restore `default_nettype wire` after: {line.strip()}",
                )
            )
    for number, line in enumerate(code, 1):
        match = re.search(r"^\s*assign\s+([A-Za-z_]\w*)\b", line)
        if match and match.group(1) not in declared:
            violations.append(
                _violation(raw_lines, "RTL-R001", source, number, raw_lines[number - 1])
            )

    # RTL-R002: arithmetic with a decimal literal that is not Verilog-sized.
    unsized = r"(?<![A-Za-z0-9_$'])\d+\b(?!\s*')"
    arithmetic = re.compile(
        rf"(?:\+|-|\*|/|%|<<|>>)\s*{unsized}|{unsized}\s*(?:\+|-|\*|/|%|<<|>>)"
    )
    for number, line in enumerate(code, 1):
        if arithmetic.search(_without_for_control(line)):
            violations.append(_violation(raw_lines, "RTL-R002", source, number, raw_lines[number - 1]))

    # RTL-R003: expressions that visibly mix declared signed and unsigned operands.
    for number, line in enumerate(code, 1):
        if not re.search(r"(?:\+|-|\*|/|%|<<|>>|<=|>=)", line):
            continue
        names = set(IDENTIFIER_RE.findall(line))
        if names & signed and names & unsigned:
            violations.append(_violation(raw_lines, "RTL-R003", source, number, raw_lines[number - 1]))

    assignments_by_block = [_block_assignments(code, block) for block in blocks]

    # RTL-R004: incomplete always_comb control without a prior default assignment.
    for block, assignments in zip(blocks, assignments_by_block):
        if block["kind"] != "comb":
            continue
        block_text = "\n".join(code[block["start"] - 1:block["end"]])
        controls: list[tuple[int, str]] = []
        for offset, line in enumerate(code[block["start"] - 1:block["end"]], block["start"]):
            if re.search(r"\bif\s*\(", line) and not re.search(r"\belse\b", block_text):
                controls.append((offset, "if without else"))
            if re.search(r"\bcase[xz]?\s*\(", line) and not re.search(r"\bdefault\s*:", block_text):
                controls.append((offset, "case without default"))
        if controls:
            first_control, evidence = controls[0]
            missing_default = [
                name for name, lines in assignments.items() if not any(line < first_control for line in lines)
            ]
            if missing_default:
                violations.append(
                    _violation(
                        raw_lines,
                        "RTL-R004",
                        source,
                        first_control,
                        f"{evidence}; no default for {', '.join(sorted(missing_default))}",
                    )
                )

    # RTL-R005: blocking state assignment in a sequential process (loop indices exempt).
    for block in blocks:
        if block["kind"] != "seq":
            continue
        for number in range(block["start"], block["end"] + 1):
            line = _without_for_control(code[number - 1])
            for match in ASSIGNMENT_RE.finditer(line):
                if match.group(2) == "=":
                    violations.append(
                        _violation(raw_lines, "RTL-R005", source, number, raw_lines[number - 1])
                    )

    # RTL-R006: one signal assigned from more than one procedural block.
    drivers: dict[str, list[tuple[int, int]]] = {}
    loop_variables = {
        match.group(1)
        for line in code
        for match in [re.search(r"\bfor\s*\(\s*([A-Za-z_]\w*)\s*=", line)]
        if match
    }
    for block_index, (block, assignments) in enumerate(zip(blocks, assignments_by_block)):
        for name, lines in assignments.items():
            if name in loop_variables:
                continue
            drivers.setdefault(name, []).append((block_index, lines[0]))
    for name, items in drivers.items():
        unique_blocks = {block_index for block_index, _ in items}
        if len(unique_blocks) > 1:
            line = sorted(items, key=lambda item: item[1])[1][1]
            violations.append(
                _violation(raw_lines, "RTL-R006", source, line, f"{name} is assigned in multiple processes")
            )

    # RTL-R007: required module contract fields before each module.
    for module_line in module_lines:
        prior_endmodules = [
            number for number, line in enumerate(code[: module_line - 1], 1)
            if re.search(r"^\s*endmodule\b", line)
        ]
        lower_bound = prior_endmodules[-1] if prior_endmodules else 0
        contract_ok, missing = _has_contract(raw_lines, module_line, lower_bound)
        if not contract_ok:
            violations.append(
                _violation(
                    raw_lines,
                    "RTL-R007",
                    source,
                    module_line,
                    "missing contract fields: " + ", ".join(missing),
                )
            )

    # RTL-R008: valid/ready and payload using inconsistent explicit stage tags.
    for number, line in enumerate(code, 1):
        stages = [(name, int(stage)) for name, stage in STAGE_RE.findall(line)]
        if len(stages) < 2:
            continue
        stage_values = {stage for _, stage in stages}
        control = any("valid" in name.lower() or "ready" in name.lower() for name, _ in stages)
        if len(stage_values) > 1 and (control or max(stage_values) - min(stage_values) > 1):
            violations.append(_violation(raw_lines, "RTL-R008", source, number, raw_lines[number - 1]))

    # RTL-R009: direct procedural read from a signal driven in another clock domain.
    signal_clocks: dict[str, set[str]] = {}
    for block, assignments in zip(blocks, assignments_by_block):
        if block["kind"] != "seq" or not block["clock"]:
            continue
        for name, lines in assignments.items():
            signal_clocks.setdefault(name, set()).add(block["clock"])
    async_reg_names: set[str] = set()
    for line in code:
        if "ASYNC_REG" in line:
            async_reg_names.update(IDENTIFIER_RE.findall(line))
    reported_cdc: set[tuple[str, str]] = set()
    for block in blocks:
        destination_clock = block.get("clock")
        if block["kind"] != "seq" or not destination_clock:
            continue
        for destination, reads, line_number in _block_read_sites(code, block):
            if destination in async_reg_names:
                continue
            for name in reads:
                source_clocks = signal_clocks.get(name, set())
                for source_clock in source_clocks:
                    key = (name, destination_clock)
                    if source_clock != destination_clock and key not in reported_cdc:
                        reported_cdc.add(key)
                        violations.append(
                            _violation(
                                raw_lines,
                                "RTL-R009",
                                source,
                                line_number,
                                f"{name} crosses from {source_clock} to {destination_clock} without an approved pattern",
                            )
                        )

    # RTL-R010: synthesis/debug preservation attributes require an explicit waiver.
    for number, line in enumerate(code, 1):
        if re.search(r"\(\*.*\b(?:KEEP|DONT_TOUCH|MARK_DEBUG)\b.*\*\)", line, re.IGNORECASE):
            violations.append(_violation(raw_lines, "RTL-R010", source, number, raw_lines[number - 1]))

    violations.sort(key=lambda item: (item["line"], item["rule_id"], item["evidence"]))
    blocking = sum(
        1 for item in violations if item["severity"] == "ERROR" and not item["waived"]
    )
    warnings = sum(
        1 for item in violations if item["severity"] == "WARNING" and not item["waived"]
    )
    waived = sum(1 for item in violations if item["waived"])
    return {
        "schema_version": SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "status": "FAIL" if blocking else "PASS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "summary": {
            "violations": len(violations),
            "blocking": blocking,
            "warnings": warnings,
            "waived": waived,
        },
        "violations": violations,
    }


def write_report(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("rtl_readability.json"))
    args = parser.parse_args(argv)
    try:
        report = analyze(args.source, root=args.root)
        write_report(report, args.output)
    except (OSError, UnicodeError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
