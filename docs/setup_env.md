# VibeSilicon environment setup

The repository ships three one-shot launchers that prepare and verify a
VibeSilicon development environment. They share a single Python core
(`scripts/setup_env_core.py`) so the behaviour and exit codes are identical
across platforms:

| File | Style | When to use |
|---|---|---|
| `scripts/setup_env.sh`   | POSIX shell | Linux, macOS, WSL, GitHub Actions |
| `scripts/setup_env.ps1`  | PowerShell  | Windows modern shells, CI agents, dev machines |
| `scripts/setup_env.cmd`  | cmd batch   | Windows legacy `.bat`-only consoles, Task Scheduler |

CI pipelines and Makefile-style automation should call the Python core
directly so the same JSON output is available regardless of host OS:

```bash
python scripts/setup_env_core.py --json
```

## What the script does

1. **Create or reuse `.venv`** at the repository root. Pass `--recreate`
   (sh/cmd) / `-RecreateVenv` (ps1) / `--recreate-venv` (core) to wipe and
   rebuild.
2. **Install locked Python dependencies** from `requirements-dev.lock`
   (which transitively pulls `requirements.lock`). Skip with `--no-install`.
3. **Import smoke** — verifies that every locked package imports cleanly
   and prints its reported version (via `importlib.metadata`, not
   `pkg.__version__`).
4. **Run `scripts/public_release_audit.py`** as a source-tree gate. The
   audit is **skipped by default** so a fresh checkout succeeds even when
   transient workspace artifacts (node_modules, generated logs) are
   present. Pass `--audit` to opt in.
5. **Run the unit-test smoke** via `unittest discover`. Skip with
   `--skip-tests` for fast iteration.
6. **Probe optional EDA tools** on `PATH`: `verilator`, `yosys`,
   `symbiyosys` (`sby`), `vivado`, `vitis_hls`, `openroad`, `klayout`.

Each step prints a structured line so the launcher can show exactly which
check failed.

## Usage

### POSIX shell (Linux / macOS / WSL)

```bash
scripts/setup_env.sh                # full run (audit skipped)
scripts/setup_env.sh --recreate     # wipe and rebuild .venv
scripts/setup_env.sh --skip-tests   # skip unittest smoke
scripts/setup_env.sh --no-install   # trust existing venv
scripts/setup_env.sh --audit        # opt in to public-release audit
scripts/setup_env.sh --no-audit     # explicit skip (also default)
scripts/setup_env.sh --json         # machine-readable output
scripts/setup_env.sh --help         # in-script help
```

The sh wrapper resolves the script directory through `BASH_SOURCE` so it
keeps working through symlinks. It uses `bash` features (arrays would be
nice but `set -eu` + `case` keeps it portable across bash 3.2 / zsh / dash).
Interpreter preference, in order: `.venv/bin/python` →
`$VIBESILICON_MCP_PYTHON` → `python3` → `python`.

### PowerShell (Windows)

```powershell
pwsh -File scripts\setup_env.ps1                # full run (audit skipped)
pwsh -File scripts\setup_env.ps1 -RecreateVenv  # wipe and rebuild .venv
pwsh -File scripts\setup_env.ps1 -SkipTests     # skip unittest smoke
pwsh -File scripts\setup_env.ps1 -NoInstall     # trust existing venv
pwsh -File scripts\setup_env.ps1 -Audit         # opt in to public-release audit
pwsh -File scripts\setup_env.ps1 -NoAudit       # explicit skip (also default)
pwsh -File scripts\setup_env.ps1 -Json          # machine-readable output
pwsh -File scripts\setup_env.ps1 -Help          # ps1 help
```

### cmd (Windows legacy)

```bat
scripts\setup_env.cmd
scripts\setup_env.cmd --recreate
scripts\setup_env.cmd --skip-tests
scripts\setup_env.cmd --no-install
scripts\setup_env.cmd --audit
scripts\setup_env.cmd --no-audit
scripts\setup_env.cmd --json
scripts\setup_env.cmd --help
```

The cmd launcher prefers `pwsh.exe` (PowerShell 7) and falls back to the
built-in `powershell.exe` (Windows PowerShell 5.1).

### Direct Python (CI / Makefile)

```bash
python scripts/setup_env_core.py --json
```

This is the most portable form. The Python core is the single source of
truth for behaviour and exit codes.

## Argument cross-reference

| Behaviour              | sh / cmd / core        | PowerShell (ps1)   |
|---|---|---|
| Rebuild `.venv`        | `--recreate`           | `-RecreateVenv`    |
| Skip unittest smoke    | `--skip-tests`         | `-SkipTests`       |
| Trust existing venv    | `--no-install`         | `-NoInstall`       |
| Skip release audit     | `--no-audit`           | `-NoAudit`         |
| Run release audit      | `--audit`              | `-Audit`           |
| JSON output            | `--json`               | `-Json`            |
| Help                   | `--help` / `-h`        | `-Help`            |

## Exit codes

| Code | Meaning |
|---:|---|
| `0`  | Ready — Python dependencies importable, smoke checks pass. |
| `2`  | The `.venv` could not be created or bootstrapped (e.g. `ensurepip` is missing). Re-run after installing the matching `python3-venv` package or invoking the launcher with a Python that has `pip` available. |
| `3`  | One or more locked dependencies failed to install or import. Re-run with the launcher removed to inspect the `pip install` tail, or remove `--no-install`. |
| `4`  | `public_release_audit.py` reported blocked paths. Investigate the audit output; this gate exists to keep PDKs, bitstreams, and personal paths out of the public tree. |
| `5`  | The unit-test smoke run failed. Re-run `python -m unittest discover -s tests -p "test_*.py"` for the full diff. |
| `10` | One or more optional EDA tools are missing. The script still exits non-zero so CI can warn, but the Python environment itself is ready. |
| `64` | (sh only) The user passed an unknown argument. |
| `98` | No Python interpreter was found on `PATH` and there is no `.venv`. |
| `99` | `setup_env_core.py` could not be located next to the wrapper. |

Exit codes `98` and `99` are emitted by the wrappers themselves; everything
in `0..64` is forwarded directly from the Python core.

## What "ready" does **not** imply

The launcher only validates the portable Python environment. Whether a flow
that needs a specific EDA tool can run depends on that tool being on `PATH`:

* FPGA lint/sim only needs `verilator` (optional but recommended).
* Formal verification needs `yosys` + `symbiyosys`.
* FPGA implementation needs `vivado`.
* HLS implementation needs `vitis_hls`.
* ASIC synthesis / STA / physical flow needs `openroad` and `klayout`.

These are listed in the report under `eda:<name>` with a `WARN` status when
missing. The launcher does not fail on optional tools; CI agents can opt in
by checking the `--json` output and the `exit_code == 10` signal.

## Claude Code integration

Start Claude Code from the repository root after preparing `.venv`. The
project `.mcp.json` starts all three servers through `scripts/mcp_launcher.py`,
which selects a Python runtime with the required MCP dependencies. A local
`VIBESILICON_MCP_PYTHON` environment variable can select a preferred runtime;
do not put machine-specific interpreter paths into shared settings.

The shared `.claude/settings.json` enables only `python-sim`, `vitis-hls`,
and `vivado`, and retains the RTL edit hook. Claude Code applies shared
project MCP approvals after workspace trust; accept its workspace trust
dialog when opening the project. See the
[Claude Code MCP trust documentation](https://code.claude.com/docs/en/mcp#project-server-approvals-and-workspace-trust).
This server list does not bypass tool permissions or engineering sign-off.

Use the ignored `.vibesilicon/mcp-env.json` described below for local EDA
paths shared by Claude Code and Codex. Claude-only overrides may be stored
in `.claude/settings.local.json`, which is also ignored by Git. Keep any
existing local overrides when updating the shared configuration.

Restart Claude Code after updating configuration. Run `claude mcp get`
for each of the three server names, or inspect `/mcp` in the session, to
verify connection status. A connected server does not prove that an EDA
license or a hardware run is available.

## Codex integration

Start Codex with the repository root as the working directory. The project
`.codex/config.toml` uses `cwd = "."` for the three MCP launchers. Trust the
project so its config and `.agents/skills/` are available. The native Codex
agents in `.codex/agents/` reference the canonical contracts in `subagents/`;
the reviewer additionally uses a read-only sandbox.

For machine-specific EDA paths, create `.vibesilicon/mcp-env.json` locally:

```json
{
  "VIVADO_BIN": "/absolute/path/to/vivado",
  "VITIS_RUN_BIN": "/absolute/path/to/vitis-run"
}
```

On Windows, use the installed `.bat` or `.exe` launcher paths. Optional
`VIVADO_SETTINGS` may point to the installation's settings script. Only these
three keys are accepted, paths must be absolute existing files, and explicit
process environment variables take precedence. `.vibesilicon/` is ignored by
Git; do not copy personal tool paths into the tracked Codex configuration.

After changing configuration, reload MCP or restart the Codex session.
Check `codex doctor --json` for malformed role warnings and
`codex mcp list` for registered servers. Registration does not prove a
successful MCP handshake or an available EDA license.

The edit hook uses Codex's `matcher`/`hooks` format. Review and trust its
definition through Codex's hook controls (`/hooks` in the CLI); project trust
alone does not authorize a non-managed hook. The PostToolUse check reports
RTL gate failures after an edit and does not undo the edit.

## Relationship to the README quickstart

The README quickstart is still valid for first-time bootstrap on any OS:

```bash
python -m venv .venv
# Linux/macOS:  source .venv/bin/activate
# Windows:      .venv\Scripts\activate
python -m pip install -r requirements-dev.lock
python scripts/public_release_audit.py
python -m unittest discover -s tests -p "test_*.py"
```

The three wrappers wrap those four commands plus the EDA probe and produce
a structured report plus a stable exit code, which is useful for CI and
for repeated local verification.
