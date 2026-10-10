# Technology wrappers for XPM CDC

XPM is a vendor implementation option behind a neutral target wrapper, not portable ASIC RTL. Declare the device/tool support and reviewed primitive parameters. Use the selected tool installation's primitive templates and documentation instead of assuming a stable parameter set.

Choose level synchronizers for persistent single-bit levels, pulse synchronizers only within their documented spacing/reset requirements, and handshake/FIFO primitives for coherent words. A Gray synchronizer requires a source representation with valid Gray transitions; it cannot repair arbitrary multi-bit data.

Record stage count, source registration, reset behavior, simulation assertions, latency and frequency assumptions. Compare wrapper behavior against the shared contract; review report_cdc and synthesis inference. Never suppress primitive assertion failures to make a run pass.

For ASIC use an independently reviewed equivalent wrapper with technology reliability evidence. Keep golden vectors and numeric behavior unchanged.
