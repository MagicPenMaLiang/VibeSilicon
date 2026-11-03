# Fixed-point implementation contract

For every value record signedness, width, fractional scaling, legal range, rounding and overflow/saturation mode. Derive full precision before a reviewed narrowing point: a product generally needs the sum of operand widths, while a sum may require growth determined by bounds. These are derivation aids, not permission to change the frozen contract.

Check SystemVerilog expression sizing and signed/unsigned mixing explicitly. Extend operands before arithmetic, document arithmetic versus logical shifts, and place casts/slices at declared quantization boundaries. Match ties, negative rounding and saturation order to the immutable golden model.

HLS types must implement the same contract rather than default C integer behavior. Preserve intermediate widths and avoid undefined signed overflow. Test boundary values, negative extremes, ties, saturation, zero and multi-stage accumulation.

If the contract lacks a numeric decision, stop for architectural review. Compare output vectors bit-for-bit; a width-saving optimization needs reviewed requirements and new acceptance, not an edited golden reference.
