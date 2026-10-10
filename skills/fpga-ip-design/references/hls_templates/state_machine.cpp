// TODO: unfinished scaffold; review and verify before use.
//
// State machine template
// Scope: illustrative FSM; this is not a complete peripheral protocol.
// Reference: references/hls_templates/state_machine.cpp
// TODO: define reset, illegal-state recovery and the accepted state contract.

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
        // TODO: read data logic
        state = WRITE;
        break;
    case WRITE:
        // TODO: write data logic
        state = DONE;
        break;
    case DONE:
        valid = 1;
        state = IDLE;
        break;
    }
    return valid;
}
