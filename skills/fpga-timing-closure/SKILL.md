---
name: fpga-timing-closure
description: Apply a controlled single-hypothesis timing change after read-only diagnosis, with guardrails and rollback.
license: Apache-2.0
metadata:
  version: "1.0.0"
  category: optimization
  routes: [fpga]
---

# FPGA timing closure

## Preconditions

Require content-addressed post-synthesis or post-route timing evidence, a classified critical path, functional guardrails, target metrics, allowed files, and human approval for RTL/XDC/strategy changes.

## Experiment

1. State one causal hypothesis.
2. Capture the immutable baseline and rollback point.
3. Modify only the approved files.
4. Run functional, protocol, CDC, formal, synthesis, and implementation gates in order.
5. Compare WNS/TNS, resources, power, runtime, and non-regression limits.
6. Accept, reject and rollback, or mark inconclusive.

Broad false paths, wildcard clock groups, unjustified multicycle paths, threshold relaxation, and removal of failing checks are prohibited.

See `references/constraint_policy.md` and `templates/optimization/experiment.json.tpl`.
