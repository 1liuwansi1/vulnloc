# vulnloc

**Public research artifact.** Code is licensed under Apache-2.0; metrics-only
data, manuscript and figures are licensed under CC BY 4.0. Individual author
names, affiliation, venue and DOI remain explicitly **PENDING** and are not
invented. See `LICENSING.md`, `LICENSE`, `LICENSE-DATA` and
`THIRD_PARTY_NOTICES.md`.

**Website:** https://1liuwansi1.github.io/vulnloc/  
**English:** https://1liuwansi1.github.io/vulnloc/en/  
**中文:** https://1liuwansi1.github.io/vulnloc/zh/  
**Repository:** https://github.com/1liuwansi1/vulnloc

## Repository-level vulnerability localization

This project accompanies *Evidence Acquisition and Output Reliability for
Advisory-Guided Vulnerability Localization*. It compares read-only adaptive
exploration (Agent), single-round hybrid retrieval (RAG), and lexicographic
context packing (Pack), under a 50,000-token repository-information ceiling.
This ceiling does **not** equalize cumulative input, compute, latency or cost.

- **S0**: original confirmatory study, 80 entries × 3 arms × 3 repeats.
- **S1**: supplemental study on the **same known entries**, with bundled
  implementation changes; not an independent confirmation or causal ablation.
- Both use the recorded DeepSeek V4 Pro / high setting. Dataset-supplied titles
  may contain filename hints. Pack is a simple lexical reference, not a strong
  competitive baseline. Static-guided retrieval is not implemented.
- This is a research artifact, **not** a commercial vulnerability scanner.

## Start here (offline, no API key)

Python **3.12** is the validated interpreter; NumPy **2.5.3** is pinned to retain
the historical S1 numerical/RNG behavior. From this checkout:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/vulnloc verify
.venv/bin/vulnloc reproduce                 # both studies; six-row shared table
.venv/bin/vulnloc reproduce --study s0      # S0-only; shared table untouched
.venv/bin/vulnloc reproduce --study s1      # S1-only; shared table untouched
.venv/bin/vulnloc verify-results            # website-data contract check
.venv/bin/python -m unittest discover -s tests -v
```

The combined `results/main_results.csv/.md/.json` is produced only by the
all-studies command. A single-study run updates its own statistics and
`main_results_s0/s1.*` and deliberately leaves the combined table unchanged.

On Debian/Ubuntu, if venv reports missing `ensurepip`, install `python3.12-venv`
using your administrator's normal procedure, then retry. See [installation](docs/INSTALL.md)
for the local workaround actually used here. Package installation can download
dependencies; **reproduction itself is entirely offline** and needs no model SDK.

The CLI operates on a checkout (default `--root .`), not on a standalone wheel's
bundled data. It supports `verify`, `reproduce` and `verify-results`; no online runner is exposed.
Do not run historical runners in `experiments/`: they can spend money and depend
on excluded private assets. Their bytes are retained for inspection only.

## Main results

| Study | Arm | FR@5 | LR@5 | Output failures |
|---|---|---:|---:|---:|
| S0 | Agent | 0.8458 | 0.6583 | 6/240 |
| S0 | RAG | 0.7875 | 0.4917 | 0/240 |
| S0 | Pack | 0.4271 | 0.2375 | 0/240 |
| S1 | Agent | 0.7479 | 0.5813 | 31/240 |
| S1 | RAG | 0.7729 | 0.4938 | 0/240 |
| S1 | Pack | 0.4229 | 0.2500 | 0/240 |

Source: `data/processed/{s0,s1}/official.json` and
`paper/tables/revision_means.tex`. Generated full-precision results and paired
tests are in `results/`. Every failed model output remains in the denominator.
Three repeats are averaged **within entry** before inference (n=80, not 240).
S1 does not establish an Agent advantage over RAG in file recall.

## Artifact contents

| Directory | Contents |
|---|---|
| `experiments/s0_frozen/`, `s1_frozen/` | Byte-identical scientific source, historical configs; not portable online entrypoints |
| `data/processed/` | Metrics-only records, official reference statistics, schedules, minimal entry metadata |
| `src/vulnloc/` | New offline validation/aggregation wrapper; frozen source not edited |
| `results/` | Regenerated main table and five frozen contrasts per study |
| `paper/` | Existing manuscript snapshot, tables and figures; attribution still pending |
| `docs/provenance/` | Source hashes, extraction validation, file mappings, integrity manifest |
| `tests/` | Offline unit and end-to-end tests, including negative checks |
| `site/` | Bilingual static research website; local preview only, publication blocked |

## Bilingual website and verified data interface

The website is implemented in `site/`, preserving the research design and using
English `/vulnloc/en/` and Simplified Chinese `/vulnloc/zh/` static routes.
The language switch preserves the current page and query-backed chart/method
selection. Explicit preference is stored locally; browser language is considered
only at the root entry page. Both languages use the exact same verified data.

```bash
cd site
npm ci
npm run dev
npm run check
npm run test:security
npm run build
npm run preview
```

Local preview: `http://localhost:4321/vulnloc/`. See `site/README.md` and
`site/DEPLOYMENT.md`. The GitHub Pages workflow publishes only `site/dist/` after
the repository approval variable, release record, approval sidecar and
scientific/legal input baseline all pass. `docs/publication_approval.json`
records the owner's publication approval and the disclosed raw-backup residual
risk; it does not claim a verification that engineering did not perform.

The site reads only the validated L1 outputs:

- `results/main_results.json` — six study/arm rows, separate S0/S1 metadata;
- `results/main_results_{s0,s1}.csv` — per-study tables;
- `results/{s0,s1}_statistics.json` — contrasts, uncertainty and input hashes.

It must run `.venv/bin/vulnloc verify-results` before building and fail closed on
missing, duplicate, tampered or non-finite data. It must not read `.local/`,
`.venv/`, `data/raw/`, repository caches or model logs, and must not claim
pooled S0/S1 inference or an Agent advantage over RAG in S1 file recall.

## Scope and limitations

L1 reproduces FR/LR **aggregation and inference from validated stored scores**.
It does not independently rescore predictions without raw answers and labels.
S0 lacks an official processed per-unit file; its public scores are a new
metrics-only derivative of the independent audit CSV, verified row-by-row against
raw records and frozen scorers during packaging. S1 additionally matches the
official processed per-record file and saved output hash.

L2 raw-dependent figure regeneration and L3 online collection remain **incomplete**.
Saved paper figures are included, not represented as newly regenerated. Single
model, known samples, title hints, weak Pack and repository dependence limit
generalization. See [methods](docs/METHODS.md), [data card](docs/DATA_CARD.md),
[reproduction](docs/REPRODUCIBILITY.md) and the
[release record](docs/RELEASE_CHECKLIST.md).

No raw conversations, repository code caches, embeddings, virtual environment,
advisory descriptions or unreviewed logs are included in the published artifact.
The owner accepted publication while independent raw-backup verification remains
a disclosed residual risk; engineering did not verify a backup. The ignored
local working snapshot is not such a backup. **Do not archive or upload this
working directory wholesale:** ignored `.local/` contains an unsanitized private
protection snapshot. Only the reviewed candidate files are published.

## Citation and licensing

Source code is Apache-2.0. Metrics-only data, manuscript and figures are
CC BY 4.0. `CITATION.cff` records the repository citation while individual
authors, affiliation, venue and DOI remain PENDING. See `LICENSING.md`,
`LICENSE-DATA` and `THIRD_PARTY_NOTICES.md`.
