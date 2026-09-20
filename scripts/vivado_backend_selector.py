#!/usr/bin/env python3
"""Fail-closed Vivado backend selector for the public distribution."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from scripts.vivado_backend import BackendBlockedError, NativeVivadoBackend, VivadoBackend


def select_vivado_backend(
    *,
    root: Path,
    vivado_bin: str,
    settings_path: str | None,
    environment: Mapping[str, str] | None = None,
) -> VivadoBackend:
    env = dict(os.environ if environment is None else environment)
    selected = env.get("VIBESILICON_VIVADO_BACKEND", "native").strip().lower()
    if selected != "native":
        raise BackendBlockedError(
            f"unsupported Vivado backend selector in the public distribution: {selected!r}; "
            "use 'native' or provide a separately reviewed adapter"
        )
    return NativeVivadoBackend(root=root, vivado_bin=vivado_bin, settings_path=settings_path)


def close_vivado_backend(backend: VivadoBackend) -> None:
    transport = getattr(backend, "transport", None)
    close = getattr(transport, "close", None)
    if callable(close):
        close()
