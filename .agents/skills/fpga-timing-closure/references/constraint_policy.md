# Timing-constraint change policy

Block proposals that:

- Add false paths to all registers or entire port groups merely to remove negative WNS.
- Use asynchronous clock groups without proof of the clock relationship and CDC design.
- Specify multicycle setup without the corresponding hold N-1.
- Use broad wildcards without known object match counts.
- Compare only WNS while omitting unconstrained paths, hold, CDC, function and resources.

An exception entering review must identify exact from/to objects, match counts,
design intent, CDC/protocol/interface proof evidence IDs, before/after exception
coverage reports and G2/G3/G4 revalidation. The coder proposing the change cannot
approve their own evidence.
