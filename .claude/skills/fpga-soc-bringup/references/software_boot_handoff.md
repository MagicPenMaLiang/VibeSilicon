# Optional SoC software and boot handoff

Use only when an FPGA application includes a processing system. Pure PL RTL
development and ASIC targets do not acquire a Vitis software dependency.

Keep the chain explicit: implemented hardware export -> platform/domain ->
application -> boot image -> observed boot -> application/DDR/peripheral tests.
Bind XSA, clocks/address map, processor/domain/OS, BSP, tool release, software
sources and linker settings, ELF and packaging inputs by hash. Platform/application
creation is different from a successful build; a stub platform file is insufficient.
Require expected outputs and build logs as well as the exit code.

Use the selected release's Vitis platform/application tooling when available;
the current SoC adapter validates input plans only. Do not claim it generates
XSA, platform, FSBL, device tree, ELF or boot images. Missing build runners remain
an explicit limitation; this reference adds a handoff contract, not a Vitis API
or shell/Python execution MCP.

For a boot image record the exact family, boot mode, partition order, BIF,
bootloader/management firmware, application, PL image and any trusted software
required by that target. Zynq-7000 and ZynqMP require different components;
Versal/PDI is outside the current ps7/mpsoc adapter. Never invent load addresses,
DDR settings, keys or certificates. Reuse reviewed board/software inputs.

Packaging completion does not authorize flash or show cold boot. Use the existing
separate operation approval and exact-device/artifact binding for board writes.
Preserve serial boot logs, reset/power-cycle conditions, DDR test results, clock
measurements and application output comparisons. A successful FPGA DRC cannot
validate the processing-system preset or software cache/DMA ownership.
