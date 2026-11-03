# Bounded experiment and convergence record

Copy the relevant fields into the project's existing analysis format. This is an analysis aid; unfilled fields cannot authorize execution. Avoid another parallel paperwork system if an existing run record can carry them.

## Before the experiment

- **Question:** one uncertainty whose answer changes the next decision.
- **Boundary:** offline replay, local composition, no-device diagnostic, component diagnostic, or unchanged acceptance.
- **Baseline:** source/binary/config/media/contract hashes; boot and relevant runtime identities for target work.
- **Observed fact:** first failing stage/event, units, limit and raw evidence location/hash.
- **Hypothesis and rival:** mechanism proposed; plausible competing mechanism still consistent with the evidence.
- **Changed variable:** one causal intervention; list instrumentation changes separately as confounders.
- **Expected signatures:** result supporting the hypothesis; result rejecting it; result that is inconclusive and why.
- **Measurement:** events, clock mapping/error, frame/slice join, trace window/completeness, counter semantics.
- **Cost and bound:** time, data, CPU/RSS/bandwidth overhead, number of attempts and early-stop rule, appropriate to the existing scope.
- **State and authority:** existing authorization reference, package identity, restoration criteria; document a new review only if the actual change requires it.

## After the experiment

- Record actual modifications, substitutions, stopped stage and original failure without reclassification.
- Verify relevant evidence hashes; distinguish verified bytes from summaries merely read.
- Compare predicted and observed signatures; mark hypothesis SUPPORTED, REJECTED or INCONCLUSIVE with the reason. Do not call an observational association a proven intervention result.
- Keep separate application, harness, evidence, recovery and physical-receiver statuses.
- State what uncertainty was removed. If none was removed, explain why a new run would obtain different information before scheduling it.
- Select the next decision: implement the supported fix, improve a specific measurement, request an architecture decision, obtain external evidence, or execute the already-approved unchanged acceptance package.

## Typical decisions

| Evidence | Supported action | Unsupported leap |
| --- | --- | --- |
| Reader thread exists before a sole-main-thread prerequisite | Reproduce actual startup order; fix the composition under applicable review | Tune FPGA timing or increase RT priority |
| Snapshot release exceeds its limit; wake-to-run dominates the observed tail | Investigate scheduling/preemption with exact thread and CPU identity | Claim the LUT datapath is too slow |
| Software thread seen at wake and dispatch endpoints | Keep it as a candidate source of interference; obtain interval evidence or a controlled intervention | Claim continuous execution or the exact kernel call |
| No terminal DRM event after a pre-submit abort | Analyze the snapshot/abort path independently | Discard all trace evidence or claim display success |
| More component tests pass but real startup is untested | Add production-composition coverage with explicit substitutions | Claim the board startup path passed |
| Golden memory samples pass, receiver capture absent | Preserve sampled correctness and physical-evidence BLOCKED | Claim no physical frame loss or tearing |

For repeated stochastic tails, compare equivalent duration/load and retained failures, not just time-to-first-failure from different workloads. Predeclare any repetition budget within authorization. A single successful run can satisfy its contractual sampled test; it does not establish a universal worst-case guarantee.
