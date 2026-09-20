# Security policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use the repository's private security advisory feature and include affected versions, reproduction steps, impact, and any suggested mitigation.

## EDA and agent safety

- Run licensed EDA tools only on a host you control and only for trusted commits.
- Never attach a self-hosted runner to untrusted pull-request execution.
- Inject licenses and credentials through the host environment or an approved secret manager; never commit them or include them in evidence.
- Review generated Tcl and external process invocations before enabling write-capable tools.
- Treat PDKs, rule decks, customer designs, logs, and generated implementation data as potentially confidential.
- Use a disposable workspace and least-privilege account for automated runs.

Portable CI intentionally avoids licensed EDA execution and does not provide production sign-off.
