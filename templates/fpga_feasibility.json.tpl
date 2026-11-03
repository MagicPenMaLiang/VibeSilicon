{
  "schema_version": 1,
  "target_flow": "fpga",
  "implementation": "rtl",
  "device_part": "REPLACE_WITH_REVIEWED_PART",
  "bindings": [
    {"role": "numeric_contract", "path": "numeric_contract.json", "sha256": "REPLACE_WITH_SHA256"},
    {"role": "golden_model", "path": "golden_manifest.json", "sha256": "REPLACE_WITH_SHA256"},
    {"role": "test_vectors", "path": "vector_manifest.json", "sha256": "REPLACE_WITH_SHA256"}
  ],
  "workload": {
    "item_unit": "REPLACE_WITH_PIXEL_SAMPLE_OR_TRANSACTION",
    "clock_hz": "REPLACE_WITH_REVIEWED_CLOCK",
    "required_items_per_second": "REPLACE_WITH_REQUIRED_RATE",
    "items_per_initiation": "REPLACE_WITH_LANE_COUNT",
    "initiation_interval_cycles": "REPLACE_WITH_SCHEDULED_INTERVAL",
    "sustained_fraction": "REPLACE_WITH_STALL_AND_PROTOCOL_FACTOR",
    "latency_cycles": "REPLACE_WITH_BOUNDED_LATENCY",
    "max_latency_seconds": "REPLACE_WITH_LATENCY_LIMIT"
  },
  "resources": [{"name": "LUT", "estimated": "REPLACE_WITH_ESTIMATE", "budget": "REPLACE_WITH_DESIGN_BUDGET"}],
  "memories": [{"name": "line_buffer", "width_bits": "REPLACE_WITH_WIDTH", "depth": "REPLACE_WITH_DEPTH", "copies": "REPLACE_WITH_COPIES", "budget_bits": "REPLACE_WITH_ALLOCATION"}],
  "external_memory": {"bytes_per_item": "REPLACE_WITH_TOTAL_READ_WRITE_BYTES", "available_bytes_per_second": "REPLACE_WITH_SUSTAINABLE_BUDGET"}
}
