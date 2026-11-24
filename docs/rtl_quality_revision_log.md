# RTL quality standard — revision log

One entry per accepted change to the reviewed RTL quality standard. A revision
is identified by `standard_version`, which is recorded in both reviewed
configuration files and, since 1.1, enforced by
`scripts/quality_gate/rtl_quality_config.py`.

Evidence produced under one version is not evidence produced under another. Two
gate runs whose ids differ only because the rule set moved are not comparable;
re-run rather than re-read.

---

## 1.1 — 2026-11-14

**Change.** G2 now requires `domain_approval` for any project declaring more
than one clock or more than one reset.

**Why.** Before this revision the only accepted proof for a multi-domain project
was a tool verdict: `rtl_domain_evidence.json` with `cdc_status` and
`rdc_status` equal to `PASS`. Nothing in the gate asked who decided that the
remaining crossings were acceptable.

That decision had already been assigned to a human in the process documents:

- `AGENTS.md` — `orchestrator-hw` "stops on missing evidence or approval";
- `AGENTS.md` — "reset/CDC exceptions … require independent human review";
- `subagents/catalog.json` — `signed_architecture_required: true`.

None of it was executed. A green `report_cdc` was treated as an engineering
decision. The gap became visible on the KV260 G1 probe, where `report_cdc` ends
with zero Critical entries but a Warning (CDC-15) remains whose acceptance is a
judgement about a capture pattern, not a tool output. An approval record was
written for that project by hand; the gate did not read it.

This revision closes the gap by giving the existing rule an executor.

### What the approval record must satisfy

`<project_root>/rtl_domain_approval.json`, validated by
`scripts/quality_gate/rtl_supplemental_policy.py`:

| Requirement | Reason |
|---|---|
| Closed field set, `schema_version` 1 | A record with unknown fields is a different record. |
| `evidence_id` equals the content id of the current `rtl_domain_evidence.json` | Regenerating the evidence invalidates the approval by construction; the record cannot drift onto a verdict it never saw. |
| `approved_by` ≠ `generated_by` (case-insensitive) | The generator of the evidence may not approve it. Same rule as the waiver registry. |
| `approved_at_utc` and `generated_at_utc` are strict RFC3339 UTC; approval not earlier than generation | An approval predating the evidence approved nothing. Local offsets are rejected: one instant, one meaning. |
| `approved_scope` and `excluded_scope` are non-empty, unique statement lists | An approval that does not say what it covers cannot be checked, and one that does not say what it excludes will be over-read. |
| `basis` is non-empty | Transcribed owner decision and independent review are different things; the record has to say which it is. |
| `record_id` is the content id over all other fields | The record is self-verifying; editing any field after signing breaks it. |

### Version handling

`standard_version` moved 1.0 → 1.1 in **both** `config/rtl_quality_policy.json`
and `config/rtl_quality_rules.json`. The rule inventory did not change; the
standard as a whole did. Keeping the two files on one version preserves the
invariant that they describe the same standard, and forces both byte pins to be
re-reviewed.

`REQUIRED_GATE_CHECKS` in `rtl_quality_config.py` pins `domain_approval` into
G2. Removing the check is therefore not a JSON edit: it requires editing that
constant, which is a reviewed code change. `GATE_CHECKS` closes the vocabulary
so a misspelt check name cannot silently switch a requirement off.

### Files changed

| File | Change |
|---|---|
| `config/rtl_quality_policy.json` | `standard_version` 1.1; `gate_requirements.g2` += `domain_approval` |
| `config/rtl_quality_rules.json` | `standard_version` 1.1 (rules unchanged) |
| `schemas/rtl_quality_policy.schema.json` | `standard_version` const 1.1 |
| `schemas/rtl_domain_approval.schema.json` | new |
| `scripts/quality_gate/rtl_quality_config.py` | `STANDARD_VERSION`, `GATE_CHECKS`, `REQUIRED_GATE_CHECKS`; both pins updated |
| `scripts/quality_gate/rtl_supplemental_policy.py` | approval record read and validated; domain result carries `approval_id` |
| `scripts/quality_gate/rtl_project_gate.py` | records `domain_approval_id` in the hashed result |
| `docs/rtl_coding_standard.md` | G2 description matches the policy again |
| `tests/test_rtl_supplemental_policy.py` | 6 approval tests |
| `tests/test_rtl_quality_config.py` | version/vocabulary tests; `_modified` now reaches content checks |

### Reviewed hashes

Independently verified by the project owner on 2026-11-14, using
`sha256sum` in their own shell. All three matched. This proves the published
values are the bytes on disk; it does not by itself assert that every line of
the policy change was read line by line.

For re-verification, from the tree that produced this entry:

```
9c7213df21a30f3485df82251f1f60e88cae1e67c7d4b973c2a39d183cfc90b1  config/rtl_quality_rules.json
301646222aa945d6e33a50aa874798a662ddb505c01d674fd666daa59f7abffc  config/rtl_quality_policy.json
e4825f9a73e1a6732bcd2d34b9813fd5ac0b95a1802a7958b7eea99cee9fc5ba  scripts/quality_gate/rtl_readability.py
```

`rtl_readability.py` is unchanged by this revision; its pin is carried forward
from the 2026-11-14 readability revision (rule set 2).

### Blast radius, measured

| Tree | Multi-domain? | Result |
|---|---|---|
| `projects/cgra_bitnet_158/…/g1_probe` | yes (2 clocks, 2 resets) | PASS. Approval binds `sha256:b4018aa2…`; record id `sha256:243a773c…`. Report `evidence/gate_v7_standard11_20261114.json`, `evidence_id` `sha256:24d5087f…`. |
| `projects/Lut3D/Lut3D-master` | yes | Already fails G0 with a source-inventory mismatch before the domain check is reached. Status unchanged by this revision; not modified. |
| `examples/rtl/counter` | no | `NOT_APPLICABLE`. |
| `.vibesilicon/deliverables/LUT3D_KV260_delivery_20261111` | frozen snapshot | Not re-run. A delivery package records the standard it was built under. |

### Verification

- `python -m unittest discover -s tests -p "test_*.py"` — 514 tests, OK, 4 skipped (was 507 before this revision).
- `rtl_project_gate` re-run on the G1 probe manifest: G0/G1/G2 PASS, `evidence_id` `sha256:24d5087f…`.
- The run-level `evidence_id` moved (`c1c16e32… → 24d5087f…`) because `domain_approval_id`
  entered the hashed result. The `unified_evidence_id` did **not** move
  (`d3747d82…`): the supplemental block is not part of the bundle, so the
  bundle alone still cannot tell an approved run from an unapproved one. The
  approval is carried in the run report, not in the unified bundle.

### Found while making this change

`tests/test_rtl_quality_config.py::_modified` built an edited copy of a reviewed
file and expected `RtlQualityConfigError`. The copy failed the **byte pin**, not
the content rule under test — so those tests would have passed with every
content check deleted. `_modified` now pins the temporary file's own hash, and
the assertions reach the rules they name.

Fixing that exposed a second false claim. `_modified`'s first fix pinned *both*
files to the temporary copy's hash, which made `load_policy` fail while loading
the real catalog — still the wrong error. With that corrected, one assertion
turned out to test behaviour that did not exist: `tool_versions` was validated
for **structure** only (`accepted_major` a non-empty list of positive ints), so
`verilator: [6]` was accepted. The byte pin alone would still have permitted it
after a hash update. `TOOL_VERSIONS` now states the reviewed values in code and
`load_policy` requires equality, matching the existing `LEGACY_THRESHOLDS`
pattern. Verified by loading edited copies past the pin: dropping
`domain_approval`, misspelling a check name, moving `wns_ns_fail`, changing the
activation round, and moving the Verilator major all now reject with a specific
message, while an unmodified copy loads.

### Not covered

- `rtl_quality_waiver.schema.json` and `rtl_quality_signoff.schema.json` keep
  `standard_version` `1.0`. They version their own artifact contracts, are not
  bound to this standard version in code, and three live waiver files exist.
  Changing them would invalidate artifacts without adding a check.
- The gate enforces **independence from the generator**, not **humanity of the
  approver**. A record whose `approved_by` is another agent passes. "Who may
  sign" is a procedural rule; this revision does not and cannot make it
  mechanical, and should not be described as if it did. What it does enforce is
  that the evidence's generator is not also its approver, that the approval
  names one instant and one evidence id, and that the approver said what the
  approval covers and what it does not.
- This revision adds no check that the approved scope was technically correct.
  It binds a decision to evidence and to a named person. It does not read the
  RTL.

### Authority

Revision requested by the project owner on 2026-11-14 and implemented by
`claude-code-agent`. The owner independently recomputed the three hashes above
in their own shell on the same day and they matched; that is the approval step
for this entry. The revision becomes load-bearing from the first gate run under
standard 1.1 (recorded above).
