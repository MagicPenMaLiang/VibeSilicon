# Proof modes and applicability

| Change | Preferred proof | Verification still required |
|---|---|---|
| Combinational expressions, constants, widths, signedness | Combinational equivalence | Lint, bit-exact golden comparison |
| Register restructuring, pipelines, state encoding | Sequential equivalence | Latency/protocol assertions and simulation |
| FSM, FIFO, arbitration, handshake | Property checking | Cover, simulation and synthesis |
| CDC, asynchronous reset | Property checking plus CDC analysis | Structural CDC and implementation reports |
| XDC only | RTL equivalence is not the relevant check | Timing, CDC and exception coverage |
| Vendor IP or encrypted netlists | Boundary properties/black-box contract | Vendor simulation models and implementation |

A bounded proof supports only a no-counterexample claim within depth N, not an
unbounded proof. Sequential equivalence must state reset mapping, initial states,
output alignment and permitted latency differences. Justify each assumption with
interface, protocol or environment evidence and a content-addressed evidence ID.
