#!/usr/bin/env python3
"""Deterministic Evidence Receipt and Artifact Manifest contracts for VibeSilicon."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")
STATUSES = {"PASS", "FAIL", "ERROR", "BLOCKED"}
RETENTIONS = {"transient", "pr", "milestone", "signoff"}
STORAGE_TYPES = {"repository", "artifact_store", "external"}
ARTIFACT_KINDS = {
    "source",
    "spec",
    "constraints",
    "golden",
    "test_vector",
    "timing_report",
    "cdc_report",
    "utilization_report",
    "drc_report",
    "simulation_report",
    "log",
    "waveform",
    "dcp",
    "bitstream",
    "other",
}


class EvidenceContractError(ValueError):
    """Raised when evidence is incomplete, mutable, or outside its declared root."""


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise EvidenceContractError(f"artifact is not a file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def content_id(document: Mapping[str, Any], id_field: str) -> str:
    payload = dict(document)
    payload.pop(id_field, None)
    return sha256_bytes(canonical_bytes(payload))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise EvidenceContractError(f"{field} must be an RFC 3339 timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise EvidenceContractError(f"{field} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise EvidenceContractError(f"{field} must include a timezone")


def _validate_hash(value: Any, field: str) -> None:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise EvidenceContractError(f"{field} must be sha256:<64 lowercase hex characters>")


def _validate_relative_path(value: Any, field: str = "path") -> None:
    if not isinstance(value, str) or not value or "\\" in value or re.match(r"^[A-Za-z]:", value):
        raise EvidenceContractError(f"{field} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise EvidenceContractError(f"{field} must not escape its project root")


def _relative_file(path: str | Path, root: Path) -> tuple[Path, str]:
    root = root.resolve(strict=True)
    candidate = Path(path)
    candidate = candidate.resolve(strict=True) if candidate.is_absolute() else (root / candidate).resolve(strict=True)
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise EvidenceContractError(f"artifact is outside project root: {candidate}") from exc
    if not candidate.is_file():
        raise EvidenceContractError(f"artifact is not a file: {candidate}")
    return candidate, relative.as_posix()


def artifact_record(
    path: str | Path,
    root: Path,
    kind: str,
    *,
    retention: str = "signoff",
    storage: str = "repository",
) -> dict[str, Any]:
    if kind not in ARTIFACT_KINDS:
        raise EvidenceContractError(f"unsupported artifact kind: {kind}")
    if retention not in RETENTIONS:
        raise EvidenceContractError(f"unsupported retention policy: {retention}")
    if storage not in STORAGE_TYPES:
        raise EvidenceContractError(f"unsupported storage type: {storage}")
    resolved, relative = _relative_file(path, root)
    digest = sha256_file(resolved)
    record: dict[str, Any] = {
        "artifact_id": digest,
        "path": relative,
        "sha256": digest,
        "size_bytes": resolved.stat().st_size,
        "kind": kind,
        "retention": retention,
        "storage": storage,
    }
    media_type, _ = mimetypes.guess_type(resolved.name)
    if media_type:
        record["media_type"] = media_type
    return record


def build_manifest(
    *,
    project: str,
    task_id: str,
    root: Path,
    artifacts: Sequence[tuple[str | Path, str]],
    created_at: str | None = None,
    source_commit: str | None = None,
    reproduce_commands: Sequence[str] = (),
    environment: Mapping[str, str] | None = None,
    retention: str = "signoff",
    storage: str = "repository",
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project": project,
        "task_id": task_id,
        "created_at": created_at or utc_now(),
        "artifacts": [
            artifact_record(path, root, kind, retention=retention, storage=storage)
            for path, kind in artifacts
        ],
        "reproduce": {
            "commands": list(reproduce_commands),
            "environment": dict(environment or {}),
        },
    }
    if source_commit is not None:
        document["source_commit"] = source_commit
    document["manifest_id"] = content_id(document, "manifest_id")
    validate_manifest(document)
    return document


def artifact_reference(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in ("artifact_id", "path", "sha256", "kind")}


def build_receipt(
    *,
    task_id: str,
    tool: Mapping[str, str],
    inputs: Mapping[str, str],
    command_argv: Sequence[str],
    command_cwd: str,
    started_at: str,
    duration_s: float,
    status: str,
    metrics: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
    parser: Mapping[str, Any],
    provenance: Mapping[str, str],
) -> dict[str, Any]:
    command = {"argv": list(command_argv), "cwd": command_cwd}
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "tool": dict(tool),
        "inputs": dict(inputs),
        "command": command,
        "command_hash": sha256_bytes(canonical_bytes(command)),
        "started_at": started_at,
        "duration_s": duration_s,
        "status": status,
        "metrics": dict(metrics),
        "artifacts": [artifact_reference(item) for item in artifacts],
        "parser": dict(parser),
        "provenance": dict(provenance),
    }
    document["evidence_id"] = content_id(document, "evidence_id")
    validate_receipt(document)
    return document


def _required(document: Mapping[str, Any], names: set[str], contract: str) -> None:
    missing = sorted(names - document.keys())
    if missing:
        raise EvidenceContractError(f"{contract} required fields missing: {missing}")


def _reject_unknown(document: Mapping[str, Any], names: set[str], contract: str) -> None:
    unexpected = sorted(document.keys() - names)
    if unexpected:
        raise EvidenceContractError(f"{contract} contains unknown fields: {unexpected}")


def _validate_artifact(record: Mapping[str, Any]) -> None:
    required = {"artifact_id", "path", "sha256", "size_bytes", "kind", "retention", "storage"}
    _required(record, required, "artifact")
    _reject_unknown(record, required | {"media_type"}, "artifact")
    _validate_hash(record["artifact_id"], "artifact_id")
    _validate_hash(record["sha256"], "artifact sha256")
    if record["artifact_id"] != record["sha256"]:
        raise EvidenceContractError("artifact_id must equal the artifact content hash")
    _validate_relative_path(record["path"])
    if not isinstance(record["size_bytes"], int) or record["size_bytes"] < 0:
        raise EvidenceContractError("artifact size_bytes must be a non-negative integer")
    if record["kind"] not in ARTIFACT_KINDS:
        raise EvidenceContractError(f"unsupported artifact kind: {record['kind']}")
    if record["retention"] not in RETENTIONS or record["storage"] not in STORAGE_TYPES:
        raise EvidenceContractError("artifact retention or storage policy is invalid")


def validate_manifest(document: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "manifest_id",
        "project",
        "task_id",
        "created_at",
        "artifacts",
        "reproduce",
    }
    _required(document, required, "artifact manifest")
    _reject_unknown(document, required | {"source_commit"}, "artifact manifest")
    if document["schema_version"] != SCHEMA_VERSION:
        raise EvidenceContractError("unsupported artifact manifest schema_version")
    _validate_hash(document["manifest_id"], "manifest_id")
    _validate_timestamp(document["created_at"], "created_at")
    if not isinstance(document["project"], str) or not document["project"]:
        raise EvidenceContractError("project must be non-empty")
    if not isinstance(document["task_id"], str) or not document["task_id"]:
        raise EvidenceContractError("task_id must be non-empty")
    if "source_commit" in document and not COMMIT_RE.fullmatch(str(document["source_commit"])):
        raise EvidenceContractError("source_commit must be 7-64 lowercase hex characters")
    artifacts = document["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise EvidenceContractError("artifact manifest must contain at least one artifact")
    paths = []
    for record in artifacts:
        if not isinstance(record, Mapping):
            raise EvidenceContractError("artifact entry must be an object")
        _validate_artifact(record)
        paths.append(record["path"])
    if len(paths) != len(set(paths)):
        raise EvidenceContractError("artifact manifest contains duplicate paths")
    reproduce = document["reproduce"]
    if not isinstance(reproduce, Mapping) or not isinstance(reproduce.get("commands"), list):
        raise EvidenceContractError("reproduce.commands must be an array")
    if not isinstance(reproduce.get("environment"), Mapping):
        raise EvidenceContractError("reproduce.environment must be an object")
    _reject_unknown(reproduce, {"commands", "environment"}, "reproduce")
    if not all(isinstance(command, str) and command for command in reproduce["commands"]):
        raise EvidenceContractError("reproduce commands must be non-empty strings")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in reproduce["environment"].items()):
        raise EvidenceContractError("reproduce environment keys and values must be strings")
    if document["manifest_id"] != content_id(document, "manifest_id"):
        raise EvidenceContractError("manifest_id does not match canonical manifest content")


def validate_receipt(document: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "evidence_id",
        "task_id",
        "tool",
        "inputs",
        "command",
        "command_hash",
        "started_at",
        "duration_s",
        "status",
        "metrics",
        "artifacts",
        "parser",
        "provenance",
    }
    _required(document, required, "evidence receipt")
    _reject_unknown(document, required, "evidence receipt")
    if document["schema_version"] != SCHEMA_VERSION:
        raise EvidenceContractError("unsupported evidence receipt schema_version")
    _validate_hash(document["evidence_id"], "evidence_id")
    _validate_timestamp(document["started_at"], "started_at")
    if document["status"] not in STATUSES:
        raise EvidenceContractError(f"unsupported evidence status: {document['status']}")
    if not isinstance(document["task_id"], str) or not document["task_id"]:
        raise EvidenceContractError("task_id must be non-empty")
    if not isinstance(document["duration_s"], (int, float)) or document["duration_s"] < 0:
        raise EvidenceContractError("duration_s must be non-negative")
    tool = document["tool"]
    if not isinstance(tool, Mapping) or any(not tool.get(name) for name in ("name", "version", "backend")):
        raise EvidenceContractError("tool must include name, version and backend")
    _reject_unknown(tool, {"name", "version", "backend"}, "tool")
    inputs = document["inputs"]
    if not isinstance(inputs, Mapping) or not inputs:
        raise EvidenceContractError("inputs must contain at least one named hash")
    for name, digest in inputs.items():
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", str(name)):
            raise EvidenceContractError(f"invalid input name: {name}")
        _validate_hash(digest, f"input {name}")
    command = document["command"]
    if not isinstance(command, Mapping) or not command.get("argv") or not command.get("cwd"):
        raise EvidenceContractError("command must include non-empty argv and cwd")
    _reject_unknown(command, {"argv", "cwd"}, "command")
    if not isinstance(command["argv"], list) or not all(isinstance(item, str) for item in command["argv"]):
        raise EvidenceContractError("command.argv must be a non-empty string array")
    _validate_relative_path(command["cwd"], "command.cwd")
    _validate_hash(document["command_hash"], "command_hash")
    if document["command_hash"] != sha256_bytes(canonical_bytes(command)):
        raise EvidenceContractError("command_hash does not match canonical command")
    if not isinstance(document["metrics"], Mapping):
        raise EvidenceContractError("metrics must be an object")
    if not isinstance(document["artifacts"], list):
        raise EvidenceContractError("artifacts must be an array")
    artifact_fields = {"artifact_id", "path", "sha256", "kind"}
    for record in document["artifacts"]:
        if not isinstance(record, Mapping):
            raise EvidenceContractError("artifact reference must be an object")
        _required(record, {"artifact_id", "path", "sha256", "kind"}, "artifact reference")
        _reject_unknown(record, artifact_fields, "artifact reference")
        _validate_hash(record["artifact_id"], "artifact reference id")
        _validate_hash(record["sha256"], "artifact reference sha256")
        if record["artifact_id"] != record["sha256"]:
            raise EvidenceContractError("artifact reference id must equal sha256")
        _validate_relative_path(record["path"])
        if record["kind"] not in ARTIFACT_KINDS:
            raise EvidenceContractError(f"unsupported artifact kind: {record['kind']}")
    parser = document["parser"]
    if (
        not isinstance(parser, Mapping)
        or not parser.get("name")
        or not isinstance(parser.get("schema_version"), int)
        or parser["schema_version"] < 1
    ):
        raise EvidenceContractError("parser must include name and integer schema_version")
    _reject_unknown(parser, {"name", "schema_version"}, "parser")
    provenance = document["provenance"]
    if not isinstance(provenance, Mapping) or not provenance.get("agent"):
        raise EvidenceContractError("provenance.agent is required")
    _reject_unknown(provenance, {"agent", "model", "prompt_version"}, "provenance")
    if document["evidence_id"] != content_id(document, "evidence_id"):
        raise EvidenceContractError("evidence_id does not match canonical receipt content")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _artifact_argument(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("artifact must use KIND=RELATIVE_PATH")
    kind, path = value.split("=", 1)
    if kind not in ARTIFACT_KINDS or not path:
        raise argparse.ArgumentTypeError("artifact kind or path is invalid")
    return path, kind


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    manifest_parser = subparsers.add_parser("manifest", help="create an artifact manifest")
    manifest_parser.add_argument("--root", required=True, type=Path)
    manifest_parser.add_argument("--project", required=True)
    manifest_parser.add_argument("--task-id", required=True)
    manifest_parser.add_argument("--output", required=True, type=Path)
    manifest_parser.add_argument("--artifact", action="append", required=True, type=_artifact_argument)
    manifest_parser.add_argument("--source-commit")
    manifest_parser.add_argument("--created-at")
    manifest_parser.add_argument("--reproduce", action="append", default=[])
    verify_parser = subparsers.add_parser("verify", help="verify a receipt or manifest")
    verify_parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.action == "manifest":
            document = build_manifest(
                project=args.project,
                task_id=args.task_id,
                root=args.root,
                artifacts=args.artifact,
                created_at=args.created_at,
                source_commit=args.source_commit,
                reproduce_commands=args.reproduce,
            )
            output = args.output.resolve(strict=False)
            root = args.root.resolve(strict=True)
            try:
                output.relative_to(root)
            except ValueError as exc:
                raise EvidenceContractError(f"output is outside project root: {output}") from exc
            _write_json(output, document)
            print(document["manifest_id"])
        else:
            document = _load_json(args.path)
            if "manifest_id" in document:
                validate_manifest(document)
                print(document["manifest_id"])
            elif "evidence_id" in document:
                validate_receipt(document)
                print(document["evidence_id"])
            else:
                raise EvidenceContractError("unknown evidence document type")
    except (OSError, json.JSONDecodeError, EvidenceContractError) as exc:
        print(f"[ERROR] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
