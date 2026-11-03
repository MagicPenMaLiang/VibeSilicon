# CDC dispositions

| Crossing | Required mechanism | Functional obligations |
|---|---|---|
| Stable single-bit level | Reviewed synchronizer | Destination may observe delayed changes; no narrow-pulse guarantee |
| Event/pulse | Toggle, stretched pulse or request/ack | Minimum spacing, reset alignment, no loss or duplication |
| Coherent word | Stable data plus handshake or async FIFO | Data held until acknowledged; coherency and backpressure |
| FIFO pointer | Gray code with reviewed synchronizers | One-bit transition property, pointer skew bounds, safe full/empty |
| Reset release | Reviewed per-domain release | Recovery/removal and startup ordering |

For each crossing record source/destination clocks, reset, direction, width, expected rate, mechanism, structural findings, functional evidence and disposition. Unknown clocks, incomplete enumeration or inconclusive proof are BLOCKED.

A false path does not implement a synchronizer. An asynchronous clock group may override a max-delay bound; verify effective constraint precedence when selecting FIFO pointer skew/delay policy. Reset/CDC exceptions require independent human review.
