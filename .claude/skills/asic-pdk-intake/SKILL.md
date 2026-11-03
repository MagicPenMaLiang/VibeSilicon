---
name: asic-pdk-intake
description: Validate external ASIC design and PDK views, license review, process corners and permitted backend capabilities before synthesis or physical work.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: intake
  routes: [asic, both]
---

# ASIC input and PDK intake

Read repository-root `docs/new_project_inputs.md`,
`config/asic_backend_policy.json` and `templates/asic_input_manifest.template.json`.
PDK selection remains independently reviewed; never select a reference PDK or
reuse its electrical/physical values merely because an example is available.

Use `python -m scripts.asic_backend_contract --help` for contract build,
capability discovery and verification. Use
`python -m scripts.asic_input_evidence --help` for input evidence build/verify.
The CLI takes a declared repository root; PDK/design roots are separate external
inputs. Capability discovery may probe executables but grants no execution
authorization. A present executable is unqualified until the input and execution
contracts hold.

Check source/top/constraints binding, full view hashes, license/ownership review,
process/voltage/temperature and RC assumptions. Inventory Liberty, LEF, GDS,
SPICE, SDC and required synthesis/physical/rule-deck views against the policy.
Review memory/macro interfaces, latency, collision/reset semantics and available
abstract views with hw-microarch; a black box is not an implemented memory.

Build evidence from actual external files. Verify evidence against the policy
and backend contract. Do not copy proprietary files or raw absolute paths into
committed manifests or generated examples. Missing views, license review or
corner bindings block the stages that need them; do not synthesize dummy views.

Return the backend contract ID, capability ID, input evidence ID, reviewed PDK
identity/corners, missing scope and the owner of each blocking input. Pass
verified bindings to asic-synthesis and asic-physical-design.
