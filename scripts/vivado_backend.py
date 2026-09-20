#!/usr/bin/env python3
"""Vivado backend protocol, native batch implementation, sessions and audit evidence."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from scripts.evidence_contract import (
    artifact_record,
    build_manifest,
    build_receipt,
    sha256_bytes,
    utc_now,
    validate_receipt,
)
from scripts.quality_gate.vivado_evidence import create_report_evidence


MAX_TIMEOUT_SECONDS = 7200
RISK_CLASSES = {"R0", "R1", "R2", "R3", "R4"}
FORBIDDEN_TCL = re.compile(r"(?im)^\s*(exec\b|file\s+(delete|rename)\b|open\s+[^\n]*\|)")


class BackendBlockedError(RuntimeError):
    """Raised when a requested backend capability is unavailable by policy."""


class VivadoBackend(Protocol):
    def discover_capabilities(self, probe: bool = True) -> dict[str, Any]: ...

    def start_session(
        self, workdir: Path, mode: str = "batch", gui: bool = False, tool_version: str | None = None
    ) -> "VivadoSession": ...

    def execute_tcl(
        self,
        session: "VivadoSession",
        command: str,
        risk_class: str,
        timeout: int,
        *,
        approved: bool = False,
    ) -> dict[str, Any]: ...

    def record_report_evidence(
        self,
        session: "VivadoSession",
        command_result: dict[str, Any],
        report_path: Path,
        kind: str,
    ) -> dict[str, Any]: ...

    def get_status(self, session: "VivadoSession") -> dict[str, Any]: ...

    def get_log_messages(
        self, session: "VivadoSession", severity: str | None = None, cursor: int = 0
    ) -> dict[str, Any]: ...

    def search_docs(self, query: str, vivado_version: str) -> dict[str, Any]: ...

    def stop_session(self, session: "VivadoSession") -> dict[str, Any]: ...


@dataclass(frozen=True)
class BackendCapabilities:
    schema_version: int
    backend: str
    backend_version: str
    available: bool
    vivado_version: str
    session_reuse: bool
    gui: bool
    waveform: bool
    ipi: bool
    remote_ssh: bool
    docs_search: bool
    telemetry: bool
    remote_connection: bool
    max_concurrent_sessions: int
    tools: tuple[str, ...]
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["tools"] = list(self.tools)
        return value


@dataclass
class VivadoSession:
    session_id: str
    owner: str
    workdir: Path
    session_dir: Path
    mode: str
    gui: bool
    tool_version: str
    started_at: str
    state: str = "ACTIVE"
    sequence: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


Runner = Callable[..., subprocess.CompletedProcess[str]]


class NativeVivadoBackend:
    """Root-confined native Vivado batch backend with immutable command evidence."""

    name = "native"
    version = "1.0"

    def __init__(
        self,
        *,
        root: Path,
        vivado_bin: str,
        settings_path: str | None = None,
        runner: Runner = subprocess.run,
        assume_available: bool | None = None,
        max_sessions: int = 1,
    ):
        self.root = root.resolve(strict=True)
        self.vivado_bin = vivado_bin
        self.settings_path = settings_path
        self.runner = runner
        self.assume_available = assume_available
        self.max_sessions = max_sessions
        self._sessions: dict[str, VivadoSession] = {}
        self._sessions_lock = threading.Lock()
        self._capabilities: BackendCapabilities | None = None

    def _inside_root(self, path: Path) -> Path:
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"backend path is outside project root: {resolved}") from exc
        return resolved

    def _command(self, arguments: list[str]) -> list[str]:
        if os.name != "nt":
            if self.settings_path and Path(self.settings_path).is_file():
                command = "source {} && exec {} {}".format(
                    shlex.quote(self.settings_path),
                    shlex.quote(self.vivado_bin),
                    " ".join(shlex.quote(item) for item in arguments),
                )
                return ["bash", "-lc", command]
            return [self.vivado_bin, *arguments]
        if not self.settings_path:
            return [self.vivado_bin, *arguments]
        command = f'"{self.vivado_bin}" ' + " ".join(f'"{item}"' for item in arguments)
        if Path(self.settings_path).is_file():
            command = f'call "{self.settings_path}" && {command}'
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command]

    def discover_capabilities(self, probe: bool = True) -> dict[str, Any]:
        if self._capabilities is not None and not probe:
            return self._capabilities.to_dict()
        if self.assume_available is not None:
            available = self.assume_available
        else:
            available = Path(self.vivado_bin).is_file() or bool(shutil.which(self.vivado_bin))
        version = "unknown"
        reason = None if available else f"Vivado executable not found: {self.vivado_bin}"
        if available and probe:
            try:
                result = self.runner(
                    self._command(["-version"]),
                    cwd=str(self.root),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    shell=False,
                )
                match = re.search(
                    r"Vivado\s+v?([0-9.]+)",
                    (result.stdout or "") + (result.stderr or ""),
                    re.IGNORECASE,
                )
                version = match.group(1) if match else "unknown"
                windows_batch_version_exit = (
                    os.name == "nt"
                    and Path(self.vivado_bin).suffix.lower() in {".bat", ".cmd"}
                    and result.returncode == 1
                    and match is not None
                )
                if result.returncode != 0 and not windows_batch_version_exit:
                    available = False
                    reason = f"Vivado version probe exited {result.returncode}"
            except (OSError, subprocess.TimeoutExpired) as exc:
                available = False
                reason = f"Vivado version probe failed: {exc}"
        self._capabilities = BackendCapabilities(
            schema_version=1,
            backend=self.name,
            backend_version=self.version,
            available=available,
            vivado_version=version,
            session_reuse=True,
            gui=False,
            waveform=False,
            ipi=True,
            remote_ssh=False,
            docs_search=False,
            telemetry=False,
            remote_connection=False,
            max_concurrent_sessions=self.max_sessions,
            tools=("execute_tcl", "get_status", "get_log_messages", "search_docs", "stop_session"),
            reason=reason,
        )
        return self._capabilities.to_dict()

    def start_session(
        self, workdir: Path, mode: str = "batch", gui: bool = False, tool_version: str | None = None
    ) -> VivadoSession:
        capabilities = self.discover_capabilities(probe=False)
        if not capabilities["available"]:
            raise BackendBlockedError(capabilities["reason"])
        if mode != "batch" or gui:
            raise BackendBlockedError("native backend currently supports batch sessions only")
        resolved_workdir = self._inside_root(workdir)
        with self._sessions_lock:
            active = [item for item in self._sessions.values() if item.state == "ACTIVE"]
            if len(active) >= self.max_sessions:
                raise BackendBlockedError("maximum concurrent Vivado sessions reached")
            session_id = uuid.uuid4().hex
            session_dir = self.root / ".vibesilicon" / "sessions" / session_id
            session_dir.mkdir(parents=True, exist_ok=False)
            session = VivadoSession(
                session_id=session_id,
                owner=self.name,
                workdir=resolved_workdir,
                session_dir=session_dir,
                mode=mode,
                gui=gui,
                tool_version=tool_version or capabilities["vivado_version"],
                started_at=utc_now(),
            )
            self._sessions[session_id] = session
        (session_dir / "capabilities.json").write_text(
            json.dumps(capabilities, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self._audit(session, {"event": "session_started", "state": session.state})
        return session

    def _require_session(self, session: VivadoSession) -> None:
        registered = self._sessions.get(session.session_id)
        if registered is not session or session.owner != self.name:
            raise ValueError("session is not owned by this backend")
        if session.state != "ACTIVE":
            raise ValueError(f"session is not active: {session.state}")

    def _audit(self, session: VivadoSession, event: dict[str, Any]) -> None:
        payload = {"timestamp": utc_now(), "backend": self.name, "session_id": session.session_id, **event}
        with (session.session_dir / "audit.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def execute_tcl(
        self,
        session: VivadoSession,
        command: str,
        risk_class: str,
        timeout: int,
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        self._require_session(session)
        if risk_class not in RISK_CLASSES:
            raise ValueError(f"unknown risk class: {risk_class}")
        if not isinstance(command, str) or not command.strip() or len(command.encode("utf-8")) > 1024 * 1024:
            raise ValueError("Tcl command must be non-empty and no larger than 1 MiB")
        blocked_reason = None
        if risk_class == "R4":
            blocked_reason = "R4 commands are forbidden"
        elif risk_class in {"R2", "R3"} and not approved:
            blocked_reason = f"{risk_class} command requires explicit approval"
        elif FORBIDDEN_TCL.search(command):
            blocked_reason = "Tcl command contains forbidden external execution or destructive file operation"
        timeout = max(1, min(int(timeout), MAX_TIMEOUT_SECONDS))

        with session.lock:
            session.sequence += 1
            sequence = session.sequence
            tcl_path = session.session_dir / f"command_{sequence:04d}.tcl"
            log_path = session.session_dir / f"command_{sequence:04d}.log"
            tcl_path.write_text(command.rstrip() + "\n", encoding="utf-8")
            launcher = self._command(["-mode", "batch", "-nolog", "-nojournal", "-source", str(tcl_path)])
            started_at = utc_now()
            start = time.monotonic()
            stdout = stderr = ""
            exit_code = None
            status = "BLOCKED" if blocked_reason else "ERROR"
            if blocked_reason is None:
                try:
                    result = self.runner(
                        launcher,
                        cwd=str(session.workdir),
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        shell=False,
                    )
                    stdout, stderr, exit_code = result.stdout or "", result.stderr or "", result.returncode
                    status = "PASS" if result.returncode == 0 else "FAIL"
                except subprocess.TimeoutExpired as exc:
                    stdout = exc.stdout or ""
                    stderr = exc.stderr or ""
                    blocked_reason = f"command timed out after {timeout}s"
                except OSError as exc:
                    blocked_reason = str(exc)
            duration = round(time.monotonic() - start, 6)
            log_path.write_text(
                json.dumps(
                    {
                        "status": status,
                        "exit_code": exit_code,
                        "reason": blocked_reason,
                        "stdout": stdout,
                        "stderr": stderr,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            log_artifact = artifact_record(log_path, self.root, "log", retention="pr")
            manifest = build_manifest(
                project=self.root.name,
                task_id=f"vivado-session-{session.session_id}-{sequence}",
                root=self.root,
                artifacts=[(log_path, "log")],
                retention="pr",
                created_at=started_at,
                reproduce_commands=[],
                environment={"backend": self.name, "vivado_version": session.tool_version},
            )
            manifest_path = session.session_dir / f"manifest_{sequence:04d}.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            receipt = build_receipt(
                task_id=manifest["task_id"],
                tool={"name": "vivado", "version": session.tool_version, "backend": self.name},
                inputs={"tcl_hash": sha256_bytes(command.encode("utf-8"))},
                command_argv=launcher,
                command_cwd=session.workdir.relative_to(self.root).as_posix() or ".",
                started_at=started_at,
                duration_s=duration,
                status=status,
                metrics={"exit_code": exit_code, "risk_class": risk_class},
                artifacts=[log_artifact],
                parser={"name": "raw-command", "schema_version": 1},
                provenance={"agent": "vivado-backend"},
            )
            receipt_path = session.session_dir / f"receipt_{sequence:04d}.json"
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            audit_event = {
                "event": "command_completed",
                "sequence": sequence,
                "risk_class": risk_class,
                "approved": approved,
                "status": status,
                "exit_code": exit_code,
                "command_hash": receipt["command_hash"],
                "evidence_id": receipt["evidence_id"],
            }
            self._audit(session, audit_event)
            return {
                "success": status == "PASS",
                "status": status,
                "backend": self.name,
                "backend_version": self.version,
                "session_id": session.session_id,
                "started_at": started_at,
                "duration_s": duration,
                "exit_code": exit_code,
                "reason": blocked_reason,
                "stdout_tail": stdout[-3000:],
                "stderr_tail": stderr[-3000:],
                "log_path": str(log_path.relative_to(self.root).as_posix()),
                "command_hash": receipt["command_hash"],
                "evidence_id": receipt["evidence_id"],
                "manifest_id": manifest["manifest_id"],
                "receipt_path": str(receipt_path.relative_to(self.root).as_posix()),
            }

    def record_report_evidence(
        self,
        session: VivadoSession,
        command_result: dict[str, Any],
        report_path: Path,
        kind: str,
    ) -> dict[str, Any]:
        """Parse a command-produced report and bind it to the raw command receipt."""
        self._require_session(session)
        if command_result.get("status") != "PASS":
            raise ValueError("parsed report evidence requires a PASS raw command receipt")
        report = self._inside_root(report_path)
        raw_receipt_path = self._inside_root(self.root / command_result["receipt_path"])
        try:
            raw_receipt_path.relative_to(session.session_dir)
        except ValueError as exc:
            raise ValueError("raw command receipt does not belong to this session") from exc
        raw_receipt = json.loads(raw_receipt_path.read_text(encoding="utf-8"))
        validate_receipt(raw_receipt)
        if raw_receipt["evidence_id"] != command_result.get("evidence_id"):
            raise ValueError("raw command evidence ID does not match its receipt")

        task_id = f"{raw_receipt['task_id']}-{kind}"
        bundle = create_report_evidence(
            report,
            root=self.root,
            kind=kind,
            task_id=task_id,
            tool=raw_receipt["tool"],
            command_argv=raw_receipt["command"]["argv"],
            command_cwd=raw_receipt["command"]["cwd"],
            started_at=raw_receipt["started_at"],
            duration_s=raw_receipt["duration_s"],
            provenance={"agent": "vivado-backend", "prompt_version": "parsed-report-v1"},
            inputs={"raw_evidence_id": raw_receipt["evidence_id"]},
        )
        stem = f"report_{session.sequence:04d}_{kind}"
        manifest_path = session.session_dir / f"{stem}.manifest.json"
        receipt_path = session.session_dir / f"{stem}.receipt.json"
        sidecar_path = report.with_suffix(report.suffix + ".receipt.json")
        for path, document in (
            (manifest_path, bundle["manifest"]),
            (receipt_path, bundle["receipt"]),
            (sidecar_path, bundle["receipt"]),
        ):
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._audit(
            session,
            {
                "event": "report_evidence_created",
                "sequence": session.sequence,
                "kind": kind,
                "raw_evidence_id": raw_receipt["evidence_id"],
                "evidence_id": bundle["receipt"]["evidence_id"],
            },
        )
        return {
            "kind": kind,
            "evidence_id": bundle["receipt"]["evidence_id"],
            "manifest_id": bundle["manifest"]["manifest_id"],
            "receipt_path": receipt_path.relative_to(self.root).as_posix(),
            "sidecar_path": sidecar_path.relative_to(self.root).as_posix(),
            "metrics": bundle["receipt"]["metrics"],
            "parser": bundle["receipt"]["parser"],
        }

    def get_status(self, session: VivadoSession) -> dict[str, Any]:
        registered = self._sessions.get(session.session_id)
        if registered is not session:
            raise ValueError("session is not owned by this backend")
        return {
            "backend": self.name,
            "session_id": session.session_id,
            "state": session.state,
            "sequence": session.sequence,
            "started_at": session.started_at,
        }

    def get_log_messages(
        self, session: VivadoSession, severity: str | None = None, cursor: int = 0
    ) -> dict[str, Any]:
        registered = self._sessions.get(session.session_id)
        if registered is not session:
            raise ValueError("session is not owned by this backend")
        lines = (session.session_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        cursor = max(0, int(cursor))
        messages = [json.loads(line) for line in lines[cursor:]]
        if severity is not None:
            messages = [item for item in messages if item.get("severity") == severity]
        return {"messages": messages, "cursor": len(lines)}

    def search_docs(self, query: str, vivado_version: str) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("documentation query must be non-empty")
        return {
            "status": "BLOCKED",
            "backend": self.name,
            "vivado_version": vivado_version,
            "citations": [],
            "reason": "native backend documentation search is not configured",
        }

    def stop_session(self, session: VivadoSession) -> dict[str, Any]:
        self._require_session(session)
        session.state = "STOPPED"
        self._audit(session, {"event": "session_stopped", "state": session.state})
        return self.get_status(session)
