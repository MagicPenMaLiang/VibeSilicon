"""Resolve the transitive `include closure of a Verilog source set.

A gate that hashes only the files named in a manifest does not bind what the
compiler actually reads: an `include pulled in by a testbench can change the
simulation result without changing any hashed byte. This module resolves the
includes the compiler would see, honouring `ifdef/`ifndef/`elsif/`else/`endif
against the manifest defines so that an include in a disabled branch is not
treated as an input.

Every resolved file must stay inside the repository. An include that is active
and cannot be resolved is an error, not a silent omission: a gate that skips an
input it cannot find is exactly the vacuum this module exists to close.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from scripts.quality_gate.rtl_manifest import ManifestError, _bounded_path


DIRECTIVE = re.compile(r"`\s*(include|ifdef|ifndef|elsif|else|endif|define|undef|undefineall)\b(.*)$")
LITERAL_INCLUDE = re.compile(r'^\s*[<"]([^">\n]+)[">]\s*$')
DEFINE_NAME = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_$]*)")


def _mask_comments(source: str) -> str:
    """Blank out comments while keeping string literals intact.

    The shared code masker blanks string contents as well, which would erase
    the filename in `include "file.sv" and leave the closure permanently empty.
    An empty closure is indistinguishable from "no includes", so this module
    keeps its own comment-only mask.
    """
    masked: list[str] = []
    state = "code"
    index = 0
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "code":
            if char == "/" and following == "/":
                masked.extend("  ")
                index += 2
                state = "line"
                continue
            if char == "/" and following == "*":
                masked.extend("  ")
                index += 2
                state = "block"
                continue
            if char == '"':
                state = "string"
        elif state == "line":
            masked.append("\n" if char == "\n" else " ")
            if char == "\n":
                state = "code"
            index += 1
            continue
        elif state == "block":
            if char == "*" and following == "/":
                masked.extend("  ")
                index += 2
                state = "code"
                continue
            masked.append("\n" if char == "\n" else " ")
            index += 1
            continue
        elif state == "string":
            if char == "\\" and following:
                masked.extend((char, following))
                index += 2
                continue
            if char == '"':
                state = "code"
        masked.append(char)
        index += 1
    return "".join(masked)


def _included_names(text: str, defines: set[str]) -> Iterator[str]:
    """Pause at each include so its macro changes affect the following lines."""
    active = True
    stack: list[tuple[bool, bool]] = []  # (this branch active, some branch taken)
    for raw in _mask_comments(text).splitlines():
        match = DIRECTIVE.match(raw.strip())
        if match is None:
            continue
        directive, rest = match.group(1), match.group(2)
        if directive in {"ifdef", "ifndef"}:
            name = DEFINE_NAME.match(rest)
            if name is None:
                raise ManifestError(f"malformed conditional directive: {raw.strip()!r}")
            taken = (name.group(1) in defines) == (directive == "ifdef")
            stack.append((active, taken))
            active = active and taken
        elif directive == "elsif":
            if not stack:
                raise ManifestError(f"unbalanced {directive} in source")
            parent, taken = stack[-1]
            name = DEFINE_NAME.match(rest)
            if name is None:
                raise ManifestError(f"malformed elsif directive: {raw.strip()!r}")
            branch = (name.group(1) in defines) and not taken
            stack[-1] = (parent, taken or branch)
            active = parent and branch
        elif directive == "else":
            if not stack:
                raise ManifestError(f"unbalanced {directive} in source")
            parent, taken = stack[-1]
            stack[-1] = (parent, True)
            active = parent and not taken
        elif directive == "endif":
            if not stack:
                raise ManifestError(f"unbalanced {directive} in source")
            parent, _ = stack.pop()
            active = parent
        elif directive == "define":
            if active:
                name = DEFINE_NAME.match(rest)
                if name is not None:
                    defines.add(name.group(1))
        elif directive == "undef":
            if active:
                name = DEFINE_NAME.match(rest)
                if name is not None:
                    defines.discard(name.group(1))
        elif directive == "undefineall":
            if active:
                defines.clear()
        elif active:
            literal = LITERAL_INCLUDE.match(rest)
            if literal is None:
                raise ManifestError(f"non-literal include cannot be bound by a gate: {raw.strip()!r}")
            yield literal.group(1)
    if stack:
        raise ManifestError("unterminated conditional in source")


def include_closure(*, root: Path, entries: list[Path], include_dirs: list[Path],
                    defines: dict[str, str] | None = None) -> dict[str, Path]:
    """Return repository-relative path -> file for every reachable include."""
    root = root.resolve(strict=True)
    macros = set((defines or {}).keys())
    closure: dict[str, Path] = {}
    expansions = 0

    def visit(current: Path, depth: int = 0) -> None:
        nonlocal expansions
        expansions += 1
        if depth > 64 or expansions > 10000:
            raise ManifestError("include expansion limit exceeded; check recursive includes")
        try:
            text = current.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Hashing stays byte-level by contract, so an undecodable source
            # must not turn into an exception here. It cannot compile or
            # simulate either, so the gate still fails closed later; and the
            # file is already in the input set by its bytes. Skipping its
            # includes therefore creates no unbound evidence.
            return
        for name in _included_names(text, macros):
            if "\\" in name or ":" in name:
                raise ManifestError(f"invalid include name: {name!r}")
            found = None
            for directory in [*include_dirs, current.parent]:
                candidate = directory / name
                if candidate.is_file():
                    found = candidate
                    break
            if found is None:
                raise ManifestError(f"unresolved include {name!r} referenced from "
                                    f"{current.relative_to(root).as_posix()}")
            if found.is_symlink():
                raise ManifestError(f"linked include is not allowed: {name}")
            resolved = found.resolve()
            if not resolved.is_relative_to(root):
                raise ManifestError(f"include escapes repository: {name}")
            relative = resolved.relative_to(root).as_posix()
            _bounded_path(root, relative, kind="include")
            closure[relative] = resolved
            # Re-read repeated headers: their active branches may differ after
            # intervening define/undef directives. The output still hashes once.
            visit(resolved, depth + 1)

    for entry in entries:
        visit(entry)
    return closure
