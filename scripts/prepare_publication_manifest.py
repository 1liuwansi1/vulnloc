"""Read-only candidate selection; no staging, copying, network or publication."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FILES = {'.gitattributes', '.gitignore', '.env.example', 'README.md', 'LICENSE', 'LICENSE-DATA', 'LICENSING.md',
         'NOTICE', 'CITATION.cff', 'CONTRIBUTING.md', 'SECURITY.md', 'THIRD_PARTY_NOTICES.md',
         'Makefile', 'pyproject.toml', 'requirements.txt'}
DIRECTORIES = {'.github', 'audit', 'data', 'docs', 'experiments', 'paper', 'results', 'scripts', 'site', 'src', 'tests'}
INTERNAL = {'OPEN_SOURCE_BUILD_REPORT.md', 'P25_INDEPENDENT_REVIEW.md', 'P25_REMEDIATION_PLAN.md',
            'P26_REMEDIATION_REPORT.md', 'WEBSITE_BUILD_REPORT.md', 'GITHUB_PUBLICATION_REPORT.md',
            'docs/provenance/safety_scan.json', 'docs/provenance/publication_checksums.json'}
FORBIDDEN = {'.local', '.venv', 'raw', 'repos', 'node_modules', 'dist', '.astro', '__pycache__',
             'embedding_cache', 'index_cache', 'test-results', 'playwright-report'}
APPROVAL = 'docs/publication_approval.json'


def candidate_manifest(root=ROOT):
    root = Path(root).resolve()
    result = subprocess.run(['git', '--no-optional-locks', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                            cwd=root, check=True, capture_output=True)
    selected = sorted({x.decode('utf-8') for x in result.stdout.split(b'\0') if x})
    files = {}
    for relative in selected:
        if relative in INTERNAL or relative == APPROVAL:
            continue  # Approval is a separately reviewed sidecar, avoiding self-hash recursion.
        parts = Path(relative).parts
        if not parts or any(part in FORBIDDEN or part.startswith('.env') and relative != '.env.example' for part in parts):
            raise ValueError('Forbidden file selected for publication')
        if len(parts) == 1 and relative not in FILES or len(parts) > 1 and parts[0] not in DIRECTORIES:
            raise ValueError('File outside candidate allowlist')
        path = root
        for part in parts:
            path = path / part
            if path.is_symlink():
                raise ValueError('Selected symlink forbidden')
        if not path.is_file():
            raise ValueError('Selected file missing')
        if relative.startswith('data/') and not relative.startswith('data/processed/'):
            raise ValueError('Only processed data may be selected')
        files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not files:
        raise ValueError('Empty publication candidate')
    return {'schema_version': '1.0', 'kind': 'local_engineering_candidate_not_authorization',
            'approval_sidecar': APPROVAL, 'files': files}


def manifest_bytes(root=ROOT):
    return (json.dumps(candidate_manifest(root), indent=2, sort_keys=True) + '\n').encode()


def protected_inputs(root=ROOT):
    """Approved science/legal baseline; ordinary site-only updates may differ."""
    fixed = {'.gitattributes','requirements.txt','pyproject.toml','docs/METHODS.md','LICENSE','LICENSE-DATA',
             'LICENSING.md','NOTICE','CITATION.cff','THIRD_PARTY_NOTICES.md','docs/RELEASE_CHECKLIST.md',
             '.github/workflows/deploy.yml','scripts/check_publication_approval.py',
             'scripts/prepare_publication_manifest.py','scripts/scan_candidate.py',
             'site/astro.config.mjs','site/package.json','site/package-lock.json',
             'site/scripts/source_boundary.py','site/scripts/scan_dist.py',
             'site/scripts/validate_data.py','site/scripts/test_security.py'}
    return {p:h for p,h in candidate_manifest(root)['files'].items()
            if p in fixed or p.startswith(('data/', 'experiments/', 'paper/', 'src/vulnloc/'))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--protected-output', type=Path)
    args = parser.parse_args()
    data = manifest_bytes()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    if args.protected_output:
        args.protected_output.parent.mkdir(parents=True,exist_ok=True)
        args.protected_output.write_text(json.dumps(protected_inputs(),indent=2,sort_keys=True)+'\n')
    print('Local candidate manifest SHA256:', hashlib.sha256(data).hexdigest())
    print('Publication authorization is checked separately by check_publication_approval.py')
