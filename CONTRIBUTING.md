# Contributing

Contributions are welcome when they are reusable, attributable, and safe to publish.

1. Do not submit confidential designs, proprietary PDK data, EDA licenses, credentials, personal paths, generated vendor IP, or customer evidence.
2. Add or update tests for behavioral changes.
3. Run `python scripts/public_release_audit.py` and the unit test suite.
4. Keep agent tools bounded and fail closed when required evidence or tools are unavailable.
5. Document whether a result is simulation, formal, FPGA implementation, ASIC physical verification, or a non-signoff estimate.

Maintain skills in `skills/` and role contracts/routing in `subagents/catalog.json`.
Use `hw-*`/`rtl-*` for shared capabilities and `fpga-*`/`asic-*` for target-specific
work. Existing compatibility names resolve directly to maintained entries;
do not introduce alias chains or count aliases as additional capabilities.
See [project map](docs/project_map.md) for the current classification and gaps.

After changing these sources, regenerate and check the client copies:

```bash
python scripts/sync_skills.py --write
python scripts/sync_skills.py --check
python -m scripts.sync_agents --write
python -m scripts.sync_agents --check
```

Do not edit generated role TOML, native agent files or native skill copies as
the only source of a change. Preserve target separation, reviewer read-only
access, unrelated client settings and existing approval boundaries.

Write public documentation, skill instructions, comments and templates in English.
Keep command syntax, identifiers, protocol terminology and source citations intact.
Follow [release preparation](docs/release_preparation.md) for Git candidate auditing
and source snapshot preparation; do not force-add ignored local design data.

By submitting a contribution, you agree that it is licensed under Apache-2.0 and that you have the right to contribute it.
