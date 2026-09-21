# Third-Party Notices

This file inventories software required or referenced by VibeSilicon. It is not a
replacement for the complete license text shipped by each upstream package.
Release owners must re-check the resolved dependency set before distribution.

## Python runtime dependencies

| Component | Pinned version | Upstream license | Use |
|---|---:|---|---|
| Model Context Protocol Python SDK (`mcp`) | 1.26.0 | MIT | MCP server runtime |
| NumPy | 1.26.4 | BSD-3-Clause | Numeric simulation and comparison |
| PyYAML | 6.0.2 | MIT | Project/KPI configuration |
| fxpmath | 0.4.9 | MIT | Fixed-point simulation |
| scikit-image | 0.24.0 | BSD-3-Clause | PSNR/SSIM metrics |

## Development and validation dependencies

| Component | Pinned version | Upstream license | Use |
|---|---:|---|---|
| pytest | 8.4.2 | MIT | Test runner compatibility |
| Ruff | 0.14.1 | MIT | Python linting |
| Verilator | system package | LGPL-3.0-or-later or Artistic-2.0 | RTL lint |

Transitive dependencies are installed from the Python package index and retain
their own licenses. A release SBOM/notice must be generated from the actual
resolved environment rather than inferred only from `requirements.lock`.

## External proprietary tools

- AMD Vivado and Vitis HLS are user-installed proprietary tools. VibeSilicon does
  not redistribute their installers, licenses, generated IP, caches, DCPs or
  bitstreams.
- Optional third-party tool adapters are not bundled. Any future adapter must
  require the user to install the tool separately and accept its applicable terms.
