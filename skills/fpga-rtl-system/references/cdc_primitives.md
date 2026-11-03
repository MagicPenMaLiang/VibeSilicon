# Portable crossing contracts

Separate crossing behavior from technology implementation. A wrapper contract declares source/destination clocks, reset assertion/release, transfer semantics, loss/coherency requirements, latency and backpressure.

A level synchronizer transfers a persistent one-bit state with variable latency. A pulse synchronizer must satisfy a minimum inter-event spacing. A handshake holds data until acknowledgement and must recover from reset according to the interface contract. An asynchronous FIFO needs independent pointer synchronization and reviewed full/empty and reset behavior.

Do not independently synchronize bits of a coherent bus. Do not feed combinational glitches into a level synchronizer or fan out its first stage. Avoid fabric clock gating; use enables or reviewed clock-control wrappers.

See the repository rtl-cdc skill for structural and functional evidence requirements. Simulate asynchronous ratios, phase shifts, reset sequencing and backpressure; use applicable formal properties. Keep FPGA and ASIC physical constraints separate.
