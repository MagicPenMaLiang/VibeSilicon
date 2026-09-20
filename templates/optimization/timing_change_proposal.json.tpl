{
  "schema_version": 1,
  "proposal_id": "TIMING-CHANGE-001",
  "analysis_evidence_id": "sha256:<64-hex>",
  "hypothesis": "one falsifiable timing hypothesis",
  "changes": [
    {"path": "rtl/top.sv", "kind": "rtl", "description": "minimal proposed change"}
  ],
  "constraints": [],
  "invariants": ["bit_exact", "latency_unchanged", "protocol_unchanged"],
  "required_gates": ["G1", "G2", "G3", "G4"],
  "max_iterations": 3,
  "approval_status": "PENDING"
}
