// Lookup example with caller-owned initialized storage; no hidden RAM contents
// or technology binding. The architecture declares the table port/latency and
// FPGA/ASIC storage wrapper. Inference and achieved II need report evidence.
#pragma once
#include "hls_stream.h"
#include "ap_int.h"

template<int ADDR_W, int DATA_W>
void lut_pipeline(hls::stream<ap_uint<ADDR_W>>& addr_in,
                  hls::stream<ap_uint<DATA_W>>& data_out,
                  const ap_uint<DATA_W>* table, unsigned n) {
    static_assert(ADDR_W > 0 && ADDR_W < 31 && DATA_W > 0, "legal widths required");
    // Caller guarantees a non-null table containing at least 2^ADDR_W entries.
    for (unsigned i = 0; i < n; ++i) {
#pragma HLS PIPELINE II=1
        ap_uint<ADDR_W> address = addr_in.read();
        data_out.write(table[address.to_uint()]);
    }
}
