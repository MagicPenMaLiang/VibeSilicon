// Neutral identity-stream example; no algorithm or interface substitution.
// Transfers exactly n words, blocking on input/output. Reset is external.
// A requested II=1 remains subject to synthesis report verification.
#pragma once
#include "hls_stream.h"
#include "ap_int.h"

template<int WIDTH>
void basic_pipeline(hls::stream<ap_uint<WIDTH>>& in,
                    hls::stream<ap_uint<WIDTH>>& out, unsigned n) {
    static_assert(WIDTH > 0, "positive word width required");
    for (unsigned i = 0; i < n; ++i) {
#pragma HLS PIPELINE II=1
        out.write(in.read());
    }
}
