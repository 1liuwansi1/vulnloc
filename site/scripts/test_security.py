"""Isolated negative tests: never mutate research inputs or real dist files."""
import csv
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
import json
import shutil
import importlib.util
import subprocess
import sys
from unittest.mock import patch

from scan_dist import scan
from validate_data import ROOT, COLUMNS, compare, read_json, safe_file, validate, validate_csv, validate_provenance
from vulnloc.reproduce import PROVENANCE_SCOPE, environment
from source_boundary import validate as validate_source


class SecurityTests(unittest.TestCase):
    def setUp(self):
        approved = Path('/tmp/opencode')
        self.temp = tempfile.TemporaryDirectory(prefix="vulnloc-site-", dir=approved if approved.is_dir() else None)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dist = self.root / "dist"
        self.public = self.root / "public"
        self.dist.mkdir()
        self.public.mkdir()
        (self.dist / "index.html").write_text("<!doctype html><h1>Public study</h1>")

    def test_clean(self):
        self.assertEqual(scan(self.dist, self.public), 1)

    def test_content(self):
        for text in ("/home/private/file", "/Users/private/file", "C:\\Users\\private", "data/raw/log",
                     "sk-" + "a" * 30, "-----BEGIN " + "PRIVATE KEY-----", "entry_id", "inputs_sha256",
                     "%2Fhome%2Fprivate", r"\u002fhome/private", "//# sourceMappingURL=a.map"):
            with self.subTest(text=text):
                (self.dist / "index.html").write_text(text)
                with self.assertRaises(ValueError):
                    scan(self.dist, self.public)

    def test_unapproved_files(self):
        for name in ("scores.json", "bundle.js", "archive.zip", ".env", "index.html.map"):
            path = self.dist / name
            path.write_text("innocent")
            with self.assertRaises(ValueError):
                scan(self.dist, self.public)
            path.unlink()

    def test_symlinks(self):
        (self.dist / "linked").symlink_to(self.public, target_is_directory=True)
        with self.assertRaises(ValueError):
            scan(self.dist, self.public)

    def test_public(self):
        (self.public / "private.txt").write_text("unused")
        with self.assertRaises(ValueError):
            scan(self.dist, self.public)

    def test_unknown_route_is_rejected(self):
        path = self.dist / 'raw'
        path.mkdir()
        (path / 'index.html').write_text('unapproved content')
        with self.assertRaises(ValueError):
            scan(self.dist, self.public)

    def test_nonfinite_and_types(self):
        for value in (float("nan"), float("inf"), True, "0.5"):
            with self.assertRaises(ValueError):
                compare(value, 0.5)
        with self.assertRaises(ValueError):
            compare({"x": 1, "extra": 2}, {"x": 1})

    def test_json_duplicates(self):
        path = self.root / "data.json"
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', '{"metadata":{"unchecked":-1e999}}'):
            path.write_text(text)
            with self.assertRaises(ValueError):
                read_json(path)

    def test_input_paths(self):
        for name in ("../escape", "/etc/passwd", ".local/private", ".venv/private.json", "data/raw/log", r"data\raw\log"):
            with self.assertRaises(ValueError):
                safe_file(self.root, name)

    def test_private_paths_and_escaped_null(self):
        for text in ('.venv/private.json', 'raw/private.txt', r'data\raw\log.txt', 'repos/source.txt', r'.venv\private.json'):
            (self.dist / 'index.html').write_text(text)
            with self.assertRaises(ValueError):
                scan(self.dist, self.public)
        (self.dist / 'index.html').write_text(r'<script>const sanitizer=/\u0000/g;</script>')
        self.assertEqual(scan(self.dist, self.public), 1)
        (self.dist / 'index.html').write_text('<code>.venv/bin/vulnloc verify</code><code>.venv/bin/python -m pip</code>')
        self.assertEqual(scan(self.dist, self.public), 1)

    def test_source_import_boundary(self):
        source = self.root / 'src'
        source.mkdir()
        page = source / 'page.astro'
        for value in ("import secret from '../../private.json'", "import fs from 'node:fs'", "const x = fetch('/private')", "const x=import.meta.glob('../../**')"):
            page.write_text(value)
            with self.assertRaises(ValueError):
                validate_source(self.root)
        page.write_text("import { useState } from 'react';")
        self.assertTrue(validate_source(self.root))
        (source / 'case.json').write_text('{}')
        with self.assertRaises(ValueError):
            validate_source(self.root)

    def test_css_url_import_boundary(self):
        source = self.root / 'src'
        source.mkdir()
        stylesheet = source / 'style.css'
        for value in (
            '@import url("../.local/private.css");',
            "@import url('../.local/private.css');",
            '@import url(../.local/private.css);',
            '@import/* comment */u/**/rl/**/("../private.css");',
            '@import URL ("../private.css");',
            '@import/**/"../../private.css";',
            '@im/**/port "../../private.css";',
            r'@import u\72l("../private.css");',
            'body { background: url(../private.svg); }',
        ):
            stylesheet.write_text(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_source(self.root)
        stylesheet.write_text('@import "tailwindcss"; body { color: #fff; }')
        self.assertTrue(validate_source(self.root))
        inline = source / 'page.astro'
        inline.write_text(r'<style>@import u\72l("../private.css");</style>')
        with self.assertRaises(ValueError):
            validate_source(self.root)

    def test_tracked_dependency_is_still_blocked(self):
        spec = importlib.util.spec_from_file_location('candidate_scan', ROOT / 'scripts/scan_candidate.py')
        scanner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scanner)
        dependency = self.root / 'node_modules'
        dependency.mkdir()
        (dependency / 'fixture.txt').write_text('synthetic dependency fixture')
        subprocess.run(['git', 'init', '-q'], cwd=self.root, check=True)
        subprocess.run(['git', 'add', 'node_modules/fixture.txt'], cwd=self.root, check=True)
        report = scanner.scan(self.root)
        self.assertFalse(report['packaging_ready'])
        self.assertTrue(any(p['path'] == 'node_modules/fixture.txt' for p in report['blocked_paths']))

    def test_release_gate_is_blocked_by_default(self):
        sys.path.insert(0,str(ROOT / 'scripts'))
        from check_publication_approval import check, FLAGS
        root = self.root / 'blocked'
        (root / 'docs').mkdir(parents=True)
        (root / 'docs/publication_approval.json').write_text(json.dumps({'schema_version':'1.0', **{flag:False for flag in FLAGS},
            'raw_backup_verified':False,'raw_backup_risk_accepted':False}))
        with self.assertRaises(ValueError):
            check(root)

    def test_approval_is_bound_to_exact_synthetic_candidate(self):
        sys.path.insert(0,str(ROOT / 'scripts'))
        from check_publication_approval import check, FLAGS
        from prepare_publication_manifest import manifest_bytes, candidate_manifest, protected_inputs
        root = self.root / 'publication'
        (root / 'docs').mkdir(parents=True)
        subprocess.run(['git','init','-q'],cwd=root,check=True)
        (root/'README.md').write_text('Synthetic fixture only')
        (root/'data/processed').mkdir(parents=True)
        (root/'data/processed/test.json').write_text('{}')
        (root/'docs/RELEASE_CHECKLIST.md').write_text('- [x] Synthetic fixture')
        approval = {'schema_version':'1.0', **{flag:True for flag in FLAGS}, 'approved_by':'Synthetic test fixture, not authorization',
                    'approved_at':'2026-11-06','github_owner':'synthetic-fixture','repository':'vulnloc',
                    'raw_backup_verified':False,'raw_backup_risk_accepted':True,
                    'candidate_manifest_sha256':hashlib.sha256(manifest_bytes(root)).hexdigest()}
        (root/'docs/publication_approval.json').write_text(json.dumps(approval))
        with patch.dict('os.environ', {'GITHUB_REPOSITORY':'synthetic-fixture/vulnloc'}):
            self.assertTrue(check(root))
            (root/'README.md').write_text('Changed fixture')
            with self.assertRaises(ValueError):
                check(root)
            approval['continuous_deployment_approved']=True
            approval['protected_inputs_sha256']=protected_inputs(root)
            (root/'docs/publication_approval.json').write_text(json.dumps(approval))
            self.assertTrue(check(root))
            (root/'data/processed/test.json').write_text('{"synthetic":true}')
            with self.assertRaises(ValueError):
                check(root)
        (root/'.env').write_text('synthetic fixture')
        with self.assertRaises(ValueError):
            candidate_manifest(root)

    def test_csv_tampering(self):
        arms = {a: {"file_recall5": .5, "line_recall5": .25, "failures": 0, "units": 240}
                for a in ("agent", "rag", "pack")}
        path = self.root / "table.csv"
        rows = [{"study": "s0", "arm": a, **v} for a, v in arms.items()]
        for bad in ("nan", "inf", "0.6"):
            altered = [dict(r) for r in rows]
            altered[0]["file_recall5"] = bad
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(altered)
            with self.assertRaises(ValueError):
                validate_csv(path, {"s0": {"arms": arms}})

    def test_provenance_exact_closure(self):
        # A synthetic hash-only input fixture: no real research files accessed.
        paths = ["data/processed/entries.json", "requirements.txt", "docs/METHODS.md",
                 "paper/tables/revision_means.tex", "paper/tables/revision_contrasts.tex",
                 "paper/tables/revision_numbers.tex",
                 "experiments/s0_frozen/code/confirmatory_stats.py",
                 "data/processed/s0/metrics.json"]
        for name in paths:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic")
        provenance = {"scope": PROVENANCE_SCOPE, "environment": environment(),
                      "inputs_sha256": {p: hashlib.sha256(b"synthetic").hexdigest() for p in paths}}
        validate_provenance(self.root, "s0", provenance)
        for mutation in ("missing", "extra", "wrong_hash", "wrong_environment"):
            altered = copy.deepcopy(provenance)
            if mutation == "missing":
                del altered["inputs_sha256"][paths[0]]
            elif mutation == "extra":
                altered["inputs_sha256"]["unapproved"] = "0" * 64
            elif mutation == "wrong_hash":
                altered["inputs_sha256"][paths[0]] = "0" * 64
            else:
                altered["environment"]["analysis_seed"] = 0
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_provenance(self.root, "s0", altered)

    def test_csv_shape(self):
        arms = {a: {"file_recall5": .5, "line_recall5": .25, "failures": 0, "units": 240}
                for a in ("agent", "rag", "pack")}
        rows = [{"study": "s0", "arm": a, **v} for a, v in arms.items()]
        path = self.root / "table.csv"
        for altered in (rows[:-1], rows + rows[:1],
                        [dict(rows[0], units="240.0"), *rows[1:]],
                        [dict(rows[0], study="s1"), *rows[1:]]):
            with path.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(altered)
            with self.assertRaises(ValueError):
                validate_csv(path, {"s0": {"arms": arms}})

    def test_full_gate_in_relocated_fixture(self):
        # Copy only approved small artifact inputs and wrappers, never local/raw.
        manifest = read_json(ROOT / 'docs/provenance/artifact_checksums.json')
        names = set(manifest) | {'docs/provenance/artifact_checksums.json'}
        for study in ('s0', 's1'):
            names |= set(read_json(ROOT / f'results/{study}_statistics.json')['provenance']['inputs_sha256'])
        names |= {p.relative_to(ROOT).as_posix() for p in (ROOT / 'src/vulnloc').glob('*.py')}
        names |= {p.relative_to(ROOT).as_posix() for p in (ROOT / 'results').glob('*') if p.is_file()}
        clone = self.root / 'artifact'
        for name in names:
            target = clone / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_file(ROOT, name), target)
        self.assertEqual(set(validate(clone)['studies']), {'s0', 's1'})
        stats = clone / 'results/s1_statistics.json'
        original = stats.read_text()
        changed = json.loads(original)
        changed['primary']['difference'] += .01
        stats.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            validate(clone)
        stats.write_text(original)
        changed = json.loads(original)
        changed['provenance']['inputs_sha256']['data/processed/entries.json'] = '0' * 64
        stats.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            validate(clone)


if __name__ == "__main__":
    unittest.main()
