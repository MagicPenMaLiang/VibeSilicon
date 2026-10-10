// TODO: unfinished scaffold; review and verify before use.
//
// Basic pipeline template
// Scope: single loop with no data dependencies; II=1 is a request.
// Reference: references/hls_templates/basic_pipeline.cpp

#pragma once
#include "hls_stream.h"
#include "ap_int.h"

template<int WIDTH>
void basic_pipeline(hls::stream<ap_uint<WIDTH>>& in,
                    hls::stream<ap_uint<WIDTH>>& out,
                    int n) {
    for (int i = 0; i < n; i++) {
#pragma HLS PIPELINE II=1
        ap_uint<WIDTH> x = in.read();
        // TODO: project algorithm logic
        out.write(x);
    }
}
