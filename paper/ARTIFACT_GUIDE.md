# Public-candidate artifact guide

This is a **candidate-scoped** guide, not the internal historical guide. It
documents only files shipped in this repository. The original research tree,
raw model conversations, repository checkouts, indexes, historical launch
contracts and the 74-repository identity index are intentionally excluded.

## Study identities

- S0: `c06-confirmatory-20261001T141449Z-4dad` — original confirmatory study.
- S1: `c06-recovery-v3-formal-20261005T142520Z-56b7` — supplemental study on the
  same known 80 entries. S1 is not an independent confirmation and is not pooled
  with S0.

## Offline L1 commands

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/vulnloc verify
.venv/bin/vulnloc reproduce            # both studies; writes the shared six-row table
.venv/bin/vulnloc reproduce --study s0 # S0-only files; does not rewrite the shared table
.venv/bin/vulnloc reproduce --study s1 # S1-only files; does not rewrite the shared table
.venv/bin/vulnloc verify-results       # six-row website-data validation
.venv/bin/python -m unittest discover -s tests -v
```

L1 reads only `data/processed/`, frozen scoring/statistics source, the paper
tables, `docs/METHODS.md` and `requirements.txt`. It never reads raw model output,
repository checkouts or provider credentials. It does not call a model API.

## Included data

| Path | Contents |
|---|---|
| `data/processed/entries.json` | 80 entry IDs, repository cluster IDs, description-only hint flags |
| `data/processed/s0/metrics.json` | 720 metrics-only S0 rows; no model text or labels |
| `data/processed/s1/metrics.json` | 720 metrics-only S1 rows; no model text or labels |
| `data/processed/{s0,s1}/official.json` | Original S0 stats / S1 summary reference |
| `data/processed/s1/official_per_record.json` | Official S1 numeric per-record reference |
| `data/processed/{s0,s1}/schedule.csv/json` | Frozen schedules |
| `results/main_results.json` | Six-row validated website interface; generated only by `--study all` |
| `results/main_results_{s0,s1}.csv` | Per-study three-row tables |
| `results/{s0,s1}_statistics.json` | Recomputed contrasts and complete input hashes |

## Excluded evidence

The candidate does **not** contain raw `records.jsonl`, prompts, thinking, tool
results, third-party source chunks, advisory descriptions, event logs, embeddings,
indexes, repository checkouts, or the historical internal artifact manifest.
Therefore L2 raw-dependent figure regeneration and L3 online collection are not
available. Saved manuscript figures are retained as static paper assets, not
represented as newly regenerated.

## Provenance

`paper/provenance.json` and `paper/artifact_manifest.json` are **engineering-
derived candidate documents**. They are not historical frozen provenance and must
not be cited as the original research records. Historical processed provenance is
preserved separately under `data/processed/{s0,s1}/source_provenance.json` as a
path-sanitized derivative; its original source hashes are listed in
`docs/provenance/copied_files.json`.

## License/authorization

No blanket copyright license is granted. See `LICENSE`, `LICENSE-DATA`,
`THIRD_PARTY_NOTICES.md` and `docs/RELEASE_CHECKLIST.md`. Author, institution,
DOI and venue are pending human approval.
