# Metrics-only data card

Study identities:
- S0: `c06-confirmatory-20261001T141449Z-4dad`
- S1: `c06-recovery-v3-formal-20261005T142520Z-56b7`

`data/processed/{s0,s1}/metrics.json` contains exactly 720 records each with:
`entry_id`, `arm`, integer `repeat`, `file_recall5`, `line_recall5`,
`failure_category`. Scores take values 0/.5/1. Failures are retained, not imputed.
`entries.json` contains 80 entry IDs, repository cluster IDs and frozen
description-only PATH_HINT flags; no title, description, target path or line labels.
Description-only NO_PATH_HINT does not mean title-free or clue-free input.

S0 has no official processed per-unit scores. Its derivative was extracted from
the independent audit `scores.csv` (1,440 rows across both studies), then every
row was compared to raw saved answers using the frozen scorer's actual function
AST. S1 matches those audit rows, the frozen scorer and official `per_record.json`.
The raw records' hashes and formal processed output hashes were verified against
saved official provenance. This packaging verification is not a new model experiment.

`official.json` retains original S0 stats / S1 summary bytes. S1 also retains
`official_per_record.json` (numeric fields plus failure labels, no model text).
`source_provenance.json` is a new path-sanitized derivative; never present its bytes
as the original provenance. Original SHA256 values are in `docs/provenance/`.
Source-relative hash catalogs contain filenames and hashes, not excluded contents.

Excluded: raw answers, prompts, thinking, tool results, third-party source chunks,
advisory text, all model-event logs, embeddings, indexes, repository checkouts,
unreviewed internal notes. Full source manifests/freeze contracts containing
advisory/personal-path content are not silently 'cleaned' into historical originals.
Only code/configs are promised byte-identical; their original home paths are
documented release blockers. No independent raw backup has been verified.

S0 has a historical Top-5 implementation difference: its LR function did not
apply a second `[:5]`, but its frozen parser already truncated candidates to
five. The audit `audit/s0_top5_lr/results.json` found 0/720 records with more
than five raw or parsed candidates; strict Top-5 LR equals official S0 LR for
all records. This is documented as an implementation note, not a rescoring.

`paper/artifact_manifest.json` and `paper/provenance.json` are **engineering-
derived candidate documents**, not historical originals. Historical processed
provenance is retained as path-sanitized `source_provenance.json`; original
hashes are in `docs/provenance/copied_files.json`.

Limitations: L1 cannot reassess labels, compute new scoring policies, or verify
model identity/provider wire data. Access to private raw originals would be needed.
The published metrics-only data and manuscript/figures are licensed CC BY 4.0;
software is Apache-2.0. Individual author names, affiliation, venue and DOI remain
PENDING. Upstream VulnGym attribution is retained; no third-party repository
source is distributed. See `LICENSING.md`, `LICENSE-DATA` and
`THIRD_PARTY_NOTICES.md`.
