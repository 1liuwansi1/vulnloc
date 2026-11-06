# Historical frozen source — inspection only

`s0_frozen/code` and `s1_frozen/code` contain byte-identical historical source.
Configs retain their original bytes and old directory layout. Do not edit or run
the online runners, provider probes or historical tests indiscriminately: they
can call paid APIs or write data. No executable permissions were copied.

Only allowlisted pure statistical functions are used by the offline wrapper:
S0 `confirmatory_stats.py`, S1 `analysis.py:paired,bh`. Their module imports,
command-line main functions and model transports are never executed.

Historical naming notes (do not edit the frozen bytes): S0 `cliffs_delta()`
actually computes Cohen's d_z; the S0 BH comment says "5 members" but the frozen
secondary family has four members. S0 `line_recall()` does not apply a second
Top-5 slice, but its frozen parser already truncates candidates to five; the
zero-impact audit is in `audit/s0_top5_lr/results.json`.

Full original manifests contain advisory text or personal paths and are excluded;
hash-only identity evidence is in `docs/provenance/`. Missing launch dependencies
are intentional. A future portable online system must live outside these folders.
