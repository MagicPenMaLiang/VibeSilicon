# Pipeline isolation and hardware diagnosis

## Establish the path contract

For each boundary record active dimensions/crop, rational frame rate, progressive
or interlaced mode, format/component order, bit depth, PPC, stride, plane offsets,
padding, color space/matrix/range, clocks/resets, backpressure and drop/repeat policy.
Distinguish a live source that cannot pause from a throttleable decoder that can
produce bursts and reordered frames.

Pixels per beat and bits per component are different parameters. For widths not
divisible by PPC, use the declared tail-lane rules. Do not assume TKEEP on every
video interface or change golden packing to conceal an implementation error.

Calculate capacity before measurement:

- Active demand is `W × H × fps`; sustained compute includes clock, PPC, II,
  pipeline fill/drain and actual stalls, not just pipeline depth.
- Display pixel clocks include total geometry and blanking. An active-video AXI
  stream can still require instantaneous supply above average active-pixel demand.
- Sum actual plane stride/rows and reads/writes per frame, including decode, PL,
  scanout, CPU copies and snapshots. Measure available bandwidth and worst service
  gaps rather than comparing only nominal DDR peak bandwidth.
- Size FIFOs for bounded bursts/service gaps. Finite buffering cannot indefinitely
  absorb a persistent 60 fps input versus 59.94 fps output; use the contract's
  synchronization, throttling or frame drop/repeat policy.

## Select one isolation boundary

These are diagnostic options, not a mandatory sequence. Use existing authorized
connections; the table does not authorize hardware changes.

| Boundary | Input and observation | Evidence and remaining limit |
|---|---|---|
| Known pattern to display | Frame/coordinate-tagged bars or grid, TX state and external receiver | Display configuration/output, not source, DDR or algorithm correctness |
| Input/decode to memory | A few buffers with explicit ownership; format, order and boundary counts | Source/decode evidence; a memory dump does not prove display |
| Known frame through IP to memory | Fixed vectors and per-pixel golden comparison; first differing coordinate/channel/value | Numeric/packing evidence; a static frame does not prove sustained throughput |
| Input through an existing bypass to display | Preserve normal buffer/fence path and observe order/queues | Separate algorithm and shared-path hypotheses; bypass can change latency, bandwidth and current |
| Input through DDR to display | Write completion, read ownership, release and FIFO occupancy | Storage/clock decoupling; buffer count does not establish ownership |
| Full path to fixed acceptance | Original media, load, duration and all thresholds | Acceptance only within this contract and evidence scope |

Direct RX-to-TX is meaningful only if timing, rates, backpressure and elasticity
permit it. Matching resolution and nominal rate do not phase-lock independent
clocks. Otherwise use an existing safe observation point or frame-store path.

## Establish competing explanations

| Symptom | First discriminating observations | Unsupported immediate fix |
|---|---|---|
| Black screen | Work from the last good boundary: handshakes/frame counts, DMA, scanout, training and receiver lock; retain first error | Changing resolution, clocks, reset and format together |
| Freeze after a few frames | Last complete line/frame, blocked reads/writes, FIFO state and wait dependencies; distinguish short frames, HLS waits and held buffers | Setting every FIFO depth to algorithm latency or adding dummy pixels blindly |
| Tearing | Match displayed frame/buffer generation, producer completion, flip and release; check writes during scanout | Treating triple buffering alone as a verified repair |
| Periodic jitter/loss | Long-term rates, queue trends, PTS, decode reorder, DDR stalls and scheduling tails | Hiding a sustained rate mismatch with average fps or larger buffers |
| PPC-periodic artifacts | Lane indices, single-pixel impulses, diagonals, checkerboards and boundary patterns | Reversing pixel order before establishing the contract |
| Color shifts/highlight wrap | Constant components, ramps and extremes; independently check matrix, range, signedness, rounding and saturation/wrap | Adding clamp and changing frozen numeric behavior |
| Flicker or retraining when processing starts | Throughput/backpressure, CDC/timing, shared bandwidth and link status before power/signal measurements | Declaring IR drop from appearance or adding dummy switching activity |

HLS fork/join FIFO demand depends on production/consumption order and bursts,
not a single latency constant. Use actual DATAFLOW channels, occupancy and blocked
points in co-simulation, including full/empty and branch-rate mismatch. Algorithm
and protocol contracts define line-buffer drain and borders; dummy input can
contaminate the next frame and needs prior verification.

## Clocks, resets and the physical link

Review generated clocks, interactions, IO constraints and unconstrained paths.
Nonnegative WNS/WHS describes analyzed paths, not missing CDC safety. Combine
structural CDC with reset-release, asynchronous-FIFO and configuration-handshake
functional evidence. Route changes to rtl-cdc, fpga-constraints or fpga-timing-closure.

Use actual PLL/CDR, reference clock, reset order, training and error counters.
Do not assign the same ECC/CRC semantics to HDMI, DP and MIPI. For scopes/receiver
analyzers record probe points, bandwidth, trigger, alignment and capture loss.
Power hypotheses need correlated voltage/timing evidence; dummy activity is not
a substitute for power-delivery analysis.

## Retain reusable evidence

Record failure signature, first-error evidence, competing hypotheses, discriminating
experiment, repair and applicable versions/limits. Preserve the minimal triggering
vector/startup combination. Recheck fixed-point extremes after numeric repairs and
full-path throughput/deadlines after stall or buffering repairs. Do not generalize
a single project outcome into a board-wide tuning rule.
