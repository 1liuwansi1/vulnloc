#!/usr/bin/env python3
"""Generate candidate-scoped paper artifact docs; explicitly not historical originals.

This script only writes paper/artifact_manifest.json and paper/provenance.json.
It does not alter results, frozen source, raw data or paper numbers.
"""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_PREFIXES = (
    "P25_", "P26_", "OPEN_SOURCE_BUILD_REPORT.md", "docs/provenance/",
)
EXCLUDE_FILES = {
    "paper/artifact_manifest.json",
    "paper/provenance.json",
}


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def candidate_paths():
    proc = subprocess.run(
        ["git", "--no-optional-locks", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    )
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "replace")
        if rel in EXCLUDE_FILES or rel.startswith(EXCLUDE_PREFIXES):
            continue
        path = ROOT / rel
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"Unsafe/missing candidate path: {rel}")
        yield rel, path


def main():
    files = {rel: sha256(path) for rel, path in sorted(candidate_paths())}
    manifest = {
        "schema_version": "1.0",
        "kind": "engineering_candidate_derived",
        "not_historical_original": True,
        "scope": (
            "Files distributed in the public candidate only. Raw model records, "
            "repository checkouts, indexes, historical launch contracts and the "
            "74-repository identity index are excluded."
        ),
        "study_ids": {
            "s0": "c06-confirmatory-20261001T141449Z-4dad",
            "s1": "c06-recovery-v3-formal-20261005T142520Z-56b7",
        },
        "files": files,
    }
    manifest_path = ROOT / "paper/artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    results = {
        study: sha256(ROOT / f"results/{study}_statistics.json")
        for study in ("s0", "s1")
    }
    provenance = {
        "schema_version": "1.0",
        "kind": "engineering_candidate_derived",
        "not_historical_original": True,
        "scope": (
            "Candidate provenance generated for the public L1 artifact; it is not "
            "the historical raw provenance and must not be cited as the original "
            "study record."
        ),
        "artifact_manifest_sha256": sha256(manifest_path),
        "l1_result_files": results,
        "source_relation": (
            "S0 original confirmatory study; S1 supplemental same-known-entry study. "
            "Separate reporting, no pooling, no independent-confirmation claim."
        ),
        "notes": [
            "Frozen source bytes are preserved; candidate docs are new engineering files.",
            "Historical raw data, model text and provider wire records are excluded.",
            "Authors, institution, license, DOI and venue remain pending approval.",
        ],
    }
    (ROOT / "paper/provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(f"Wrote candidate artifact manifest with {len(files)} files")


if __name__ == "__main__":
    main()
