# Frozen methods and statistical units

S0 is the original confirmatory comparison; S1 is a supplemental comparison on
the same known 80 entries, not independent replication. There are 13 imbalanced
repository groups (45 entries from the dominant group). Hosted model randomness
and multiple bundled changes prevent causal interpretation of S0–S1 differences.

FR@5 is the fraction of the one or two unique EP/CO file paths covered by the
top-five predictions. LR@5 has a denominator of two annotations and credits
same-file predicted-interval overlap with ±5-line tolerance. It is NOT exact line
accuracy, precision, evidence correctness, exploit validity or unknown-bug detection.
Wide predicted intervals can receive credit. Output failures retain zero scores.

**S0 LR implementation note.** The historical S0 `line_recall()` did not apply a
second Top-5 slice, whereas S1 `scores()` did. However, the frozen S0 parser
(`common.parse_final_answer`) already truncated `candidate_files` to five, so the
missing slice was non-operative. The independent audit in
`audit/s0_top5_lr/results.json` found 0/720 S0 records with more than five raw or
parsed candidates; strict Top-5 LR equals the frozen S0 LR for every record.
This is a historical implementation difference, not a change to S0 scores. The
S0 numbers remain frozen and are not recomputed.

Each entry/arm has exactly three repeats; average these BEFORE paired differences.
Primary: Agent minus Pack FR@5. Secondary family (BH q=.10) consists of Agent–RAG
and RAG–Pack for FR@5 and LR@5, exactly four members. Bootstrap: 10,000; sign-flip
Monte Carlo: 100,000. Entry independence is an assumption, not demonstrated by
distinct advisory IDs. No CR2 analysis is supplied here.

Both official calls use seed 20260928, but implementations DIFFER:

- S0: Python `random.Random`; discard zero differences for permutation; plus-one
  correction rounded to four decimals, then BH on rounded values. Percentile
  endpoints use sorted order-statistic indices; Cohen d_z and approximate
  tie-adjusted Wilcoxon use the frozen implementation.
- S1: NumPy default_rng; Fraction arithmetic for repeat means, integer-scaled
  differences; int8 sign draws in blocks of 2048, including zeros. Bootstrap uses
  the SAME RNG **after** sign draws; quantile interpolation is NumPy's default.
  BH uses unrounded probabilities. The offline wrapper explicitly passes 20260928,
  not `paired()`'s default 20261003. It does not invent S1 Wilcoxon/d_z values.

Historical S0 p=0.0000 is rounded finite Monte Carlo output, **not a true zero
probability**. Frozen comments occasionally call the randomized test 'exact';
the actual 100,000-draw procedure is Monte Carlo. Do not repair historical numbers
or comments in-place. Wider repository diagnostics and raw-based metrics are
outside the L1 completion claim.
