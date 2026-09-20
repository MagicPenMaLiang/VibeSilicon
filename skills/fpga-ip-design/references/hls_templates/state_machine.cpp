// TODO 占位（Phase 0 D5 填）
//
// 状态机模板（State Machine）
// 适用：标准 FSM 模式（LLM 友好），如 SPI/UART/I2C
// 计划 §6.1.1 references/hls_templates/state_machine.cpp
// 计划 §3.2 Pilot 选择理由："标准 FSM 模式（LLM 友好）"

#pragma once
#include "ap_int.h"

template<int STATE_W>
ap_uint<1> state_machine(ap_uint<8> data_in, ap_uint<STATE_W>& state) {
    enum { IDLE, READ, WRITE, DONE };
    ap_uint<1> valid = 0;

    switch (state) {
    case IDLE:
        if (data_in != 0) state = READ;
        break;
    case READ:
        // TODO: 读数据逻辑
        state = WRITE;
        break;
    case WRITE:
        // TODO: 写数据逻辑
        state = DONE;
        break;
    case DONE:
        valid = 1;
        state = IDLE;
        break;
    }
    return valid;
}
