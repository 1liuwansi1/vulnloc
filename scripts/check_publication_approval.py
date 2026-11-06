"""Fail closed until explicit human approvals and the exact candidate are recorded."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from prepare_publication_manifest import manifest_bytes, protected_inputs

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ('release_approved', 'authorization_confirmed', 'licenses_confirmed', 'attribution_confirmed',
         'third_party_review_confirmed', 'privacy_review_confirmed')


def check(root=ROOT):
    value = json.loads((root / 'docs/publication_approval.json').read_text())
    if value.get('schema_version') != '1.0':
        raise ValueError('Unknown approval schema')
    if any(value.get(key) is not True for key in FLAGS):
        raise ValueError('Required human release approvals are not confirmed')
    if value.get('raw_backup_verified') is not True and value.get('raw_backup_risk_accepted') is not True:
        raise ValueError('Raw backup must be verified or its residual risk explicitly accepted')
    if any(not isinstance(value.get(key), str) or not value[key].strip() for key in
           ('approved_by', 'approved_at', 'github_owner', 'candidate_manifest_sha256')):
        raise ValueError('Missing approval identity, date, owner or candidate binding')
    if value.get('repository') != 'vulnloc' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', value['github_owner']):
        raise ValueError('Invalid approved repository identity')
    if re.search(r'\[ \]', (root / 'docs/RELEASE_CHECKLIST.md').read_text()):
        raise ValueError('Release checklist still contains unresolved gates')
    if value.get('continuous_deployment_approved') is True:
        expected = value.get('protected_inputs_sha256')
        if not isinstance(expected,dict) or not expected or expected != protected_inputs(root):
            raise ValueError('Scientific/legal inputs differ from continuous-deployment approval')
    elif hashlib.sha256(manifest_bytes(root)).hexdigest() != value['candidate_manifest_sha256']:
        raise ValueError('Candidate changed after initial approval')
    if os.environ.get('GITHUB_REPOSITORY', f"{value['github_owner']}/vulnloc").lower() != f"{value['github_owner']}/vulnloc".lower():
        raise ValueError('Actions repository does not match human-approved owner')
    return value


if __name__ == '__main__':
    try:
        check()
        print('PASS: documented human approvals and candidate binding')
    except (ValueError, OSError, KeyError) as error:
        print('BLOCKED:', str(error), file=sys.stderr)
        sys.exit(1)
