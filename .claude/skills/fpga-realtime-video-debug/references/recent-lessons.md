# Reusable debugging lessons and their limits

This reference describes experimental methods. It contains no board qualification
results and does not depend on unpublished project runs, private analysis files,
CPU assignments, priority values or timing compensation settings.

| Failure pattern | Useful method | Limit on the conclusion |
|---|---|---|
| A display-wait guard stops before an endpoint sample | Retain the unknown interval; count started, completed, published and verified frames separately | Do not invent a timeout value or count unpublished frames as verified |
| Extra observation overlaps a failure window | Remove one observation source to test whether it is a necessary cause; keep other observer load explicit | Quiet execution does not exclude every source of interference |
| Snapshot release exceeds its limit and the parser fails on the stop path | Replay raw records through the actual parser stop path before rerunning hardware | Parser failure must not erase the application's deadline failure; a pre-submit stop may have no final DRM event |
| A timestamp lies close to an integer deadline | Compare original integer times and separate wakeup, dispatch and return with precision limits | Do not round a failure into PASS or infer continuous execution from two endpoint thread names |
| Startup stops before video begins | Reproduce actual thread creation, identities, helper processes and READY ordering | A pre-video harness failure is not an algorithm/display result; do not fabricate missing board thread IDs |
| Offline integration replaces target facilities with fixtures | Track which production combinations are real and which capabilities are substituted | An offline test or previous board approval is not evidence that a new board run completed |

Classify the failing layer, use falsifiable experiments and verify the observer.
If the platform cannot support the required timing argument, propose a reviewed
architecture decision. These methods do not establish a 1 ms guarantee or a
universal CPU-tuning recipe.
