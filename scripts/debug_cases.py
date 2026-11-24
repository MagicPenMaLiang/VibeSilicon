"""Validate and query a local, advisory-only debug case catalog."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.debug_case_io import (DebugDataError, _check_components, _depth, confined_path,
                                   read_document, validate_schema)
from scripts.evidence_contract import content_id

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / 'knowledge' / 'fpga-video' / 'cases'
CONTEXT_KEYS = frozenset({'target', 'pipeline', 'platform', 'boundary'})


def validate_cases(cases: list) -> None:
    if not isinstance(cases, list) or not 1 <= len(cases) <= 64:
        raise DebugDataError('catalog must contain between 1 and 64 cases')
    by_id = {}
    for case in cases:
        validate_schema(case, 'debug_case.schema.json')
        identifier = case['case_id']
        if identifier in by_id:
            raise DebugDataError('duplicate case ID')
        if 'content_id' in case and case['content_id'] != content_id(case, 'content_id'):
            raise DebugDataError('case content ID does not match')
        by_id[identifier] = case
    visited, visiting = set(), set()

    def visit(identifier):
        if identifier in visiting:
            raise DebugDataError('cyclic supersedes relationship')
        if identifier in visited:
            return
        visiting.add(identifier)
        for previous in by_id[identifier]['supersedes']:
            if previous not in by_id:
                raise DebugDataError('dangling supersedes relationship')
            visit(previous)
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in by_id:
        visit(identifier)


def load_catalog(directory: Path) -> list[dict]:
    try:
        directory = _check_components(directory)
        if not directory.is_dir():
            raise DebugDataError('catalog must be a directory')
        files = []
        for path in directory.glob('*.json'):
            if len(files) == 64:
                raise DebugDataError('catalog exceeds 64 cases')
            files.append(path)
        cases = [read_document(confined_path(directory, path.name)) for path in sorted(files)]
        validate_cases(cases)
        return cases
    except OSError as exc:
        raise DebugDataError('cannot read catalog') from exc


def _validate_context(context):
    _depth(context)
    if not isinstance(context, dict) or any(key not in CONTEXT_KEYS for key in context):
        raise DebugDataError('context must contain only supported keys')
    if any(not isinstance(value, str) or not 1 <= len(value) <= 128 for value in context.values()):
        raise DebugDataError('context values must be non-empty bounded strings')


def _classify(case, context, replaced):
    identifier = case['case_id']
    if case['status'] != 'active':
        return 'excluded', {'case_id': identifier, 'reason': 'inactive case'}
    if identifier in replaced:
        return 'excluded', {'case_id': identifier, 'reason': 'superseded by another case'}
    required = case['conditions']['required']
    exclusions = case['conditions']['exclusions']
    if any(context.get(key) == value for key, value in exclusions.items()):
        return 'excluded', {'case_id': identifier, 'reason': 'exclusion condition matched'}
    if any(key in context and context[key] != value for key, value in required.items()):
        return 'excluded', {'case_id': identifier, 'reason': 'required condition differs'}
    missing = sorted((required.keys() | exclusions.keys()) - context.keys())
    if missing:
        return 'needs_context', {'case_id': identifier, 'missing': missing, 'reason': 'conditions require more context'}
    return 'matched', {'case_id': identifier, 'reason': 'all conditions satisfied'}


def _query_validated(cases, context, replaced):
    result = {'matched': [], 'needs_context': [], 'excluded': [],
              'advisory': True, 'human_approved': False, 'hardware_validated': False}
    for case in cases:
        category, entry = _classify(case, context, replaced)
        result[category].append(entry)
    return result


def query_contexts(cases: list, contexts: list[dict]) -> list[dict]:
    validate_cases(cases)
    if not isinstance(contexts, list) or len(contexts) > 128:
        raise DebugDataError('contexts must be a list of at most 128 objects')
    for context in contexts:
        _validate_context(context)
    replaced = {previous for case in cases for previous in case['supersedes']}
    ordered = sorted(cases, key=lambda item: item['case_id'])
    return [_query_validated(ordered, context, replaced) for context in contexts]


def query_cases(cases: list, context: dict) -> dict:
    return query_contexts(cases, [context])[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ('validate', 'query'):
        sub = commands.add_parser(action)
        sub.add_argument('--catalog', type=Path, default=DEFAULT_CATALOG)
        if action == 'query':
            sub.add_argument('--context', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        cases = load_catalog(args.catalog)
        if args.action == 'query':
            result = query_cases(cases, read_document(args.context))
        else:
            result = {'case_ids': sorted(case['case_id'] for case in cases),
                      'advisory': True, 'human_approved': False, 'hardware_validated': False}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except DebugDataError as exc:
        print(json.dumps({'error': str(exc), 'advisory': True,
                          'human_approved': False, 'hardware_validated': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
