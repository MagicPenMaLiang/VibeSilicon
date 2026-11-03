# Synchronizer implementation evidence

Use ASYNC_REG only on reviewed synchronizer stages; the attribute does not establish event delivery or data coherence. Keep combinational logic out of the metastability-catching path. Avoid fanout from the first stage and keep destination stages physically close where the target supports it.

Document destination frequency, data transition rate, chosen stage count, target MTBF and technology assumptions. Two stages are a common structure, not a universal reliability guarantee. For ASIC, use the reviewed library cells and placement/sign-off flow rather than FPGA properties.

Reset assertion/deassertion is a separate crossing contract. Prove destination reset release and startup behavior; do not assume a resettable synchronizer is valid for every target.

Check synthesized cells, retained attributes and placement alongside report_cdc. Use simulation/assertions for minimum event spacing and handshake behavior. Structural recognition alone is insufficient. Bind results to source/checkpoint hashes and tool version.
