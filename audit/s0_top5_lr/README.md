# S0 Line Recall Top-5 Audit

This directory contains an **independent, read-only audit** of a historical
implementation detail:

- S0 `evaluate.line_recall()` iterates the parsed `candidate_files` list without
  applying a second `[:5]` slice.
- S0 `common.parse_final_answer()` already truncates parsed candidates to five.
- S1 `analysis.scores()` applies `[:5]` to both FR and LR.

The audit asks whether the missing S0 slice changes any reported S0 LR@5 value.
It reads the private historical raw records only when `--source-root` is supplied;
the resulting JSON contains aggregate counts and scores, not prompts, model text,
repository paths, or labels. It is **not** part of L1 and must not be used by the
website.

Run (author machine only):

```bash
python3 audit/s0_top5_lr/analysis.py \
  --source-root /home/liuwansi/research/research-harness \
  --out audit/s0_top5_lr/results.json
```

The output records whether strict Top-5 LR equals the frozen S0 LR for all 720
records, plus counts of raw and parsed candidate-list lengths.
