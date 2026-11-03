# RTL failure and tool-failure triage

## Establish the run contract

Declare backend, release, top, simulation mode and terminal acceptance condition.
Behavioral, post-synthesis functional and post-implementation timing simulation
are different claims. Timing simulation additionally needs matching libraries,
netlist and successful SDF annotation; a skipped SDF is not timing evidence.
Discover installations from declared paths, PATH and project settings rather than
scanning unrelated disks. A missing backend is BLOCKED, not permission to switch.

Record each selected test, seed and plusargs. Use bounded runtime or a proven
watchdog, and require compile/elaboration success, normal completion, an explicit
terminal test result, completion of all required cases and no unexpected fatal,
assertion failure or timeout. For a declared UVM backend inspect its final summary
as well as the transcript. A zero process exit alone cannot establish PASS.

## Localize the failure

Separate compile, elaboration, runtime/protocol, numerical mismatch and simulator
crash/library failures. Preserve the exact manifest, top, parameters, includes,
tool/library versions, seed, command/exit and first causal diagnostic. Later
unresolved modules or transaction mismatches may be consequences of that first
failure. Do not classify a simulator crash as a failing design assertion.

Separate design, testbench, environment, timeout and suspected tool failures.
Keep the complete transcript even when the handoff includes bounded excerpts.
Record every scoped diagnostic or its grouped count/location; calling a message
a cascade does not remove it from the evidence. Quote the first causal message
and, for runtime failures, its simulation time and transaction context.

For synthesis elaboration diagnostics, inspect the actual source at the cited
file/line with its include and macro context. Record severity and message ID from
the selected tool release; an imported message table is not a substitute for that
release's diagnostic. Apply the smallest contract-preserving correction and rerun
elaboration plus the applicable behavioral gate.

For AXI/stream assertions, identify the channel, failing time, transaction and
signals necessary to test the hypothesis. Preserve a short failing waveform when
it resolves timing/order ambiguity, and compare the same signal set after repair.
Waveforms supplement a self-checking scoreboard; they do not replace pass-token,
exit-code, reset, backpressure and numeric checks. No mandatory interactive pause
or GUI session is added for every test case.

For a ready/valid channel, compare accepted transfers, reset state, ordering,
backpressure stability and scoreboard latency. Capture a short interval before
and after the first mismatch with clock/reset, qualifiers, expected and observed
values. Check testbench races and unknown-state semantics before changing DUT
arithmetic. Preserve comparable failing/passing evidence after repair and rebuild
from changed sources; a stale elaborated snapshot cannot verify the fix.

## Research and reduce tool failures

When a tool/library crash appears version-specific, search the selected vendor's
release notes/Answer Records using the exact signature and version. Keep any
workaround narrow and reproducible. Do not change project RTL solely to suppress
an unconfirmed tool defect. Record the source URL/edition, applicability, change
and rerun result; an untested workaround remains a proposal.

Search with the causal message ID plus the distinguishing construct, failure
stage and release. The same crash signature can have several unrelated causes;
match the documented mechanism to the failing source rather than accepting the
first hit. Check affected and fixed-in releases against the actual installation.

If another licensed simulator is already available and selected for comparison,
keep source, parameters, language mode, libraries, stimulus and seed equivalent.
Different results are evidence to investigate, not a majority vote on correct HDL.
For an upgrade regression, isolate the version boundary without changing inputs.
Reduce an unresolved failure while preserving its signature and legal semantics;
retain dependencies and reproduction steps. Do not publish proprietary models or
send a vendor report without authorization. Missing licensed simulators or
compile_simlib libraries remain missing evidence.

## Coverage and activity boundaries

The built-in portable backend is still Verilator; this
playbook does not imply that XSim/UVM/third-party runners or coverage adapters
were added. Functional/code/assertion coverage must name the supported backend
and metric, with reviewed exclusions rather than a generic coverage PASS.

For a separately supported SAIF/VCD capture, declare hierarchy/object scope,
timescale, reset/warm-up and bounded measurement interval. Verify the file is
complete and has meaningful activity, and retain the independent functional
verdict. Dumping a waveform does not prove a representative power workload or
correct replay. Generated stimulus still needs its own oracle and watchdog.
