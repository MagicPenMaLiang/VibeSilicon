# Independent control-arm authoring worksheet — trial kv260-video-2026-11-10

**You are the independent control author.** You are not the scorer and you did not
write any other decision in this trial. Write one **control-arm** decision for each
scenario below.

**What "control arm" means:** the diagnostic decision a competent engineer would
make for this scenario **without consulting any case catalog or prior-case
library**. Write what you would genuinely conclude and do next. Do **not** soften,
hedge, or add caveats on our behalf — if your honest first pass is a confident
conclusion, write that. One short paragraph each: state the failing layer, the next
experiment, and any stop/authorization call.

**Do not read `decisions.blind.json`, `plan.json`, or the treatment arms before
writing.** Write cold, from the scenario alone.

**Handling / confidentiality:** this worksheet maps each control decision to a blind
token. Like `plan.json`, it must be **withheld from the scorer**. After you fill the
four decisions, the trial custodian (not the decision author, not the scorer) pastes
each into `decisions.blind.json` at the matching `blind_token`, replacing the
placeholder. The scorer then receives only the completed `decisions.blind.json`.

---

## Scenario A  → blind_token `8ca06a73ee33a5956448f82ad69d3849`

Sustained NV12 playback drops frames under load. The custom RGBx packer stage
appears to serialize. State the failing layer and the next experiment.

**Your control decision:**
```
Failing layer: throughput in the pixel path, most likely backpressure at the
RGBx packer or its downstream memory interface. "The packer serializes" is a
symptom, not a settled cause; I would not assert it yet. Next experiment:
instrument per-stage occupancy and stall reasons (packer in/out FIFO levels,
AXI burst length and wait states, source vs sink rate) and replay one static
frame at the same clock, then replay with the packer replaced by a passthrough.
That pair discriminates packer-internal serialization from DDR bandwidth or
upstream/downstream contention. Stop/authorization: do not re-architect the
packer or claim sustained playback until the counters identify the limiting
stage; a pass here is a board measurement, not a readiness result.
```

---

## Scenario B  → blind_token `8e4804539812a3b3337b87f0ff46fa48`

The output image is shifted and cropped. The suspicion is a geometry/stride
miscalculation in scanout. State the failing layer and the next experiment.

**Your control decision:**
```
Failing layer: pixels/geometry — the scanout rectangle, base address, pitch or
active width/height, or a mismatch between the producer's buffer geometry and
what scanout assumes; not the transport protocol. Next experiment: drive scanout
with a known pattern (distinct corner markers and a one-pixel border) through the
same buffer layout, and compare the observed offset/crop against the programmed
stride and active dimensions; then bypass the LUT3D/custom stage and repeat. The
second run discriminates a scanout-side geometry error from an upstream producer
writing at the wrong pitch. Stop/authorization: do not nudge the display plane or
rescale to hide the symptom, and do not sign off image quality, until the
stride/offset formula and both ends' geometry contracts are checked against the
actual buffer.
```

---

## Scenario C  → blind_token `8904a258ccea5a0b3a29a1de07888429`

A single-bank DDR containment test passes. Decide whether that proves the silicon
data path is correct.

**Your control decision:**
```
No — it does not. A single-bank containment pass proves only that one bank, over
one address subset and one traffic pattern, returns correct data. It says nothing
about the other banks, address decode across the full range, bank-conflict
behavior, crossbar/QoS arbitration under concurrent clients, or sustained
full-rate bandwidth. Next experiment: extend the identical test to every bank,
then run randomized/interleaved addresses across banks with concurrent read and
write at the target rate, checking data integrity rather than pass/fail, plus
per-bank throughput and latency counters; the failure pattern there separates an
address-decode fault from an arbitration/bandwidth limit. Stop/authorization: a
single-bank pass is not silicon data-path validation and must not be used to
authorize live playback or claim readiness.
```

---

## Scenario D  → blind_token `0ddd2551093dc2405ab9a494555591a8`

At end-of-stream the presentation of the final frames is uncertain and teardown
races with the last DRM submit. Decide whether the run's tail frames counted as
presented.

**Your control decision:**
```
Failing layer: the evidence/recovery boundary at EOS teardown, not the render
path. If teardown can race the last DRM submit, a missing presentation record for
the tail frames is an artifact of the race, so I cannot count them as presented;
they are at most "unknown". Next experiment: add a deterministic EOS barrier —
quiesce the producer, wait for the flip-done/vblank completion event of the final
submitted buffer(s) before teardown, and log submit-to-flip-done pairs from the
kernel side — then replay and check that every submitted tail buffer has a
matching completion event. Stop/authorization: report the tail frames as not
counted (or excluded) unless a completion event proves presentation; do not claim
full-frame delivery from a run whose teardown raced the last submit.
```
