import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from vulnloc.integrity import contained, sha256, verify
from vulnloc.reproduce import (
    aggregate, assert_finite_tree, compute, displayed, input_manifest,
    pure_functions, run, validate_units,
)
from vulnloc.site_data import load_site_data

ROOT = Path(__file__).resolve().parents[1]


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.rows = json.loads((ROOT / 'data/processed/s1/metrics.json').read_text())
        self.entries = json.loads((ROOT / 'data/processed/entries.json').read_text())
        self.schedule = json.loads((ROOT / 'data/processed/s1/schedule.json').read_text())

    def test_integrity(self):
        self.assertGreater(verify(ROOT), 50)

    def test_source_copies_are_byte_identical(self):
        ledger = json.loads((ROOT / 'docs/provenance/copied_files.json').read_text())
        for item in ledger:
            if item['mode'] == 'byte-identical':
                self.assertEqual(sha256(ROOT / item['destination']), item['sha256'])

    def test_supplied_s0_launch_hashes(self):
        import hashlib
        bindings = json.loads((ROOT / 'docs/provenance/s0_launch_hash_bindings.json').read_text())
        self.assertEqual(len(bindings), 18)
        for value in bindings.values():
            if value['supplied_copy']:
                data = (ROOT / value['supplied_copy']).read_bytes().replace(b'\r\n', b'\n').replace(b'\r', b'\n')
                self.assertEqual(hashlib.sha256(data).hexdigest(), value['expected_normalized_sha256'])

    def test_tampering_fails(self):
        with tempfile.TemporaryDirectory() as d:
            r = Path(d)
            (r / 'docs/provenance').mkdir(parents=True)
            p = r / 'input.json'
            p.write_text('original')
            (r / 'docs/provenance/artifact_checksums.json').write_text(json.dumps({'input.json': sha256(p)}))
            p.write_text('altered')
            with self.assertRaises(ValueError):
                verify(r)

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            contained(ROOT, '../elsewhere')

    def test_complete_schedule(self):
        validate_units(self.rows, self.entries, self.schedule)

    def test_missing_rejected(self):
        with self.assertRaises(ValueError):
            validate_units(self.rows[:-1], self.entries, self.schedule)

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            validate_units(self.rows[:-1] + self.rows[:1], self.entries, self.schedule)

    def test_bad_repeat_rejected(self):
        self.rows[0]['repeat'] = True
        with self.assertRaises(ValueError):
            validate_units(self.rows, self.entries, self.schedule)

    def test_nonzero_failure_rejected(self):
        r = next(r for r in self.rows if r['failure_category'])
        r['file_recall5'] = 1
        with self.assertRaises(ValueError):
            validate_units(self.rows, self.entries, self.schedule)

    def test_infra_failure_rejected(self):
        self.rows[0]['failure_category'] = 'transport_error'
        with self.assertRaises(ValueError):
            validate_units(self.rows, self.entries, self.schedule)

    def test_unreviewed_field_rejected(self):
        self.rows[0]['raw_text'] = 'must never be accepted'
        with self.assertRaises(ValueError):
            validate_units(self.rows, self.entries, self.schedule)

    def test_aggregate_entries_not_repeats(self):
        means = aggregate(self.rows, True)
        self.assertEqual(len(means), 80 * 3)
        self.assertTrue(all(isinstance(v[0], Fraction) for v in means.values()))

    def test_frozen_bh_monotonic(self):
        fn = pure_functions(ROOT / 'experiments/s0_frozen/code/confirmatory_stats.py', ('bh_fdr',))
        q = fn['bh_fdr']([.01, .04, .03, .8])
        for a, b in zip(q, [.04, .05333333333333334, .05333333333333334, .8]):
            self.assertAlmostEqual(a, b)

    def test_printed_precision_binary_tie(self):
        displayed(.24374999999999997, '.2438')
        with self.assertRaises(ValueError):
            displayed(.2436, '.2438')

    def test_frozen_scorer_definitions(self):
        # Pure function extraction bypasses S1's core/model imports.
        import ast
        ns = {'Fraction': Fraction}
        path = ROOT / 'experiments/s1_frozen/code/analysis.py'
        nodes = [n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name in ('scores', 'interval')]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), ns)
        row = dict(ep_file='a.py', co_file='b.py', ep_line='10', co_line='100')
        answer = {'candidate_files': [{'path': 'a.py', 'line_start': 1, 'line_end': 1000}]}
        self.assertEqual(ns['scores'](row, answer), (Fraction(1, 2), Fraction(1, 2)))
        self.assertEqual(ns['scores'](row, answer, 64)[1], 0)
        self.assertEqual(ns['scores'](row, None), (0, 0))

    def test_no_network_or_subprocess_for_full_reproduction(self):
        # Actual full statistical recomputation; fail if it opens a socket/process.
        with patch('socket.socket', side_effect=AssertionError('network forbidden')), \
             patch('subprocess.Popen', side_effect=AssertionError('process forbidden')):
            for study in ('s0', 's1'):
                result = compute(ROOT, study)
                self.assertEqual(result['official_and_paper_checks'], 'PASS')
                self.assertEqual(result['entries'], 80)
                self.assertEqual(result['units'], 720)

    def test_readme_table_matches_paper(self):
        readme = (ROOT / 'README.md').read_text()
        paper = (ROOT / 'paper/tables/revision_means.tex').read_text()
        import re
        for study, arm, fr, lr, failures in re.findall(r'(S[01]) & (Agent|RAG|Pack) & ([0-9.]+) & ([0-9.]+) & (\d+)/240', paper):
            self.assertIn(f'| {study} | {arm} | {fr} | {lr} | {failures}/240 |', readme)

    def test_nonfinite_displayed_rejected(self):
        displayed(.24375, '0.2438')
        displayed(.24376, '0.2438')
        for bad in ('nan', 'NaN', 'inf', '-inf', '1e309', 'abc', None):
            with self.assertRaises(ValueError):
                displayed(.24375, bad)
        with self.assertRaises(ValueError):
            displayed(float('nan'), '0.2438')

    def test_nonfinite_close_and_tree_rejected(self):
        from vulnloc.reproduce import close
        with self.assertRaises(ValueError):
            close(float('nan'), 0.0, 'x')
        with self.assertRaises(ValueError):
            close(0.0, float('inf'), 'x')
        with self.assertRaises(ValueError):
            assert_finite_tree({'x': [float('nan')]})

    def test_provenance_complete_and_no_private_paths(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'results'
            run(ROOT, ('s0', 's1'), out)
            for study in ('s0', 's1'):
                value = json.loads((out / f'{study}_statistics.json').read_text())
                inputs = value['provenance']['inputs_sha256']
                self.assertIn('data/processed/entries.json', inputs)
                self.assertIn('requirements.txt', inputs)
                self.assertIn('docs/METHODS.md', inputs)
                self.assertIn('paper/tables/revision_means.tex', inputs)
                self.assertIn(f'experiments/{study}_frozen/code/', ' '.join(inputs))
                self.assertFalse(any('/home/' in key for key in inputs))
                self.assertFalse(any('/home/' in str(v) for v in inputs.values()))

    def test_all_and_single_study_tables(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'results'
            run(ROOT, ('s0', 's1'), out)
            all_rows = (out / 'main_results.csv').read_text()
            self.assertEqual(len(all_rows.splitlines()), 7)
            payload = load_site_data(ROOT, out)
            self.assertEqual(set(payload['studies']), {'s0', 's1'})
            combined_hash = sha256(out / 'main_results.csv')
            json_hash = sha256(out / 'main_results.json')
            s1_stats_hash = sha256(out / 's1_statistics.json')
            run(ROOT, ('s0',), out)
            self.assertEqual(sha256(out / 'main_results.csv'), combined_hash)
            self.assertEqual(sha256(out / 'main_results.json'), json_hash)
            self.assertEqual(sha256(out / 's1_statistics.json'), s1_stats_hash)
            self.assertEqual(len((out / 'main_results_s0.csv').read_text().splitlines()), 4)
            self.assertEqual(len((out / 'main_results_s1.csv').read_text().splitlines()), 4)
            s0_stats_hash = sha256(out / 's0_statistics.json')
            run(ROOT, ('s1',), out)
            self.assertEqual(sha256(out / 'main_results.csv'), combined_hash)
            self.assertEqual(sha256(out / 'main_results.json'), json_hash)
            self.assertEqual(sha256(out / 's0_statistics.json'), s0_stats_hash)

    def test_site_data_rejects_missing_or_tampered(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'results'
            run(ROOT, ('s0', 's1'), out)
            (out / 'main_results_s1.csv').unlink()
            with self.assertRaises(ValueError):
                load_site_data(ROOT, out)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / 'results'
            run(ROOT, ('s0', 's1'), out)
            payload = json.loads((out / 'main_results.json').read_text())
            payload['studies']['s1']['arms']['agent']['file_recall5'] = 0.99
            (out / 'main_results.json').write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                load_site_data(ROOT, out)

    def test_s0_top5_audit_records_zero_effect(self):
        audit = json.loads((ROOT / 'audit/s0_top5_lr/results.json').read_text())
        self.assertEqual(audit['records'], 720)
        self.assertEqual(audit['affected_record_count'], 0)
        self.assertEqual(audit['raw_records_over_5'], 0)
        self.assertEqual(audit['parsed_records_over_5'], 0)
        self.assertEqual(audit['status'], 'PASS_ZERO_EFFECT')


class ScannerTests(unittest.TestCase):
    def _run(self, root):
        out = (ROOT / '.local' / 'p26-test-scan.json') if root == ROOT else root / 'scan.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/scan_candidate.py'), '--root', str(root), '--output', str(out)],
            capture_output=True, text=True,
        )
        return proc, json.loads(out.read_text())

    def _init_repo(self, root):
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        subprocess.run(['git', 'add', '.'], cwd=root, check=True)

    def test_synthetic_strong_key_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'secret.txt').write_text('sk-ant-api03-' + 'A' * 30)
            self._init_repo(root)
            proc, report = self._run(root)
            self.assertNotEqual(proc.returncode, 0)
            self.assertGreater(report['blocking_count'], 0)
            self.assertFalse(report['packaging_ready'])

    def test_directory_symlink_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'site').mkdir()
            (root / 'private').mkdir()
            (root / 'private/secret.txt').write_text('not a credential')
            (root / 'site/link').symlink_to(root / 'private', target_is_directory=True)
            self._init_repo(root)
            proc, report = self._run(root)
            self.assertNotEqual(proc.returncode, 0)
            self.assertTrue(any(x['reason'] == 'symlink' for x in report['blocked_paths']))

    def test_normal_candidate_is_review_only(self):
        proc, report = self._run(ROOT)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(report['blocking_count'], 0)
        self.assertTrue(report['packaging_ready'])
        self.assertGreater(report['review_count'], 0)
        self.assertFalse(report['release_authorized'])


if __name__ == '__main__':
    unittest.main()
