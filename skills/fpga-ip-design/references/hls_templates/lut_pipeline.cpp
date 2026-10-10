// TODO: unfinished LUT scaffold; initialization and verification are required.
//
// LUT pipeline template
// Scope: illustrative memory lookup; the LUT contents are not initialized.
// Reference: references/hls_templates/lut_pipeline.cpp
// TODO: document the accepted lookup function.
// TODO: review storage requirements for the selected device.

#pragma once
#include "hls_stream.h"
#include "ap_int.h"

template<int ADDR_W, int DATA_W>
void lut_pipeline(hls::stream<ap_uint<ADDR_W>>& addr_in,
                  hls::stream<ap_uint<DATA_W>>& data_out,
                  int n) {
    // TODO: review memory mapping and partitioning
    ap_uint<DATA_W> lut[1 << ADDR_W];
#pragma HLS RESOURCE variable=lut core=RAM_1P_URAM  // Illustrative URAM request; verify tool and device support.
    // ... LUT initialization is missing ...

    for (int i = 0; i < n; i++) {
#pragma HLS PIPELINE II=1
        ap_uint<ADDR_W> addr = addr_in.read();
        data_out.write(lut[addr]);
    }
}
