# IP project setup

This directory is a setup guide, not an executable IP implementation. Create a
private project workspace and copy the applicable files from the repository's
`templates/` directory. Do not add customer designs to the public toolkit.

## Declare the project contract

Start with `docs/new_project_inputs.md` and `templates/spec.md.template`.
Declare the target flow (`fpga`, `asic`, or `both`), owner, third-party licenses,
functional and numeric contract, interfaces, clocks, resets, throughput, latency,
backpressure, target device or external PDK views, PPA budgets and approval scope.
Freeze the golden model and accepted vectors before implementation.

Use `skills/fpga-micro-arch/templates/micro_arch_template.md` for the reviewed
architecture. Keep behavioral contracts shared for a dual-target design, while
maintaining separate manifests, constraints, memory wrappers and target evidence.

## Prepare RTL inputs

Run the toolkit from the root of the private checkout containing the project.
The current RTL adapters require manifests and source paths within that root;
they do not accept paths escaping the checkout. Keep project inputs out of the
public release tree and explicitly exclude them from public commits.

| Repository template | Project file | Purpose |
|---|---|---|
| `templates/rtl/project_manifest.json.template` | `rtl_project_manifest.json` | Complete RTL compilation inventory |
| `templates/rtl/quality_waivers.json.template` | `rtl_quality_waivers.json` | Reviewed waiver registry, including an empty registry |
| `templates/rtl/simulation_contract.json.template` | `rtl_simulation_contract.json` | Bounded self-checking simulation contract |
| `templates/rtl/selfcheck_tb.sv.template` | Project testbench | Scaffold that fails until independent checks are implemented |
| `templates/test_vectors.yaml.template` | Project vectors | Reviewed inputs and expected outputs |

Replace placeholders and enumerate every source, header, include directory,
define and parameter. Paths in the manifest are relative to the checkout root,
not to the manifest directory. Declare the actual top module, clocks and resets.
The self-checking testbench must compare against independent expected results;
an exit code or a printed PASS token alone is insufficient.

From the checkout root, use the actual project manifest path:

```bash
python -m scripts.quality_gate.rtl_manifest path/to/rtl_project_manifest.json
python -m scripts.quality_gate.rtl_waiver_registry path/to/rtl_project_manifest.json
python -m scripts.quality_gate.rtl_project_gate path/to/rtl_project_manifest.json
```

The portable example in `examples/rtl/counter/` demonstrates these inputs.
Its behavior and timing are examples, not defaults for a new IP. For HLS, declare
the reviewed top function, source/testbench inputs, device and clock before using
the bounded Vitis HLS adapter. C simulation does not establish RTL or board validity.

## Keep source and generated evidence separate

Maintain source RTL/HLS, constraints, build scripts, specifications and sanitized
contracts in version control where ownership permits. Keep generated vendor IP,
EDA licenses, PDKs, customer assets, raw run directories, `.bit`, `.ltx`, `.dcp`
and GDS files outside public commits. Do not force-add ignored build products.
Record artifact hashes, tool versions, configuration and evidence IDs instead;
retain raw artifacts in the project's approved private evidence store.

## Review and handoff

Follow the gates in `AGENTS.md`: reviewed architecture, G0 manifest, G1 static
checks, G2 simulation/protocol/formal as applicable, then target implementation
and hardware validation where required. Missing tools or evidence remain blocked
or explicitly skipped; neither status is PASS. Human architecture and high-risk
sign-off are required according to the project contract and applicable schemas.

Use `templates/acceptance_report.md.template` to summarize the evidence and open
items. Declare reproduction inputs, commands, expected outcomes and tool versions
in the appropriate supported manifest or contract; there is no standalone
project-reproduction catalog or runner in this repository.
