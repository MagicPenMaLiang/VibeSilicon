# Debug learning: first increment requirements

Status: implementation baseline, 2026-11-10. This is a software/tooling increment,
not a hardware architecture approval or an authorization to operate a board.

## Problem

Video bring-up accumulated useful methods alongside retracted explanations,
private run dependencies and repeated package/state errors. Chat memory is not a
shared knowledge authority. Longer skills alone cannot prove better decisions.

## Users and outcomes

- Engineers can read a source-qualified retrospective without private assets.
- Agents can retrieve conditional cases and see missing context and counterevidence.
- Maintainers can replay portable positive/negative scenarios on a clean checkout.
- Engineers can check a declarative package plan and local state capture without
  running commands, connecting to hardware or changing the inputs.

## Acceptance

1. Six or more cases separate observation, interpretation, counterevidence,
   applicability, exclusions and unresolved questions. Extracted cases remain
   unreviewed; structural validation never promotes them.
2. Query distinguishes matching context, missing context and exclusions. An
   unknown mandatory condition is never a successful match.
3. A frozen synthetic scenario set tests both acceptance and rejection; reports
   explicitly state that no model A/B or hardware evaluation was performed.
4. Offline preflight detects naming, path/root, artifact hash/closure, boot and
   required-state mismatches. Missing/unknown state blocks satisfaction.
5. Every preflight result retains live-state verification, execution authorization
   and hardware validation as false, even when offline checks are satisfied.
6. New software has positive/negative unit tests, offline CLI integration tests,
   >=80% measured coverage and independent code/security review.
7. Canonical skill resources are synchronized; no private runs or assets are
   introduced into public source.

## Non-goals

No board access, live collector, actual package compiler/generator, automatic
cleanup/reboot, automatic case promotion, evidence authentication, automatic
optimization acceptance, model-performance ranking, RAG/database or MCP endpoint.
No changes to RTL, golden data, timing/acceptance thresholds, role permissions or
existing board approvals. The original trial executors are not migrated.

## Related documents

- [Architecture](architecture.md)
- [System design](system_design.md)
- [Technical design](tech_doc.md)
- [Task list](task_list.md)
- [Verification and limitations](verification.md)
- [Bring-up retrospective](../../reviews/kv260_video_bringup_retrospective_20261110.md)
