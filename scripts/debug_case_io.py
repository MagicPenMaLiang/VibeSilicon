"""Bounded, local-only input helpers for advisory debug data."""
from __future__ import annotations

import json
import math
import os
import stat
from functools import lru_cache
from pathlib import Path

from jsonschema import validators
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import NoSuchResource

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = frozenset({'debug_case.schema.json', 'debug_run_plan.schema.json',
                     'debug_capture.schema.json', 'debug_scenarios.schema.json',
                     'debug_trial_plan.schema.json', 'debug_trial_scores.schema.json'})
DOCUMENT_LIMIT = 1024 * 1024


class DebugDataError(ValueError):
    """Invalid or unsafe debug input."""


def _is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _check_components(path):
    if not isinstance(path, (str, Path)):
        raise DebugDataError('path must be a string or Path')
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if _is_link(current.lstat()):
            raise DebugDataError('links and reparse points are not allowed')
    return absolute


def confined_path(root: Path, relative: str) -> Path:
    if (not isinstance(relative, str) or not relative or '\\' in relative or ':' in relative
            or any(part in ('', '.', '..') for part in relative.split('/'))):
        raise DebugDataError('expected a strict POSIX relative path')
    try:
        base = _check_components(root).resolve(strict=True)
        if not base.is_dir():
            raise DebugDataError('root must be a directory')
        candidate = _check_components(base.joinpath(*relative.split('/'))).resolve(strict=True)
        candidate.relative_to(base)
        return candidate
    except (OSError, ValueError) as exc:
        if isinstance(exc, DebugDataError):
            raise
        raise DebugDataError('path is unavailable or outside root') from exc


def _read_file(path, max_bytes):
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 0:
        raise DebugDataError('invalid byte limit')
    try:
        path = _check_components(path)
        before_path = path.lstat()
        if _is_link(before_path) or not stat.S_ISREG(before_path.st_mode):
            raise DebugDataError('input must be a regular file')
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, 'rb') as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
                raise DebugDataError('input is not a regular file or exceeds byte limit')
            data = stream.read(max_bytes + 1)
            after = os.fstat(stream.fileno())
        final = path.lstat()
        def identity(s):
            return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)

        if (len(data) > max_bytes or identity(before_path) != identity(before)
                or identity(before) != identity(after) or identity(after) != identity(final)
                or before.st_ctime_ns != after.st_ctime_ns or _is_link(final)):
            raise DebugDataError('input changed during read or exceeds byte limit')
        return data
    except OSError as exc:
        raise DebugDataError('cannot safely read input file') from exc


def read_artifact(root: Path, relative: str, max_bytes: int = 33554432) -> bytes:
    return _read_file(confined_path(root, relative), max_bytes)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DebugDataError('duplicate JSON key')
        result[key] = value
    return result


def _constant(_value):
    raise DebugDataError('non-finite JSON number')


def _depth(value, depth=0):
    if depth > 32:
        raise DebugDataError('JSON nesting exceeds limit')
    if isinstance(value, float) and not math.isfinite(value):
        raise DebugDataError('non-finite JSON number')
    if isinstance(value, str) and any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise DebugDataError('invalid Unicode surrogate')
    if isinstance(value, dict):
        for key, child in value.items():
            _depth(key, depth + 1)
            _depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _depth(child, depth + 1)


def read_document(path: Path) -> dict:
    try:
        value = json.loads(_read_file(path, DOCUMENT_LIMIT).decode('utf-8'),
                           object_pairs_hook=_object, parse_constant=_constant)
        if not isinstance(value, dict):
            raise DebugDataError('JSON document must be an object')
        _depth(value)
        return value
    except DebugDataError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise DebugDataError('invalid UTF-8 JSON document') from exc


def _check_refs(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ('$ref', '$dynamicRef', '$recursiveRef') and (not isinstance(child, str) or not child.startswith('#')):
                raise DebugDataError('external schema references are forbidden')
            _check_refs(child)
    elif isinstance(value, list):
        for child in value:
            _check_refs(child)


def _deny_retrieve(uri):
    raise NoSuchResource(ref=uri)


@lru_cache(maxsize=4)
def _validator(schema_path):
    schema = read_document(schema_path)
    _check_refs(schema)
    cls = validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema, registry=Registry(retrieve=_deny_retrieve))


def _validation_location(error):
    parts = [str(part).replace('~', '~0').replace('/', '~1') for part in error.absolute_path]
    pointer = ('/' + '/'.join(parts))[:256]
    message = f'document invalid at {pointer} (rule: {error.validator})'
    if error.validator == 'required' and isinstance(error.instance, dict):
        missing = [key for key in error.validator_value if key not in error.instance]
        message += '; missing fields: ' + ', '.join(missing)[:256]
    return message


def validate_schema(value: dict, schema_name: str) -> None:
    if not isinstance(schema_name, str) or schema_name not in SCHEMAS:
        raise DebugDataError('schema is not allowed')
    _depth(value)
    try:
        validator = _validator(ROOT / 'schemas' / schema_name)
    except (DebugDataError, SchemaError) as exc:
        raise DebugDataError('local schema is unavailable or invalid') from exc
    try:
        validator.validate(value)
    except ValidationError as exc:
        raise DebugDataError(_validation_location(exc)) from exc
