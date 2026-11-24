import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import debug_case_io as io
from scripts import debug_cases as dc

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'knowledge' / 'fpga-video' / 'cases'


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.cases = dc.load_catalog(CATALOG)

    def test_catalog_and_query(self):
        self.assertGreaterEqual(len(self.cases), 6)
        before = copy.deepcopy(self.cases)
        result = dc.query_cases(self.cases, {})
        self.assertFalse(result['matched'])
        self.assertTrue(result['needs_context'])
        self.assertTrue(result['advisory'])
        self.assertFalse(result['human_approved'])
        self.assertFalse(result['hardware_validated'])
        self.assertEqual(self.cases, before)
        case = self.cases[0]
        result = dc.query_cases(self.cases, dict(case['conditions']['required']))
        self.assertIn(case['case_id'], [item['case_id'] for item in result['matched']])
        self.assertEqual([x['case_id'] for x in result['matched']], sorted(x['case_id'] for x in result['matched']))

    def test_context_and_exclusion(self):
        with self.assertRaises(io.DebugDataError):
            dc.query_cases(self.cases, {'unknown': 'x'})
        with self.assertRaises(io.DebugDataError):
            dc.query_cases(self.cases, {'target': None})
        case = copy.deepcopy(self.cases[0])
        case['conditions']['exclusions'] = {'platform': 'other'}
        result = dc.query_cases([case], {**case['conditions']['required'], 'platform': 'other'})
        self.assertEqual(result['excluded'][0]['case_id'], case['case_id'])

    def test_relationships_and_inactive(self):
        first = copy.deepcopy(self.cases[0])
        second = copy.deepcopy(first)
        second['case_id'] = 'replacement'
        second['supersedes'] = [first['case_id']]
        result = dc.query_cases([first, second], first['conditions']['required'])
        self.assertEqual(result['excluded'][0]['case_id'], first['case_id'])
        second['status'] = 'stale'
        self.assertEqual(len(dc.query_cases([first, second], {})['excluded']), 2)
        for bad in ([first, first], [{**first, 'supersedes': ['absent']}],
                    [{**first, 'supersedes': [first['case_id']]}],
                    [{**first, 'supersedes': ['replacement']}, second]):
            with self.subTest(bad=bad), self.assertRaises(io.DebugDataError):
                dc.validate_cases(bad)

    def test_invalid_cases_and_context_boundaries(self):
        from scripts.evidence_contract import content_id
        case = copy.deepcopy(self.cases[0])
        for change in ({'status': 'unknown'}, {'unexpected': 'value'},
                       {'content_id': 'sha256:' + '0' * 64}):
            with self.subTest(change=change), self.assertRaises(io.DebugDataError):
                dc.validate_cases([{**case, **change}])
        case['content_id'] = content_id(case, 'content_id')
        dc.validate_cases([case])
        for context in (None, [], {'target': ''}, {'target': 'x' * 129}, {'boundary': 3}):
            with self.subTest(context=context), self.assertRaises(io.DebugDataError):
                dc.query_cases(self.cases, context)
        result = dc.query_cases([case], {**case['conditions']['required'], 'boundary': 'wrong'})
        self.assertTrue(result['excluded'])

    def test_missing_exclusion_context(self):
        case = copy.deepcopy(self.cases[0])
        case['conditions']['exclusions'] = {'platform': 'excluded-platform'}
        result = dc.query_cases([case], case['conditions']['required'])
        self.assertEqual(result['needs_context'][0]['missing'], ['platform'])
        result = dc.query_cases([case], {**case['conditions']['required'], 'platform': 'allowed'})
        self.assertEqual(result['matched'][0]['case_id'], case['case_id'])

    def test_batch_queries(self):
        from unittest.mock import patch
        context = dict(self.cases[0]['conditions']['required'])
        expected = [dc.query_cases(self.cases, {}), dc.query_cases(self.cases, context)]
        with patch.object(dc, 'validate_cases', wraps=dc.validate_cases) as validate:
            self.assertEqual(dc.query_contexts(self.cases, [{}, context]), expected)
            self.assertEqual(validate.call_count, 1)
        for invalid in (None, {}, [None], [{}] * 129):
            with self.subTest(invalid=type(invalid)), self.assertRaises(io.DebugDataError):
                dc.query_contexts(self.cases, invalid)
        self.assertEqual(dc.query_contexts(self.cases, []), [])

    def test_reject_empty_and_invalid_unicode(self):
        with self.assertRaises(io.DebugDataError):
            dc.validate_cases([])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(io.DebugDataError):
                dc.load_catalog(Path(tmp))
        for context in ({'target': '\ud800'}, {'target': '\udfff'}):
            with self.assertRaises(io.DebugDataError):
                dc.query_cases(self.cases, context)
        case = copy.deepcopy(self.cases[0])
        case['title'] = '\ud800'
        with self.assertRaises(io.DebugDataError):
            dc.validate_cases([case])

    def test_limits_and_direct_cli(self):
        import contextlib
        import io as stringio
        with self.assertRaises(io.DebugDataError):
            dc.validate_cases([self.cases[0]] * 65)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(io.DebugDataError):
                dc.load_catalog(root / 'missing')
            for number in range(65):
                (root / f'{number:02}.json').write_text('{}', encoding='utf-8')
            with self.assertRaises(io.DebugDataError):
                dc.load_catalog(root)
        with contextlib.redirect_stdout(stringio.StringIO()) as output:
            self.assertEqual(dc.main(['validate']), 0)
        self.assertEqual(len(json.loads(output.getvalue())['case_ids']), len(self.cases))
        with contextlib.redirect_stdout(stringio.StringIO()) as output:
            self.assertEqual(dc.main(['query', '--context', 'missing.json']), 2)
        self.assertIn('error', json.loads(output.getvalue()))

    def test_catalog_enumeration_stops_at_limit_and_rejects_bad_paths(self):
        from unittest.mock import patch

        consumed = []

        def names():
            for number in range(65):
                consumed.append(number)
                yield CATALOG / f'{number}.json'
            raise AssertionError('catalog enumerated past the reject threshold')

        with patch.object(Path, 'glob', return_value=names()), self.assertRaises(io.DebugDataError):
            dc.load_catalog(CATALOG)
        self.assertEqual(len(consumed), 65)
        for value in (None, [], {}, 1):
            with self.subTest(value=value), self.assertRaises(io.DebugDataError):
                dc.load_catalog(value)
            with self.subTest(root=value), self.assertRaises(io.DebugDataError):
                io.confined_path(value, 'file')

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = Path(tmp) / 'context.json'
            context.write_text('{}', encoding='utf-8')
            run = subprocess.run([os.sys.executable, '-m', 'scripts.debug_cases', 'query', '--context', str(context)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue(json.loads(run.stdout)['needs_context'])
            context.write_text('{bad', encoding='utf-8')
            run = subprocess.run([os.sys.executable, '-m', 'scripts.debug_cases', 'query', '--context', str(context)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)


class IOTests(unittest.TestCase):
    def test_document_rejects_bad_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'x.json'
            for raw in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}', '{"a":"\\ud800"}', '{"a":' + '9' * 5000 + '}', '[' * 34 + '0' + ']' * 34, '[]', 'x' * (1024 * 1024 + 1)):
                path.write_text(raw, encoding='utf-8')
                with self.subTest(raw=raw[:20]), self.assertRaises(io.DebugDataError):
                    io.read_document(path)
            path.write_text('{"ok":true}', encoding='utf-8')
            self.assertEqual(io.read_document(path), {'ok': True})

    def test_paths_and_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'file').write_bytes(b'abc')
            self.assertEqual(io.read_artifact(root, 'file'), b'abc')
            with self.assertRaises(io.DebugDataError):
                io.read_artifact(root, 'file', 2)
            for path in ('../file', './file', 'a//b', '/file', 'C:file', 'a\\b', ''):
                with self.subTest(path=path), self.assertRaises(io.DebugDataError):
                    io.confined_path(root, path)
            try:
                (root / 'link').symlink_to(root / 'file')
            except OSError:
                return
            with self.assertRaises(io.DebugDataError):
                io.read_artifact(root, 'link')
            with self.assertRaises(io.DebugDataError):
                io.read_document(root / 'link')

    def test_schema_blocks_external_references(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            schemas = Path(tmp) / 'schemas'
            schemas.mkdir()
            schema = schemas / 'debug_case.schema.json'
            for value in ({'$ref': 'https://example.invalid/schema'},
                          {'type': 'not-a-type'}):
                schema.write_text(json.dumps(value), encoding='utf-8')
                with patch.object(io, 'ROOT', Path(tmp)), self.assertRaises(io.DebugDataError):
                    io.validate_schema({}, 'debug_case.schema.json')

    def test_schema_validator_cache(self):
        from unittest.mock import patch
        io._validator.cache_clear()
        schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'type': 'object'}
        with patch.object(io, 'read_document', return_value=schema) as read:
            io.validate_schema({}, 'debug_case.schema.json')
            io.validate_schema({}, 'debug_case.schema.json')
            self.assertEqual(read.call_count, 1)
        io._validator.cache_clear()

    def test_schema_allowlist(self):
        with self.assertRaises(io.DebugDataError):
            io.validate_schema({}, '../other.json')
        with self.assertRaises(io.DebugDataError):
            io.validate_schema({}, 'debug_case.schema.json')


if __name__ == '__main__':
    unittest.main()
