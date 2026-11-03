"""Cheap FPGA planning rejection from explicit rates, capacities and immutable inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from scripts.evidence_contract import canonical_bytes, sha256_bytes, sha256_file, _relative_file, _validate_relative_path


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/fpga_feasibility.schema.json"


def assess(root: Path, contract: dict) -> dict:
    """CANDIDATE means only these declared estimates fit; it is never a gate PASS."""
    root = root.resolve(strict=True)
    contract_bytes = canonical_bytes(contract)  # Reject NaN/Inf before arithmetic.
    schema_bytes = SCHEMA.read_bytes()
    Draft202012Validator(json.loads(schema_bytes)).validate(contract)
    roles = [binding["role"] for binding in contract["bindings"]]
    if set(roles) != {"numeric_contract", "golden_model", "test_vectors"}:
        raise ValueError("bindings require one numeric contract, golden model and vector manifest")
    for binding in contract["bindings"]:
        # Shared contract validates normalized relative paths; no model is executed.
        relative = binding["path"]
        _validate_relative_path(relative)
        path, _ = _relative_file(relative, root)
        if sha256_file(path) != binding["sha256"]:
            raise ValueError(f"immutable input hash mismatch: {binding['role']}")
    for group in ("resources", "memories"):
        names = [item["name"] for item in contract[group]]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate {group} names")
    work = contract["workload"]
    peak_rate = work["clock_hz"] * work["items_per_initiation"] / work["initiation_interval_cycles"]
    sustained_rate = peak_rate * work["sustained_fraction"]
    latency = work["latency_cycles"] / work["clock_hz"]
    external = contract["external_memory"]
    bandwidth = work["required_items_per_second"] * external["bytes_per_item"]
    checks = [
        {"metric": "required_items_per_second", "demand": work["required_items_per_second"], "budget": sustained_rate},
        {"metric": "latency_seconds", "demand": latency, "budget": work["max_latency_seconds"]},
        {"metric": "external_bytes_per_second", "demand": bandwidth, "budget": external["available_bytes_per_second"]},
    ]
    checks.extend({"metric": f"resource.{row['name']}", "demand": row["estimated"], "budget": row["budget"]}
                  for row in contract["resources"])
    checks.extend({"metric": f"memory_bits.{row['name']}",
                   "demand": row["width_bits"] * row["depth"] * row["copies"], "budget": row["budget_bits"]}
                  for row in contract["memories"])
    for row in checks:
        row["fits_estimate"] = row["demand"] <= row["budget"]
    # Check the declared bindings again after computation, without changing input bytes.
    for binding in contract["bindings"]:
        path, _ = _relative_file(binding["path"], root)
        if sha256_file(path) != binding["sha256"]:
            raise ValueError(f"immutable input changed during assessment: {binding['role']}")
    result = {
        "schema_version": 1, "target_flow": "fpga", "implementation": contract["implementation"],
        "device_part": contract["device_part"], "contract_sha256": sha256_bytes(contract_bytes),
        "schema_sha256": sha256_bytes(schema_bytes), "bindings": contract["bindings"],
        "status": "CANDIDATE" if all(row["fits_estimate"] for row in checks) else "REJECTED",
        "acceptance": "NOT_EVALUATED", "hardware_validated": False,
        "peak_items_per_second": peak_rate, "sustained_items_per_second": sustained_rate,
        "checks": checks,
        "unverified": ["numeric semantics", "dependency closure of bound files", "architecture approval",
                       "memory banking and collision schedule", "FIFO deadlock and stalls", "achieved timing",
                       "resource inference and packing", "functional correctness", "hardware behavior"],
    }
    result["evidence_id"] = sha256_bytes(canonical_bytes(result))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        # Bound the planning input; artifact bindings remain project-confined.
        with args.contract.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("planning contract exceeds 1 MiB")
        result = assess(args.root, json.loads(raw))
    except ValidationError as exc:
        print(json.dumps({"status": "BLOCKED", "error": exc.message}))
        return 2
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}))
        return 2
    print(json.dumps(result, allow_nan=False))
    return 0 if result["status"] == "CANDIDATE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
