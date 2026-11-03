# Preparing a GitHub source update

This repository publishes a reusable engineering toolkit. Local designs, raw EDA
runs, customer evidence, PDKs, credentials and machine-specific configuration stay
outside the public update. Public instructions and templates are maintained in
English. Chat responses and private project records can use the project's language.

## Reviewed maintenance changes

- Hardware roles and target routing have one maintained source in
  `subagents/catalog.json`; client adapters are generated and checked in CI.
- Shared RTL skills and separate FPGA/ASIC branches retain direct compatibility
  names. Supporting resources at old paths are generated mirrors, so they cannot
  silently diverge from the maintained resource.
- The project map, project input worksheet and real-time video guidance are in
  English. Video lessons describe reusable methods without relying on unpublished
  run IDs, private analysis files or unshipped board performance claims.
- Skill validation rejects malformed identity/metadata and duplicate routes.
  Reviewer read-only configuration requires the actual boolean `true`.
- Codex reviewer files no longer contain ineffective agent-local sandbox/MCP
  overrides. Review permissions are inherited from the parent; enforce isolation
  in the parent review session. This follows the
  [official custom-agent permission model](https://learn.chatgpt.com/docs/agent-configuration/subagents).
- The public audit uses Git candidate selection in a checkout and strict source
  traversal in an export. It reports unreadable, linked and unsupported files as
  failures, checks templates/scripts/locks as text and rejects generated artifacts.
- `jsonschema` is declared in the runtime dependency list, matching its runtime
  use and `pyproject.toml`; development dependencies extend the runtime list.

These are software and packaging changes. They do not qualify an EDA installation,
board, process kit, timing result or production signoff.

## What is selected for publication

In a checkout, `scripts/public_release_audit.py` reads the union of tracked files
and untracked files not excluded by Git ignore rules. Tracked deletions are omitted
from the prepared snapshot. Ignored local directories are not traversed. A tracked
file remains subject to audit even if it matches an ignore rule: force-adding a
run or secret does not make it publishable.

The public profile permits the root project/configuration files and these source
directories: `.agents`, `.claude`, `.codex`, `.github`, `.opencode`, `config`, `docs`,
`examples`, `mcp`, `schemas`, `scripts`, `skills`, `subagents`, `templates`, `tests`
and `third_party`. Client directories have narrower configuration/agent/skill
subpaths. File types and root filenames are declared in the auditor. A new source
category requires an explicit review of that profile; unknown files are not
silently accepted. The audit is a deterministic content screen, not a complete
secret scanner or a substitute for ownership/license review.

Known local workspace roots and tool outputs are ignored by `.gitignore`. This
does not delete them or certify their contents. Inspect `git status --short` before
staging, and review the diff without using `git add .` as a substitute for selection.

## Verify and prepare a source snapshot

```bash
python scripts/sync_skills.py --check
python -m scripts.sync_agents --check
python -m ruff check scripts mcp tests
python -m unittest discover -s tests -p "test_*.py"
python scripts/public_release_audit.py --json
git diff --check
```

Run the `--write` synchronization modes only after reviewing edits to their
canonical sources. Missing or skipped EDA tests remain explicit; software test
success is not hardware validation.

Prepare a fresh snapshot using an unused destination:

```bash
python scripts/public_release_audit.py --prepare .vibesilicon/github-candidate --json
python scripts/public_release_audit.py --root .vibesilicon/github-candidate/source --json
```

Preparation audits before copying, records SHA-256 and byte counts, independently
audits the export and writes `manifest.json` beside `source/`. It refuses to
overwrite a destination or write outside a new directory below `.vibesilicon`.
It does not change the Git index, commit, push or create a GitHub release.
The export includes working-tree edits and eligible new files; it is not a staged
index snapshot. Review and stage the intended changes separately.

Use the snapshot as a review/reproduction artifact, not as evidence that an upload
occurred. Run the source gate again if files change after preparation. GitHub
publication still uses the reviewed commit and existing project authority.
