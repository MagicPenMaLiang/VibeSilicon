// Full-precision signed multiply-add example: a*b + c, with no quantization.
// Reviewed product width is 2*W; one additional bit covers signed addition.
// Narrowing, rounding or saturation belongs to a separately reviewed contract.
#pragma once
#include "ap_int.h"

template<int W>
ap_int<2*W+1> compute_pipeline(ap_int<W> a, ap_int<W> b, ap_int<4> c) {
    static_assert(W >= 2, "product must cover the four-bit addend");
#pragma HLS PIPELINE II=1
    ap_int<2*W> product = a * b;
    ap_int<2*W+1> extended_product = product;
    ap_int<2*W+1> extended_addend = c;
    return extended_product + extended_addend;
}
