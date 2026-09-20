#!/usr/bin/env python3
"""Deterministic SPI Mode 0 and AXI-Stream trace assertions for VibeSilicon G2."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
RULESET_VERSION = 1
MAX_TRACE_BYTES = 64 * 1024 * 1024
MAX_SAMPLES = 1_000_000
PASS = "PASS"
FAIL = "FAIL"


class ProtocolTraceError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(root: Path, raw: Path, *, must_exist: bool) -> Path:
    candidate = raw if raw.is_absolute() else root / raw
    path = candidate.resolve(strict=must_exist)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ProtocolTraceError(f"path is outside project root: {path}") from exc
    if must_exist and (not path.is_file() or path.is_symlink()):
        raise ProtocolTraceError(f"trace must be a regular non-symlink file: {path}")
    return path


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ProtocolTraceError(f"{label} must be an integer >= {minimum}")
    return value


def _bit(value: Any, label: str) -> int:
    if value not in (0, 1) or isinstance(value, bool):
        raise ProtocolTraceError(f"{label} must be 0 or 1")
    return int(value)


def _finding(rule_id: str, cycle: int, message: str, evidence: str) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": "ERROR",
        "cycle": cycle,
        "message": message,
        "evidence": evidence,
    }


def _validate_trace(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "trace_id", "producer", "protocol", "config", "samples"}
    if set(value) != required:
        raise ProtocolTraceError(
            "trace requires exactly schema_version/trace_id/producer/protocol/config/samples"
        )
    if value["schema_version"] != SCHEMA_VERSION:
        raise ProtocolTraceError("unsupported trace schema_version")
    if not isinstance(value["trace_id"], str) or not value["trace_id"].strip():
        raise ProtocolTraceError("trace_id must be non-empty")
    if not isinstance(value["producer"], str) or value["producer"] not in {
        "curated-fixture", "cocotb", "verilator", "ila"
    }:
        raise ProtocolTraceError("producer must be curated-fixture/cocotb/verilator/ila")
    protocol = value["protocol"]
    if not isinstance(protocol, str) or protocol not in {"spi-mode0", "axi-stream"}:
        raise ProtocolTraceError(f"unsupported protocol: {protocol}")
    if not isinstance(value["config"], Mapping):
        raise ProtocolTraceError("config must be an object")
    if not isinstance(value["samples"], list) or len(value["samples"]) < 2:
        raise ProtocolTraceError("samples must contain at least two entries")
    if len(value["samples"]) > MAX_SAMPLES:
        raise ProtocolTraceError(f"samples exceed limit of {MAX_SAMPLES}")
    expected_signals = (
        {"cs_n", "sck", "mosi", "miso"}
        if protocol == "spi-mode0"
        else {"reset_n", "tvalid", "tready", "tdata", "tlast"}
    )
    previous_cycle = -1
    normalized_samples = []
    for index, sample in enumerate(value["samples"]):
        if not isinstance(sample, Mapping) or set(sample) != {"cycle", "signals"}:
            raise ProtocolTraceError(f"sample {index} requires exactly cycle/signals")
        cycle = _integer(sample["cycle"], f"sample {index} cycle")
        if cycle <= previous_cycle:
            raise ProtocolTraceError("sample cycles must be strictly increasing")
        previous_cycle = cycle
        signals = sample["signals"]
        if not isinstance(signals, Mapping) or set(signals) != expected_signals:
            raise ProtocolTraceError(f"sample {index} signals must be {sorted(expected_signals)}")
        normalized = dict(signals)
        for name in expected_signals - {"tdata"}:
            normalized[name] = _bit(signals[name], f"sample {index} {name}")
        if protocol == "axi-stream":
            normalized["tdata"] = _integer(signals["tdata"], f"sample {index} tdata")
        normalized_samples.append({"cycle": cycle, "signals": normalized})
    return {
        "schema_version": SCHEMA_VERSION,
        "trace_id": value["trace_id"],
        "producer": value["producer"],
        "protocol": protocol,
        "config": dict(value["config"]),
        "samples": normalized_samples,
    }


def _assert_spi(trace: Mapping[str, Any]) -> list[dict[str, Any]]:
    config = trace["config"]
    allowed = {"bit_order", "expected_mosi_bytes", "expected_miso_bytes", "max_edge_gap_cycles"}
    if set(config) != allowed:
        raise ProtocolTraceError(f"SPI config must contain exactly {sorted(allowed)}")
    if not isinstance(config["bit_order"], str) or config["bit_order"] not in {
        "msb-first", "lsb-first"
    }:
        raise ProtocolTraceError("SPI bit_order must be msb-first or lsb-first")
    expected_mosi = config["expected_mosi_bytes"]
    expected_miso = config["expected_miso_bytes"]
    for name, expected in (("MOSI", expected_mosi), ("MISO", expected_miso)):
        if not isinstance(expected, list) or not all(
            isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 255
            for item in expected
        ):
            raise ProtocolTraceError(f"SPI expected_{name.lower()}_bytes must be a byte list")
    max_gap = _integer(config["max_edge_gap_cycles"], "SPI max_edge_gap_cycles", minimum=1)
    findings: list[dict[str, Any]] = []
    samples = trace["samples"]
    active_bits: list[int] = []
    active_miso_bits: list[int] = []
    transaction_bits = 0
    observed_bytes: list[int] = []
    observed_miso_bytes: list[int] = []
    previous = samples[0]
    last_edge_cycle: int | None = None
    for sample in samples:
        cycle = sample["cycle"]
        signals = sample["signals"]
        if signals["cs_n"] == 1 and signals["sck"] != 0:
            findings.append(_finding("SPI-P001", cycle, "SCK is not idle-low while CS is high", "cs_n=1 sck=1"))
        was_active = previous["signals"]["cs_n"] == 0
        is_active = signals["cs_n"] == 0
        if not was_active and is_active:
            transaction_bits = 0
        edge = signals["sck"] != previous["signals"]["sck"]
        if is_active and edge:
            if last_edge_cycle is not None and cycle - last_edge_cycle > max_gap:
                findings.append(
                    _finding("SPI-P004", cycle, "SPI edge timeout", f"gap={cycle - last_edge_cycle} max={max_gap}")
                )
            last_edge_cycle = cycle
        if is_active and previous["signals"]["sck"] == 0 and signals["sck"] == 1:
            active_bits.append(signals["mosi"])
            active_miso_bits.append(signals["miso"])
            transaction_bits += 1
            if len(active_bits) % 8 == 0:
                bits = active_bits[-8:]
                ordered = bits if config["bit_order"] == "msb-first" else list(reversed(bits))
                observed_bytes.append(int("".join(str(bit) for bit in ordered), 2))
                miso_bits = active_miso_bits[-8:]
                ordered_miso = (
                    miso_bits if config["bit_order"] == "msb-first" else list(reversed(miso_bits))
                )
                observed_miso_bytes.append(int("".join(str(bit) for bit in ordered_miso), 2))
        if was_active and not is_active:
            if transaction_bits == 0 or transaction_bits % 8:
                findings.append(
                    _finding("SPI-P002", cycle, "CS deasserted on a partial byte", f"sampled_bits={transaction_bits}")
                )
            last_edge_cycle = None
        previous = sample
    if samples[-1]["signals"]["cs_n"] == 0:
        findings.append(
            _finding("SPI-P002", samples[-1]["cycle"], "trace ends with CS asserted", f"sampled_bits={transaction_bits}")
        )
    if observed_bytes != expected_mosi or observed_miso_bytes != expected_miso:
        findings.append(
            _finding(
                "SPI-P003",
                samples[-1]["cycle"],
                "SPI payload does not match the expected bytes",
                f"mosi_expected={expected_mosi} mosi_observed={observed_bytes}; "
                f"miso_expected={expected_miso} miso_observed={observed_miso_bytes}",
            )
        )
    return findings


def _assert_axi_stream(trace: Mapping[str, Any]) -> list[dict[str, Any]]:
    config = trace["config"]
    allowed = {"data_width", "expected_beats", "max_stall_cycles", "require_complete_packet"}
    if set(config) != allowed:
        raise ProtocolTraceError(f"AXI-Stream config must contain exactly {sorted(allowed)}")
    width = _integer(config["data_width"], "AXI-Stream data_width", minimum=1)
    if width > 4096:
        raise ProtocolTraceError("AXI-Stream data_width exceeds 4096")
    max_stall = _integer(config["max_stall_cycles"], "AXI-Stream max_stall_cycles", minimum=1)
    if not isinstance(config["require_complete_packet"], bool):
        raise ProtocolTraceError("AXI-Stream require_complete_packet must be boolean")
    expected = config["expected_beats"]
    if not isinstance(expected, list) or not all(
        isinstance(item, Mapping) and set(item) == {"tdata", "tlast"} for item in expected
    ):
        raise ProtocolTraceError("AXI-Stream expected_beats must contain tdata/tlast objects")
    normalized_expected = []
    for index, beat in enumerate(expected):
        data = _integer(beat["tdata"], f"expected beat {index} tdata")
        if data >= 1 << width:
            raise ProtocolTraceError(f"expected beat {index} tdata exceeds data_width")
        normalized_expected.append({"tdata": data, "tlast": _bit(beat["tlast"], "expected tlast")})
    findings: list[dict[str, Any]] = []
    observed: list[dict[str, int]] = []
    held: tuple[int, int] | None = None
    stall_count = 0
    packet_open = False
    for sample in trace["samples"]:
        cycle = sample["cycle"]
        signals = sample["signals"]
        if signals["tdata"] >= 1 << width:
            findings.append(
                _finding("AXIS-P006", cycle, "TDATA exceeds the declared width", f"tdata={signals['tdata']} width={width}")
            )
        if signals["reset_n"] == 0:
            held = None
            stall_count = 0
            packet_open = False
            continue
        if signals["tlast"] and not signals["tvalid"]:
            findings.append(_finding("AXIS-P002", cycle, "TLAST asserted without TVALID", "tlast=1 tvalid=0"))
        if held is not None:
            if not signals["tvalid"]:
                findings.append(
                    _finding("AXIS-P001", cycle, "TVALID dropped before handshake", f"held={held}")
                )
            elif (signals["tdata"], signals["tlast"]) != held:
                findings.append(
                    _finding("AXIS-P001", cycle, "payload changed while backpressured", f"held={held} current={(signals['tdata'], signals['tlast'])}")
                )
        if signals["tvalid"] and not signals["tready"]:
            held = held or (signals["tdata"], signals["tlast"])
            stall_count += 1
            if stall_count == max_stall + 1:
                findings.append(
                    _finding("AXIS-P004", cycle, "backpressure timeout exceeded", f"stall={stall_count} max={max_stall}")
                )
        else:
            held = None
            stall_count = 0
        if signals["tvalid"] and signals["tready"]:
            observed.append({"tdata": signals["tdata"], "tlast": signals["tlast"]})
            packet_open = not bool(signals["tlast"])
    if observed != normalized_expected:
        findings.append(
            _finding(
                "AXIS-P003",
                trace["samples"][-1]["cycle"],
                "handshaken payload or TLAST sequence differs from expectation",
                f"expected={normalized_expected} observed={observed}",
            )
        )
    if config["require_complete_packet"] and packet_open:
        findings.append(
            _finding("AXIS-P005", trace["samples"][-1]["cycle"], "trace ends before TLAST handshake", "packet_open=true")
        )
    return findings


def _write_vcd(trace: Mapping[str, Any], findings: list[dict[str, Any]], path: Path) -> None:
    signal_names = list(trace["samples"][0]["signals"])
    width = int(trace["config"].get("data_width", 1))
    identifiers = {name: chr(34 + index) for index, name in enumerate(signal_names)}
    violation_cycles = {item["cycle"] for item in findings}
    lines = [
        "$timescale 1ns $end",
        "$scope module protocol_trace $end",
        "$var wire 1 ! violation $end",
    ]
    for name in signal_names:
        signal_width = width if name == "tdata" else 1
        lines.append(f"$var wire {signal_width} {identifiers[name]} {name} $end")
    lines.extend(["$upscope $end", "$enddefinitions $end"])
    for sample in trace["samples"]:
        cycle = sample["cycle"]
        lines.extend([f"#{cycle}", f"{1 if cycle in violation_cycles else 0}!"])
        for name, value in sample["signals"].items():
            identifier = identifiers[name]
            lines.append(f"b{value:0{width}b} {identifier}" if name == "tdata" else f"{value}{identifier}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def analyze(trace_path: Path, *, root: Path, waveform_dir: Path | None = None) -> dict[str, Any]:
    resolved_root = root.resolve(strict=True)
    source = _inside(resolved_root, trace_path, must_exist=True)
    if source.stat().st_size > MAX_TRACE_BYTES:
        raise ProtocolTraceError(f"trace exceeds {MAX_TRACE_BYTES} byte limit")
    value = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ProtocolTraceError("trace root must be an object")
    trace = _validate_trace(value)
    trace_hash = _sha256(source)
    findings = _assert_spi(trace) if trace["protocol"] == "spi-mode0" else _assert_axi_stream(trace)
    waveform = None
    if findings and waveform_dir is not None:
        output_dir = _inside(resolved_root, waveform_dir, must_exist=False)
        if output_dir.exists() and (not output_dir.is_dir() or output_dir.is_symlink()):
            raise ProtocolTraceError("waveform output must be a non-symlink directory")
        output_dir.mkdir(parents=True, exist_ok=True)
        output = _inside(output_dir, output_dir / f"{trace['trace_id']}.fail.vcd", must_exist=False)
        _write_vcd(trace, findings, output)
        waveform = output.relative_to(resolved_root).as_posix()
    return {
        "schema_version": SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "status": FAIL if findings else PASS,
        "generated_at": _now(),
        "trace": source.relative_to(resolved_root).as_posix(),
        "trace_id": trace["trace_id"],
        "producer": trace["producer"],
        "trace_sha256": trace_hash,
        "evidence_id": f"sha256:{trace_hash}",
        "protocol": trace["protocol"],
        "summary": {"violations": len(findings), "blocking": len(findings)},
        "violations": findings,
        "waveform": waveform,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--waveform-dir", type=Path, default=Path("reports/protocol"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = analyze(args.trace, root=args.root, waveform_dir=args.waveform_dir)
        if args.output:
            output = _inside(args.root.resolve(strict=True), args.output, must_exist=False)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError, ProtocolTraceError) as exc:
        print(json.dumps({"status": "ERROR", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
