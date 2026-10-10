// TODO: unfinished scaffold; review and verify before use.
//
// Compute pipeline template
// Scope: illustrative multiply-add scaffold; numeric widths are not validated.
// Reference: references/hls_templates/compute_pipeline.cpp

#pragma once
#include "hls_stream.h"
#include "ap_int.h"

template<int W>
ap_int<W+4> compute_pipeline(ap_int<W> a, ap_int<W> b, ap_int<4> c) {
#pragma HLS PIPELINE II=1
    // TODO: multiply-add / accumulation / reviewed overflow policy
    ap_int<W+1> mul = a * b;
    ap_int<W+4> acc = mul + c;
    return acc;
}
