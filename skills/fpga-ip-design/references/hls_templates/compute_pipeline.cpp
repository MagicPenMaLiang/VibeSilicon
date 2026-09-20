// TODO 占位（Phase 0 D5 填）
//
// 计算型流水线模板（Compute Pipeline）
// 适用：MAC/向量乘加/卷积等计算密集场景
// 计划 §6.1.1 references/hls_templates/compute_pipeline.cpp

#pragma once
#include "hls_stream.h"
#include "ap_int.h"

template<int W>
ap_int<W+4> compute_pipeline(ap_int<W> a, ap_int<W> b, ap_int<4> c) {
#pragma HLS PIPELINE II=1
    // TODO: 乘加 / 累加 / 饱和截断
    ap_int<W+1> mul = a * b;
    ap_int<W+4> acc = mul + c;
    return acc;
}
