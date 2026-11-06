# Release record — approved for publication 2026-11-06

Approved by the project owner (`1liuwansi1`) after the P4 publication request.
This file records decisions and disclosed residual risks; it is not a claim that
every possible external audit was performed.

## Engineering record

- [x] L1 reproduction, six-row combined table, per-study isolation, exact 720+720 units.
- [x] Provenance includes entries, study data, frozen statistics source, paper tables, METHODS and requirements.
- [x] Non-finite values rejected; scanner blocks synthetic strong credentials and symlinks.
- [x] Candidate artifact guide/manifest/provenance exist and are marked derived, not historical.
- [x] External clean-host reproduction was not available; local isolated-venv and independent static-host tests passed, and the owner accepts this residual limitation.
- [x] Professional secret scanner run on the exact candidate; 3 generic-key hits manually reviewed as SHA256 false positives (`docs/provenance/gitleaks_review.json`).
- [x] Manual PII/provenance/license review completed; historical paths, fixture identity and all known review items are disclosed and accepted below.

## Publication decisions

- [x] Copyright ownership, code provenance, coauthor and institutional permission confirmed by the project owner.
- [x] Code licensed Apache-2.0; metrics-only data, manuscript and figures licensed CC BY 4.0 (`LICENSING.md`).
- [x] Publication approved with individual authors, affiliation, venue and DOI explicitly PENDING; no attribution was invented.
- [x] Independent raw-backup verification was not performed by engineering; the owner accepts responsibility for preserving the private originals as a disclosed residual risk.
- [x] Human review of immutable historical home paths and fixture strings completed; frozen bytes remain unchanged, and `/home/...` plus `fixture@example.invalid` are accepted as historical/test records, not credentials.
- [x] Paper bibliography and PDF metadata reviewed: the PDF has no author or personal-path metadata; 15 of 16 public reference identities were checked, the PrimeVul DOI remains unverified, and the owner accepts this residual.
- [x] Professional secret scanner plus manual PII/provenance/license review completed for the reviewed candidate; this is not a formal guarantee about every binary or future file.
- [x] Third-party distribution decision: no third-party repository source is included; VulnGym v0.1.4 attribution is retained; advisory text, model outputs, embeddings and indexes remain excluded.
- [x] Fresh-host external reproduction was not performed; the disclosed local/isolated limitation is accepted.

## Publication boundary

The approved candidate is the explicit file list produced by
`scripts/prepare_publication_manifest.py`; internal review/build/publication
reports, `.local/`, `.venv/`, raw data, caches, `node_modules`, `dist` and the
generated website data are excluded. `docs/publication_approval.json` binds the
approval to this release. Continuous deployment is limited to ordinary site
updates; changes to protected scientific, legal, workflow or safety inputs
require renewed review.

This project is a research artifact, not a commercial vulnerability scanner.
S1 is not independent confirmation or a causal ablation.
