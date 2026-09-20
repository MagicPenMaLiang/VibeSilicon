# RTL coding standard

## Structure

- One primary synthesizable module per source file; file and module names match.
- Separate synthesizable logic, memory abstraction, technology-specific wrappers, assertions, and testbench code.
- Do not mix inferred arrays with vendor or foundry macro instantiations in the same behavioral module.
- Use explicit module contracts for purpose, clocks, resets, interfaces, numeric behavior, latency, throughput, and invariants.

## Language and intent

- Use ``default_nettype none`` for synthesizable SystemVerilog and restore it only where integration requires it.
- Declare widths and signedness explicitly. Size constants and intermediate arithmetic deliberately.
- Use `always_comb`, `always_ff`, and `always_latch` according to intent; avoid mixed blocking/nonblocking assignments.
- Provide complete assignments in combinational logic and deterministic reset behavior where the architecture requires reset.
- Avoid simulation-only constructs, delays, force/release, and X-dependent behavior in synthesizable code.

## Clock, reset, and CDC

- A sequential block has one clock and one documented reset policy.
- Synchronizers, handshakes, and asynchronous FIFOs are explicit and reviewed.
- Multi-bit CDC data must use a coherent transfer protocol; synchronizing each bit independently is not acceptable.
- Timing exceptions must have narrow endpoints, justification, and independent evidence.

## State and protocol

- Enumerate states with explicit legal transitions and safe recovery behavior.
- Hold valid/data payload stable while backpressured when the protocol requires it.
- Assertions cover reset release, request/acknowledge, FIFO safety, and protocol invariants where applicable.

## Memory

- Keep memory behavior in a dedicated inferred-memory module or a target-specific wrapper.
- Document read latency, write mode, collision behavior, initialization, byte enables, and clocking.
- Do not assume FPGA initialization semantics for ASIC memory.
- Maintain behavioral models for target-specific macros and verify wrapper equivalence.

## Verification and review

- G0: manifest, provenance, path safety, and configuration completeness.
- G1: lint, readability, CDC-shape checks, and approved waiver validation.
- G2: elaboration, self-checking simulation, protocol assertions, mutation/fault checks, and formal verification as applicable.
- G3/G4: target synthesis, implementation or physical design, PPA evidence, and independent sign-off.

No required skipped, unavailable, inconclusive, or stale check is a PASS.
