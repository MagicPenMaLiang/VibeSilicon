{
  "schema_version": 1,
  "experiment_id": "OPT-CHANGE-ME",
  "hypothesis": "One independently testable RTL change improves routed timing.",
  "baseline": {
    "evidence_id": "sha256:<64 lowercase hexadecimal characters>",
    "metrics": {
      "wns_ns": 0.0,
      "lut": 0
    }
  },
  "objectives": [
    {"metric": "wns_ns", "operator": ">=", "value": 0.2}
  ],
  "guardrails": [
    {"metric": "lut", "max_delta_pct": 5.0}
  ],
  "non_regression": [
    {"metric": "wns_ns", "direction": "higher"}
  ],
  "invariants": ["bit_exact", "latency_unchanged"],
  "files": ["rtl/design.sv"],
  "required_gates": ["G1", "G2", "G3", "G4"],
  "max_iterations": 3,
  "auto_rollback": true,
  "min_improvement": {"metric": "wns_ns", "absolute": 0.01}
}
