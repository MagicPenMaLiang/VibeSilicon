{
  "schema_version": 1,
  "family": "ps7",
  "part": "xc7z020clg400-1",
  "preset": {
    "path": "external/reviewed_board_preset.xml",
    "sha256": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  },
  "initialization": {
    "path": "external/reviewed_ps_initialization.tcl",
    "sha256": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  },
  "interface_contract": {
    "path": "external/interface_contract.json",
    "sha256": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
  },
  "board_tests": [
    "identity",
    "boot_log",
    "ddr_memory",
    "peripheral",
    "clock_reset"
  ]
}
