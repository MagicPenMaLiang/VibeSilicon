#!/usr/bin/env bash
# ============================================================
#  VibeSilicon POSIX shell entry (Linux + macOS).
#
#  Thin wrapper that delegates to scripts/setup_env_core.py.
#  All real logic lives in the Python core so this script can
#  stay small and easy to audit.
#
#  Exit codes (forwarded from the Python core):
#      0  ready - Python deps importable, smoke checks pass.
#      2  venv could not be created.
#      3  locked dependencies failed.
#      4  public_release_audit.py failed (only when --audit).
#      5  unit-test smoke failed.
#      10 optional EDA tools missing (warning only).
#      98 no Python interpreter found.
#      99 setup_env_core.py missing.
#
#  Usage:
#      scripts/setup_env.sh                  [default full run]
#      scripts/setup_env.sh --recreate       [rebuild .venv]
#      scripts/setup_env.sh --skip-tests     [skip unittest smoke]
#      scripts/setup_env.sh --no-install     [trust existing venv]
#      scripts/setup_env.sh --no-audit       [skip release audit]
#      scripts/setup_env.sh --audit          [run release audit]
#      scripts/setup_env.sh --json           [machine-readable]
#      scripts/setup_env.sh --help
# ============================================================
set -eu

# Resolve the script directory even when invoked through a symlink so the
# wrapper keeps working from copied or relocated checkouts.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CORE="${SCRIPT_DIR}/setup_env_core.py"

if [ ! -f "${CORE}" ]; then
    printf 'setup_env.sh: missing %s\n' "${CORE}" >&2
    exit 99
fi

# Map long flags to the core's argv contract. Anything not recognised falls
# through untouched so forward-compatible core flags keep working.
CORE_ARGS=""
SKIP_NEXT=0
for arg in "$@"; do
    if [ "${SKIP_NEXT}" -eq 1 ]; then
        SKIP_NEXT=0
        continue
    fi
    case "${arg}" in
        --recreate|--recreate-venv) CORE_ARGS="${CORE_ARGS} --recreate-venv" ;;
        --skip-tests)               CORE_ARGS="${CORE_ARGS} --skip-tests" ;;
        --no-install)               CORE_ARGS="${CORE_ARGS} --no-install" ;;
        --no-audit)                 CORE_ARGS="${CORE_ARGS} --no-audit" ;;
        --audit)                    CORE_ARGS="${CORE_ARGS} --audit" ;;
        --json)                     CORE_ARGS="${CORE_ARGS} --json" ;;
        -h|--help)
            cat <<'USAGE'
VibeSilicon POSIX environment setup

Usage:
  scripts/setup_env.sh [--recreate] [--skip-tests] [--no-install]
                       [--audit | --no-audit] [--json] [--help]

Default behaviour: create or reuse .venv, install locked dependencies,
run the import smoke, run unit tests, probe optional EDA tools. The
public_release_audit.py gate is skipped by default; pass --audit to
opt in.

See docs/setup_env.md for the full exit code table.
USAGE
            exit 0
            ;;
        *)
            printf 'setup_env.sh: unknown argument: %s\n' "${arg}" >&2
            printf 'Run scripts/setup_env.sh --help for usage.\n' >&2
            exit 64
            ;;
    esac
done

# Interpreter selection: prefer the repo's venv, then VIBESILICON_MCP_PYTHON,
# then any python3 / python on PATH. We deliberately avoid `command -v python`
# on POSIX because some distros ship only python3.
PY=""
if [ -x "${ROOT}/.venv/bin/python" ]; then
    PY="${ROOT}/.venv/bin/python"
elif [ -n "${VIBESILICON_MCP_PYTHON:-}" ] && [ -x "${VIBESILICON_MCP_PYTHON}" ]; then
    PY="${VIBESILICON_MCP_PYTHON}"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PY="$(command -v python)"
fi

if [ -z "${PY}" ]; then
    printf 'setup_env.sh: no python3 found on PATH and no .venv present.\n' >&2
    printf 'Install Python 3.10-3.12 or run scripts/setup_env.sh after creating .venv.\n' >&2
    exit 98
fi

# shellcheck disable=SC2086 # CORE_ARGS is intentionally split on whitespace.
"${PY}" "${CORE}" ${CORE_ARGS}
EC=$?

if [ "${EC}" -ne 0 ]; then
    printf '\nsetup_env.sh: completed with exit code %s\n' "${EC}" >&2
    printf 'See docs/setup_env.md for the meaning of each code.\n' >&2
fi

exit "${EC}"
