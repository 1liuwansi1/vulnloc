# Reproduction levels

## L1 — implemented

```bash
.venv/bin/vulnloc verify
.venv/bin/vulnloc reproduce                 # both studies; six-row shared table
.venv/bin/vulnloc reproduce --study s0      # S0-only files; shared table untouched
.venv/bin/vulnloc reproduce --study s1      # S1-only files; shared table untouched
.venv/bin/vulnloc verify-results            # six-row website-data validation
# Equivalent:
.venv/bin/python scripts/reproduce_stats.py --study all
```

Checks hashes, 720 unique units/study, schedule equality, 80 entries, allowed score
schema, zero scores for failures, exact historical statistics and official
references. Compares all five contrasts and S0 d_z/Wilcoxon, then manuscript main
table, S1 primary CI and key contrast macros. Tolerance: 1e-12 for numerical
references; manuscript contrast differences are checked within half one unit of
their last printed decimal (0.00005 + 1e-12 at four places). This explicitly
handles the historical RAG–Pack LR binary value just below 0.24375 displayed as
0.2438. Reference JSON is compared at full precision, not this display tolerance.
NaN and infinities are rejected before any comparison.

Outputs: `results/{s0,s1}_statistics.json`, per-study
`main_results_{s0,s1}.csv/.md`, and — **only for `--study all`** — the combined
`main_results.csv`, `main_results.md`, `main_results.json`. Single-study runs never
rewrite the combined table; they cannot silently drop the other study. The
website must read `main_results.json` through `vulnloc verify-results`, which
requires exactly six study/arm rows plus both per-study tables and rejects
missing, duplicate, tampered or non-finite data.

Each statistics file records SHA256 for global entries, study metrics/official
references/schedule, the frozen statistical source, paper tables, METHODS and
requirements, plus Python/NumPy and analysis seeds. These are engineering-derived
L1 provenance records, not historical raw provenance.

## L2 — incomplete

Existing manuscript figures are saved assets, not regenerated in this build.
Delivery/width/input figures need excluded raw delivery spans, model call usage
and/or third-party dataset/code. No pretend 'reproduce all' command is provided.
The main statistical table is regenerated under L1, not a full L2 certification.

## L3/L4 — not implemented in public wrapper

Historical online runners are retained but must NOT be run from this artifact.
They depend on historical layout, absolute Pi paths, missing manifests/indexes,
credentials and launch contracts. There is no supported provider adapter or online
CLI. Future work requires explicit paid-call consent and separate output/version.
No future provider backend can guarantee identical historical responses.

## Paper build

`make paper` builds the included snapshot into ignored `.local/tex-build/` if
TeX packages are installed, without overwriting the saved paper PDF. This does not regenerate
figures or revalidate every claim. Author/institution/venue/DOI are still pending.
Existing comments refer to original generators and provenance that require excluded
raw data; see file mappings instead of assuming those commands work here.
