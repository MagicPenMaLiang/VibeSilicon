// TODO 占位（Phase 0 D5 填）
//
// 基础流水线模板（Basic Pipeline）
// 适用：单层 for 循环，II=1 目标，无依赖数据
// 计划 §6.1.1 references/hls_templates/basic_pipeline.cpp

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
        // TODO: 用户算法逻辑
        out.write(x);
    }
}
