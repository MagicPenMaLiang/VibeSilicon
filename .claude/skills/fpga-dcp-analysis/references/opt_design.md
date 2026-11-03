# opt_design attribution before changing RTL or constraints

Use `analyze_opt_log` in Vivado MCP, or
`python -m scripts.vivado_opt_analysis RUN.log --root PROJECT_ROOT`.
The collector reads an existing log only; no Vivado installation is needed.

Logs often mix synthesis, linking, optimization, placement and routing. Scope
observations from `Command: opt_design` through `opt_design: Time`. Repeated runs
remain separate; a next command or EOF without the end marker leaves the run
incomplete. Message IDs and phase numbers alone do not identify the stage.

The collector returns line-numbered excerpts, completion/error markers, truncation
flags and a hash of the original bytes. COLLECTED means log scopes were extracted;
it does not mean the command succeeded, timing closed, or the report matches the
current source. Bind the run receipt/source/configuration before accepting a claim.

Investigate retarget/propagation/sweep statistics, failed RAM/SRL/DSP inference,
control-set merging and constrained-object diagnostics. Treat DONT_TOUCH and
MARK_DEBUG as possible blockers only when the exact cell/net and owning constraint
are evidenced. If the ordinary log lacks object attribution, propose a reviewed
diagnostic rerun with the selected tool release's debug logging; absence of a
message is not absence of a blocker.

Do not remove protection across the design: it may protect CDC structure, a
reviewed memory boundary or a debug requirement. Hand an evidenced, narrow change
to timing/resource optimization, preserve the baseline, then repeat functional,
CDC, timing and relevant implementation checks. Any candidate directive must exist
in the selected Vivado version; a copied upstream directive name is not evidence.
