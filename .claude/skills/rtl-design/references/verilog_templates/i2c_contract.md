# I2C requires a reviewed protocol core

The former empty i2c_slave module was not a functioning protocol template and
is removed. Select a separately verified core or implement one only after
reviewing an explicit interface contract and verification plan.

Declare address modes, read/write transactions, repeated START, STOP, ACK/NACK,
clock stretching, arbitration applicability, reset recovery and unsupported
transactions. Board pull-ups, voltage, filtering and sampling timing come from
board and bus specifications. Never infer them from an empty wrapper.

Keep open-drain IO primitives in the target-specific wrapper. Separate sampled
bus events and local control logic; review metastability and the relationship
between the sample clock and SCL. Prove edge ordering and glitch/filter behavior
under the declared timing assumptions.

Use an independent bus model and scoreboard for address/data, ACK/NACK,
repeated START, resets mid-transaction, stretching and illegal sequences.
Record source/configuration/tool hashes and raw simulation evidence. No I2C
implementation or compliance is implied by this checklist.
