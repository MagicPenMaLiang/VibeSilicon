// TODO 占位（Phase 2 W4 填，EOTF 查表实例驱动）
//
// LUT 流水线模板（LUT Pipeline）
// 适用：BRAM/URAM 查表 + Pipeline，典型场景 stream-processing EOTF
// 计划 §6.1.1 references/hls_templates/lut_pipeline.cpp
// 计划 §4.3 选择 EOTF 查表模块的原因
// 计划 §4.6 BRAM 资源危机缓解策略（8 项）

#pragma once
#include "hls_stream.h"
#include "ap_int.h"

template<int ADDR_W, int DATA_W>
void lut_pipeline(hls::stream<ap_uint<ADDR_W>>& addr_in,
                  hls::stream<ap_uint<DATA_W>>& data_out,
                  int n) {
    // TODO: URAM 迁移 + 分块 PARTITION 优化
    ap_uint<DATA_W> lut[1 << ADDR_W];
#pragma HLS RESOURCE variable=lut core=RAM_1P_URAM  // 优先 URAM
    // ... LUT 初始化 ...

    for (int i = 0; i < n; i++) {
#pragma HLS PIPELINE II=1
        ap_uint<ADDR_W> addr = addr_in.read();
        data_out.write(lut[addr]);
    }
}
