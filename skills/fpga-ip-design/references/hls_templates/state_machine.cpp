// Control-only four-phase example. Each call advances one phase; nonzero
// data_in starts the sequence and DONE pulses valid for one call. The caller
// initializes state to IDLE. This is not a serial or streaming protocol core.
#pragma once
#include "ap_int.h"

template<int STATE_W>
ap_uint<1> state_machine(ap_uint<8> data_in, ap_uint<STATE_W>& state) {
    static_assert(STATE_W >= 2, "four states require two bits");
    enum { IDLE, PHASE_A, PHASE_B, DONE };
    ap_uint<1> valid = 0;
    switch (state) {
    case IDLE: if (data_in != 0) state = PHASE_A; break;
    case PHASE_A: state = PHASE_B; break;
    case PHASE_B: state = DONE; break;
    case DONE: valid = 1; state = IDLE; break;
    default: state = IDLE; break;
    }
    return valid;
}
