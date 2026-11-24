# KV260 Video Bring-up: Evidence, Reversals, and Transferable Lessons

**Date:** 2026-11-10

**Audience:** James and future hardware/video bring-up teams

**Scope:** LUT3D video-path learning through the r117 demonstration

## Executive assessment

The useful outcome was not a single fix. It was a progression from making board
operations safe, through reconciling interfaces and timing, to separating
software records, sampled data checks, and an actual person's view of the panel.
Each addresses a different failure mode; none should be substituted for another.

The r117 record reports that James accepted the observed scheduled LUT/bypass
effect on their own demo content. The demonstrated workload was H.264 4K30,
looping a **60-frame excerpt**, not playing the complete original video. The
record reports 18,000 completed frames and 32 sampled snapshots matching the
scheduled reference. It does not establish per-frame physical measurement,
instrumented sink acceptance, H.265 functionality, or a full G1 pass. [S7]

**Evidence boundary.** This is a retrospective of the cited historical source
records, not evidence of a current hardware run. Some project sources may be
ignored and absent from a clean checkout; historical-source references may need
private evidence. Assertions below are attributed to those records, not to an
independent examination of their underlying raw evidence. No raw evidence is
reproduced here.

## Stages and what changed in the reasoning

| Stage | Evidence and change in understanding | Decision or remaining boundary |
|---|---|---|
| Early safety / static pixels | Static injected RGB pixels were a useful isolated input, but were not the decoder's NV12 output. The r58 review also identified a mismatch between the VPSS address contract and the implemented address map. [S1, Findings 1–2] | Keep safe one-vector probes and verify address maps across design, device tree, and driver before hardware access. A static-pixel success does not validate a decoded-video path. |
| First-frame / steady-state / teardown | r60 recorded a started transfer that did not complete at the first-frame deadline; r75 later recorded callbacks arriving after the deadline. r109 separately recorded a completed long run, cooperative stop, and drained finalizer. [S2, `diagnostic_verdict`; S3, `outcome`; S4, `outcome`] | Treat startup, sustained frame budget, and end-of-stream resource release as separate contracts. A timeout alone does not identify which contract failed. |
| Format / topology | r58 restored the required NV12-to-RGB VPSS path. r112 reported that snapshots matched the deployed reference while the observed panel colours were wrong; the deployed RGB565 word order disagreed with the reviewed display interpretation. [S1, Finding 2 and Decision; S5, `colour_investigation`] | Check each interface's planes, colour conversion, channel order, packing, and consumer interpretation independently; agreement with a mis-specified reference is not correctness. |
| Throughput | r75 reported 55.1 ms per 4K frame against a 33.333 ms budget and attributed the rate limit to the serialized packer; its proposed gapless packer had offline value and rate checks. [S3, `outcome.timing_root_cause`] | Budget pixels per cycle and backpressure at every stage; distinguish an offline candidate fix from a subsequent board result. |
| Golden / physical | r109 recorded 18,000 frames and 32 snapshots but a black panel; r112 recorded a visible image with wrong colour and contours despite matching snapshots. [S4, `physical_observation` and `gates`; S5, `operator_observation` and `colour_investigation`] | A host-side match, a visible panel, accurate colour, and a measured sink are different claims. Observe and test each separately. |
| Demo acceptance | r117 records a scheduled alternating effect, 18,000 completed frames, 32/32 schedule-selected snapshot matches, and James's positive observation. [S7, `scheduled_toggle_evidence`, `frames`, `physical_visual_acceptance`] | Accept the observed demonstration at its actual scope; retain the independent sink and broader gate limitations. |

## Earlier milestones: timing and ownership

The fixed RGB DMA test reported three complete 4K frame comparisons covering
bypass, enabled processing and SOF disable. Its original trial still stopped on
a provider-reference check; a subsequent successful recovery did not rewrite
that trial into a pass. Readiness, table loading, pixel comparison and recovery
are separate claims. [S8]

The early throughput record separated a roughly 20.815 ms DMA interval from a
249.495 ms CPU snapshot copy of 33,177,600 bytes. The copy alone exceeded the
33.333 ms frame budget. This localized that rejection without proving an
uncached-memory mechanism or blaming LUT arithmetic. [S9]

Later full-length runs exposed different lifecycle boundaries: V38 completed
frames before its out-fence failure; V43 demonstrated a separate two-phase
stop-display component; V45 reached decoder Idle with output ownership still
outstanding. The V46 first-commit investigation then failed before reaching the
Idle question. These component results cannot be added together to claim one
successful full-chain run. [S10]

The EOS ownership investigation reproduced an outstanding-output signature and
changed the policy to stop returning output after the EOS access unit was queued.
Its review retained uncertainty about the vendor's internal EOS ordering. Buffer
accounting and successful teardown require their own evidence, not longer
unexplained waits or forced buffer destruction. [S11]

## Root-cause reversals and limits

### A transfer can start and still time out

The r59 hypothesis that the write node never started was overturned by r60's
first-poll control sample: the node left idle immediately. Both sides were
still running at failure, and neither completion callback had arrived by the
snapshot. The same record suspected the restored read-side stream boundary,
but did not establish precisely when the island error arose. [S2,
`diagnostic_verdict.write_poll`, `hypothesis_updates`]

Later, r75 found the callbacks present and invoked approximately 21 ms after
the deadline, with the packer rate identified as the reported timing cause.
That later finding does not retroactively prove that every earlier timeout had
the same cause. [S3, `outcome.callback_chain`, `outcome.timing_root_cause`]

### Removing VPSS was withdrawn, not simplified into a fix

The r58 review withdrew the proposal to delete VPSS configuration after
reconciling decoder NV12 output with the actual hardware path. The earlier
RGBX assumption came from software-injected test frames; the decoded-video
path needed the conversion block. The review approved restoring the path and
aligning its address aperture, while explicitly retaining risk around the
then-unproven hardware configuration. [S1, Findings 1–2, Decision, Declared risks]

### Geometry was a hypothesis, not the final explanation

The r71 geometry hypothesis should not be presented as the final root cause.
The r78 record reports a completed frame after restoring the earlier 16-bit
geometry, while r75 identified a serialized-packing rate limit and a gapless
candidate fix. That counterexample undermines the claim that changing the
geometry was necessary for completion. It does not prove geometry can never
matter in other configurations. [S3, `outcome`; S12, `outcome`]

### A black panel is a symptom, not one diagnosis

r109 reported a black panel despite completed software records; it also recorded
a connected DisplayPort connector with display power off and an inactive CRTC
at a post-run observation, not during the failed presentation interval. r112
later recorded a visible image under a different run and
then exposed colour-order and quantization issues. This disproves any universal
claim that this lineage could never display an image; it does **not** establish
a single proven cause of the r109 black screen or prove every black screen has
the same cause. [S4, `physical_observation`; S5, `operator_observation`,
`colour_investigation`]

### Single-bank containment is not a silicon diagnosis

Using a single bank as a bounded way to reduce exposure is a mitigation, not
proof of a dual-bank silicon defect. The selected sources do not establish a
complete dual-bank causal chain. In particular, the r66 record retained a
failed sample-export path and an uncaptured transition while the milestone was
reduced to single-bank operation. [S13] Keep the bank-switching question open
until a separately designed, reviewed experiment identifies the failing boundary
and excludes software, sequencing, and observation alternatives.

## Eight transferable lessons

1. **Name the contract at every boundary.** Decode format, memory layout,
   stream timing, colour conversion, output packing, address map, and consumer
   format must agree. A valid contract at one boundary does not validate the
   next. [S1; S5, `colour_investigation.reference_layout`]
2. **Instrument the disputed event.** A start-state sample and callback timing
   separate “never started,” “still running,” and “finished too late.” Record
   when a sample was taken, not just its value. [S2, `diagnostic_verdict`;
   S3, `outcome.callback_chain`]
3. **Measure the rate-limiting stage.** Compare frame time and stage throughput
   to the fixed budget, then test value correctness and sustained rate separately.
   A correct but serialized stage can still miss every deadline. [S3,
   `outcome.timing_root_cause`]
4. **Make the golden independent of the same assumption under test.** A
   deployed expected word can match while the display decodes that word
   differently. Review the golden's layout and the consumer contract; retain
   both functional and visual checks. [S5, `outcome.note`, `colour_investigation`]
5. **Use an evidence ladder.** Offline checks, hardware completion, sampled
   in-memory comparisons, operator observation, and instrumented sink capture
   provide distinct evidence. Report what each actually establishes, including
   sample count and workload. [S3–S5; S7]
6. **Treat cleanup and observability as stateful resources.** r115's six
   pre-hardware stops included a trace phase that consumed the cold trace
   baseline before a later guard stopped execution. Cleanup of an owned trace
   instance did not restore that baseline. [S6, `attempts`, `root_cause`]
7. **Fail closed, then recover deliberately.** A preflight stop is not a
   hardware failure or pass. Identify residue, verify permitted removal, and
   re-establish the required baseline before a newly authorized attempt; do not
   use repeated retries as diagnosis. [S6, `attempts`, `recovery`, `next`]
8. **Preserve scope in the acceptance statement.** A looped 60-frame excerpt,
   schedule-selected snapshots, and James's visual acceptance are meaningful
   demonstration evidence, but not full-source coverage or physical measurement
   of every frame. [S7, `change`, `scheduled_toggle_evidence`,
   `physical_visual_acceptance`, `gates`]

## Open items and next evidence

- **Late vblank:** r117 reports zero vblank violations for its recorded run
  [S7, `frames`]. That does not close late-vblank behaviour under other loads,
  boundary conditions, or schedules. Define a reproduction, timing budget,
  instrumentation, and reviewed acceptance criteria before generalizing.
- **Dual-bank operation:** single-bank containment does not explain the
  underlying behaviour. Isolate control sequencing, data integrity, and
  switching timing with an independently reviewed test and explicit stop rules.
- **Physical sink:** r117's operator observation is positive, but the record
  retains instrumented sink acceptance as `BLOCKED` because no capture device
  was attached. A future sink test needs a verified capture path, identity,
  signal and colour criteria, and an appropriate temporal coverage statement.
  [S7, `physical_visual_acceptance`, `gates`]
- **G1:** `FAIL_RETAINED` is not a pass and cannot be cleared by the demo.
  Identify and close the specific outstanding G1 findings using the governing
  gate process; the selected outcome does not itself enumerate all remedies.
  [S7, `gates.full_G1`]
- **H.265:** deferred and not tested; do not infer codec coverage from the
  H.264 demonstration. It requires its own approved workload and evidence.
  [S7, `gates.h265`]

## Where the learning belongs

| Destination | Preserve | Avoid |
|---|---|---|
| Skill | General procedure for interface reconciliation, staged instrumentation, independent golden review, and bounded visual acceptance. | Turning this one board's hypotheses into universal rules. |
| Case study | The r58/r60/r75 and r109/r112/r117 reversals, decisions, and evidence limits; include pointers to authorized historical sources. | Reproducing private media or raw run material. |
| Gate | Machine-checkable design/address agreement, explicit time budgets, declared golden/consumer formats, distinct sample and sink acceptance statuses, and fail-closed baseline checks where applicable. | A single aggregate PASS that hides skipped, blocked, or retained failures. |
| Runtime record | Attempt-specific authorization, configuration, preconditions, state transitions, measurements, sample coverage, observer statement, cleanup, and explicit outstanding gates. | Treating a retrospective or a prior run as current-run evidence. |

These are recommended destinations, not claims that a skill or gate was changed
as part of this documentation task. Changes to hardware workflows require their
normal review and approval.

## Interpreting model effectiveness

This history does not support a causal ranking of AI models. Attempts differed
in inputs, tools, board state, instrumentation, human decisions, and accumulated
knowledge. Later success cannot be attributed to a model merely because it
occurred later. A defensible comparison would require matched tasks and context,
independent scoring, repeated trials, and disclosure of tool and human support.

## Historical sources

Paths below are repository-relative pointers to the specific records consulted.
The outcome JSON fields are claims in the historical records; their cited raw
artifacts were not independently checked for this retrospective.

- **S1:** `projects/Lut3D/Lut3D-master/docs/reviews/kv260_lut3d_variant_a_read_path_vpss_aperture_r58_design_review_20261029.md` — Findings 1–2, Decision, Declared risks.
- **S2:** `projects/Lut3D/Lut3D-master/analysis/kv260_h264_main_block_stack_v47_r60_outcome_20261030.json` — `diagnostic_verdict`, `hypothesis_updates`.
- **S3:** `projects/Lut3D/Lut3D-master/analysis/kv260_h264_main_block_stack_v47_r75_outcome_20261103.json` — `outcome.callback_chain`, `outcome.timing_root_cause`.
- **S4:** `projects/Lut3D/Lut3D-master/analysis/kv260_h264_main_block_stack_v47_r109_outcome_20261109.json` — `outcome`, `physical_observation`, `gates`.
- **S5:** `projects/Lut3D/Lut3D-master/analysis/kv260_h264_main_block_stack_v47_r112_outcome_20261109.json` — `outcome`, `operator_observation`, `colour_investigation`, `gates`.
- **S6:** `projects/Lut3D/Lut3D-master/analysis/kv260_h264_main_block_stack_v47_r115_outcome_20261110.json` — `attempts`, `root_cause`, `recovery`, `gates`, `next`.
- **S7:** `projects/Lut3D/Lut3D-master/analysis/kv260_h264_main_block_stack_v47_r117_outcome_20261110.json` — `change`, `scheduled_toggle_evidence`, `frames`, `physical_visual_acceptance`, `gates`.
- **S8:** `projects/Lut3D/Lut3D-master/docs/reviews/kv260_fixed_dma_v3_hardware_result_20261014.md` — fixed-frame comparisons and original stop/recovery distinction.
- **S9:** `projects/Lut3D/Lut3D-master/docs/reviews/kv260_rgb_memory256_throughput_v4_copy_deadline_result_20261014.md` — measured DMA/copy intervals and deadline.
- **S10:** `projects/Lut3D/Lut3D-master/docs/kv260_lut3d_board_validation_handoff_20261022.md` — V38/V43/V45/V46 lifecycle outcomes and first-commit interval.
- **S11:** `projects/Lut3D/Lut3D-master/docs/reviews/kv260_lut3d_decoder_output_ownership_s4_card_20261023.md` — output ownership signature, EOS policy and vendor-ordering limitations.
- **S12:** `projects/Lut3D/Lut3D-master/analysis/kv260_h264_main_block_stack_v47_r78_outcome_20261104.json` — `outcome`, restored geometry and frame completion.
- **S13:** `projects/Lut3D/Lut3D-master/analysis/kv260_h264_main_block_stack_v47_r66_outcome_20261103.json` — incomplete transition observation and single-bank milestone decision.
