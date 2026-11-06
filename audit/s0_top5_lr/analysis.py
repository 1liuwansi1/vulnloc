#!/usr/bin/env python3
"""Independent S0 LR Top-5 sensitivity audit.

Reads historical raw answers, frozen parser/scorer, and the frozen manifest.
Writes only aggregate counts/scores; never writes prompts, model text, file paths,
target labels, or repository source. Does not modify source research assets.
"""
import argparse
import ast
import collections
import json
import re
import sys
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode = True


def load_pure(path, names, ns=None):
    ns = dict(ns or {})
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes} != set(names):
        raise ValueError(f"Missing frozen functions in {path}")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), ns)
    return ns


def full_raw_candidate_count(text):
    """Count candidate_files in the raw JSON without applying the frozen [:5] cap."""
    value = (text or "").strip()
    value = re.sub(r"```(?:json)?", "", value)
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(value[start:end + 1])
    except json.JSONDecodeError:
        return None
    candidates = obj.get("candidate_files")
    return len(candidates) if isinstance(candidates, list) else None


def score_lr(row, answer, line_recall, top5=False):
    """Call the frozen LR function; only optionally supply a strict Top-5 copy."""
    if top5 and answer is not None:
        answer = dict(answer)
        answer["candidate_files"] = list(answer.get("candidate_files", []))[:5]
    return line_recall(row, answer)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    source = Path(args.source_root).resolve()
    run = source / "07_results/raw/c06-confirmatory-20261001T141449Z-4dad"
    manifest = source / "06_experiments/c06/confirmatory_sample_manifest.csv"
    if not (run / "records.jsonl").is_file() or not manifest.is_file():
        raise SystemExit("Private S0 raw records or manifest not found")
    import csv
    rows = {
        r["entry_id"]: r
        for r in csv.DictReader(manifest.open(encoding="utf-8"))
        if r["role"] == "confirmatory"
    }
    scoring = load_pure(
        source / "06_experiments/scripts/c06/evaluate.py",
        ("_parse_lines", "line_recall"),
    )
    data = load_pure(
        source / "06_experiments/scripts/c06/common.py",
        ("_try_json", "_strip_wrappers", "parse_final_answer"),
        {"json": json, "re": re},
    )
    original = collections.defaultdict(list)
    strict = collections.defaultdict(list)
    raw_lengths = collections.Counter()
    parsed_lengths = collections.Counter()
    affected = []
    diffs = []
    n = 0
    for line in (run / "records.jsonl").open(encoding="utf-8"):
        rec = json.loads(line)
        n += 1
        row = rows[rec["entry_id"]]
        answer = rec.get("answer")
        raw_count = full_raw_candidate_count(rec.get("raw_text", ""))
        parsed_count = len((answer or {}).get("candidate_files", []))
        raw_lengths[raw_count] += 1
        parsed_lengths[parsed_count] += 1
        old = float(scoring["line_recall"](row, answer))
        new = float(score_lr(row, answer, scoring["line_recall"], top5=True))
        original[(rec["entry_id"], rec["arm"])].append(old)
        strict[(rec["entry_id"], rec["arm"])].append(new)
        if old != new:
            affected.append({
                "entry_id": rec["entry_id"],
                "arm": rec["arm"],
                "repeat": rec["repeat"],
                "raw_candidate_count": raw_count,
                "parsed_candidate_count": parsed_count,
                "original_lr": old,
                "strict_top5_lr": new,
            })
        diffs.append(abs(old - new))
    if n != 720:
        raise SystemExit(f"Expected 720 S0 records, got {n}")

    def mean_by_arm(values):
        result = {}
        for arm in ("agent", "rag", "pack"):
            entries = sorted({e for (e, a) in values if a == arm})
            entry_means = [
                sum(values[(e, arm)]) / len(values[(e, arm)]) for e in entries
            ]
            result[arm] = {
                "entries": len(entries),
                "repeats_per_entry": 3,
                "line_recall5_mean": sum(entry_means) / len(entry_means),
            }
        return result

    out = {
        "audit": "S0 LR Top-5 sensitivity",
        "source_run": "c06-confirmatory-20261001T141449Z-4dad",
        "scope": "read-only raw verification; no model calls",
        "records": n,
        "raw_candidate_lengths": {str(k): v for k, v in sorted(raw_lengths.items(), key=lambda x: (x[0] is None, x[0]))},
        "parsed_candidate_lengths": {str(k): v for k, v in sorted(parsed_lengths.items(), key=lambda x: (x[0] is None, x[0]))},
        "raw_records_over_5": sum(v for k, v in raw_lengths.items() if k is not None and k > 5),
        "parsed_records_over_5": sum(v for k, v in parsed_lengths.items() if k is not None and k > 5),
        "affected_record_count": len(affected),
        "affected_records": affected,
        "max_abs_record_difference": max(diffs) if diffs else 0.0,
        "original": mean_by_arm(original),
        "strict_top5": mean_by_arm(strict),
        "conclusion": (
            "No effect. The frozen S0 parser already truncates candidate_files to five; "
            "every S0 raw and parsed candidate list contains at most five entries, so "
            "strict Top-5 LR is identical to the historical S0 LR for all 720 records."
            if not affected
            else "EFFECT DETECTED: strict Top-5 changes S0 LR; escalate as a scientific correctness risk."
        ),
    }
    if affected:
        out["status"] = "SCIENTIFIC_CORRECTNESS_RISK"
    else:
        out["status"] = "PASS_ZERO_EFFECT"
    out["candidate_list_source"] = (
        "raw_text JSON candidate_files before the frozen parser; parsed answer after parse_final_answer()"
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in (
        "records", "raw_records_over_5", "parsed_records_over_5",
        "affected_record_count", "max_abs_record_difference", "status",
    )}, indent=2))
    if affected:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
