"""Offline L1: aggregate verified per-unit scores using frozen statistical rules.

No raw records, advisory texts, target paths, repository checkouts or model SDKs.
Only allowlisted pure statistical functions are extracted from frozen source ASTs;
imports and entrypoints in historical modules are NEVER executed.
"""
import ast
import csv
import json
import math
import platform
import random
import re
import statistics
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

import numpy as np

from .integrity import read_json, sha256, verify

ARMS = ("agent", "rag", "pack")
METRICS = ("file_recall5", "line_recall5")
FAMILY = (("agent", "rag", 0), ("rag", "pack", 0),
          ("agent", "rag", 1), ("rag", "pack", 1))
S0_NAMES = ("bootstrap_ci", "permutation_p", "wilcoxon_p", "cohens_dz", "bh_fdr")
STUDY_STATS = {
    "s0": "experiments/s0_frozen/code/confirmatory_stats.py",
    "s1": "experiments/s1_frozen/code/analysis.py",
}
PAPER_INPUTS = (
    "paper/tables/revision_means.tex",
    "paper/tables/revision_contrasts.tex",
    "paper/tables/revision_numbers.tex",
)
PROVENANCE_SCOPE = (
    "engineering-derived L1 provenance for the public candidate; "
    "not a historical raw provenance record"
)


def finite_number(value, label):
    """Reject NaN, infinities, and non-numeric display/statistical values."""
    try:
        number = float(value)
    except (TypeError, ValueError) as ex:
        raise ValueError(f"Non-numeric value: {label}") from ex
    if not math.isfinite(number):
        raise ValueError(f"Non-finite value: {label}")
    return number


def input_manifest(root, study):
    """Complete L1 input closure: global entries, study data, code, paper tables."""
    root = Path(root).resolve()
    paths = {
        Path("data/processed/entries.json"),
        Path(STUDY_STATS[study]),
        Path("requirements.txt"),
        Path("docs/METHODS.md"),
        *(Path(p) for p in PAPER_INPUTS),
        *(p.relative_to(root) for p in sorted((root / "data/processed" / study).glob("*")) if p.is_file()),
    }
    return {p.as_posix(): sha256(root / p) for p in sorted(paths, key=lambda p: p.as_posix())}


def environment():
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "analysis_seed": 20260928,
        "bootstrap_draws": 10000,
        "permutation_draws": 100000,
    }


def assert_finite_tree(value, label="result"):
    if isinstance(value, dict):
        for key, item in value.items():
            assert_finite_tree(item, f"{label}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_finite_tree(item, f"{label}[{index}]")
    elif isinstance(value, (float, int)) and not isinstance(value, bool):
        if not math.isfinite(value):
            raise ValueError(f"Non-finite result: {label}")


def pure_functions(path, names):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes} != set(names):
        raise ValueError("Frozen statistics functions missing")
    # Sources are first checked against the artifact SHA256 manifest by run().
    ns = {"math": math, "random": random, "statistics": statistics, "np": np}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), ns)
    return {name: ns[name] for name in names}


def validate_units(records, entries, schedule):
    ids = [r["entry_id"] for r in entries]
    if len(ids) != 80 or len(set(ids)) != 80:
        raise ValueError("Expected 80 unique entries")
    expected = {(e, a, i) for e in ids for a in ARMS for i in (1, 2, 3)}
    planned = [(r["entry_id"], r["arm"], r["repeat"]) for r in schedule]
    if len(planned) != 720 or set(planned) != expected:
        raise ValueError("Frozen schedule incomplete or duplicate")
    keys = []
    for r in records:
        if set(r) != {"entry_id", "arm", "repeat", *METRICS, "failure_category"}:
            raise ValueError("Unexpected fields in metrics-only data")
        if type(r["repeat"]) is not int:
            raise ValueError("Repeat must be an integer")
        keys.append((r["entry_id"], r["arm"], r["repeat"]))
        if r["failure_category"] not in (None, "invalid_json", "empty_answer"):
            raise ValueError("Unrecognized/infra failure in scientific outcomes")
        for metric in METRICS:
            v = r[metric]
            if type(v) not in (float, int) or v not in (0, 0.5, 1):
                raise ValueError("Invalid frozen score")
            if r["failure_category"] is not None and v != 0:
                raise ValueError("Failed model output must remain scored zero")
    if len(keys) != 720 or set(keys) != expected:
        raise ValueError("Missing, duplicate or extra inference units")


def aggregate(records, exact):
    cells = defaultdict(list)
    for r in records:
        values = tuple(Fraction(str(r[m])) if exact else float(r[m]) for m in METRICS)
        cells[(r["entry_id"], r["arm"])].append(values)
    # S0 uses statistics.mean; S1 preserves Fraction sums before division.
    return {k: tuple(sum(x[i] for x in v) / len(v) if exact
                     else statistics.mean(x[i] for x in v) for i in range(2))
            for k, v in cells.items()}


def close(actual, expected, label):
    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
            raise ValueError(f"Length mismatch: {label}")
        for i, (a, b) in enumerate(zip(actual, expected)):
            close(a, b, f"{label}[{i}]")
    else:
        actual_number = finite_number(actual, label + ".actual")
        expected_number = finite_number(expected, label + ".expected")
        if not math.isclose(actual_number, expected_number, rel_tol=0, abs_tol=1e-12):
            raise ValueError(
                f"Official/paper mismatch: {label}: {actual_number} != {expected_number}"
            )


def displayed(actual, expected, digits=4):
    """Check a printed decimal's precision, including binary floating-point ties.

    Do not change official numbers to force a particular formatting convention.
    Half one unit in the final printed place is the display precision bound;
    1e-12 only accommodates representation noise at its boundary. Non-finite
    values are rejected before subtraction so NaN cannot bypass the comparison.
    """
    actual_number = finite_number(actual, "displayed actual")
    expected_number = finite_number(expected, "displayed expected")
    if abs(actual_number - expected_number) > 0.5 * 10 ** (-digits) + 1e-12:
        raise ValueError(f"Manuscript display outside {digits}-decimal precision")


def compute(root, study):
    base = root / "data/processed" / study
    records = read_json(base / "metrics.json")
    entries = read_json(root / "data/processed/entries.json")
    if study == "s0":
        with (base / "schedule.csv").open(newline="") as f:
            schedule = [dict(entry_id=r["entry_id"], arm=r["arm"], repeat=int(r["repeat"]))
                        for r in csv.DictReader(f)]
    else:
        schedule = read_json(base / "schedule.json")
    validate_units(records, entries, schedule)
    means = aggregate(records, exact=study == "s1")
    ids = sorted(r["entry_id"] for r in entries)
    official = read_json(base / "official.json")
    failures = Counter(r["arm"] for r in records if r["failure_category"] is not None)
    arms = {a: {"file_recall5": sum(float(means[e, a][0]) for e in ids) / len(ids),
                "line_recall5": sum(float(means[e, a][1]) for e in ids) / len(ids),
                "failures": failures[a], "units": 240} for a in ARMS}
    if study == "s0":
        fn = pure_functions(root / "experiments/s0_frozen/code/confirmatory_stats.py", S0_NAMES)

        def paired(a, b, metric):
            d = [means[e, a][metric] - means[e, b][metric] for e in ids]
            return {"n": len(d), "mean": round(statistics.mean(d), 4),
                    "bootstrap_ci95": fn["bootstrap_ci"](d),
                    "cohens_dz": fn["cohens_dz"](d),
                    "permutation_p": fn["permutation_p"](d),
                    "wilcoxon_p": fn["wilcoxon_p"](d)}

        primary = paired("agent", "pack", 0)
        secondary = {f'{"fr" if m == 0 else "lr"}_{a}_vs_{b}': paired(a, b, m)
                     for a, b, m in FAMILY}
        qs = fn["bh_fdr"]([x["permutation_p"] for x in secondary.values()])
        ref = official["stats"]
        for key, v in primary.items():
            close(v, ref["primary"]["agent_vs_pack"][key], "s0.primary." + key)
        for (name, value), q in zip(secondary.items(), qs):
            for key, v in value.items():
                close(v, ref["secondary"][name][key], "s0." + name + "." + key)
            value["bh_q"] = q
            close(q, ref["secondary"]["bh_fdr_qvalues"][name], "s0." + name + ".q")
        for a, v in arms.items():
            close(round(v["file_recall5"], 4), ref["primary"]["arm_means_fr"][a], "s0.fr." + a)
            close(round(v["line_recall5"], 4), ref["secondary"]["arm_means_lr"][a], "s0.lr." + a)
    else:
        fn = pure_functions(root / "experiments/s1_frozen/code/analysis.py", ("paired", "bh"))

        def paired(a, b, metric):
            return fn["paired"]([means[e, a][metric] for e in ids],
                                [means[e, b][metric] for e in ids], seed=20260928)

        primary = paired("agent", "pack", 0)
        secondary = {f'{a}-{b}-{"fr" if m == 0 else "lr"}': paired(a, b, m) for a, b, m in FAMILY}
        qs = fn["bh"]([v["mc_sign_flip_p"] for v in secondary.values()])
        for key, v in primary.items():
            if key != "note":
                close(v, official["primary_agent_pack_fr"][key], "s1.primary." + key)
        for (name, value), q in zip(secondary.items(), qs):
            for key, v in value.items():
                if key != "note":
                    close(v, official["comparisons"][name][key], "s1." + name + "." + key)
            value["bh_q_unrounded"] = q
            close(q, official["comparisons"][name]["bh_q_unrounded"], "s1." + name + ".q")
        for a, v in arms.items():
            for key, orig in (("file_recall5", "fr_mean"), ("line_recall5", "lr_mean"), ("failures", "failure_count")):
                close(v[key], official["arms"][a][orig], "s1." + a + "." + key)
    # Cross-check the actual manuscript's main-results table, not just JSON summaries.
    table = (root / "paper/tables/revision_means.tex").read_text()
    matches = re.findall(r"(S[01]) & (Agent|RAG|Pack) & ([0-9.]+) & ([0-9.]+) & (\d+)/240", table)
    selected = [m for m in matches if m[0] == study.upper()]
    if len(selected) != 3:
        raise ValueError("Manuscript table rows missing")
    for _, arm, fr, lr, count in selected:
        v = arms[arm.lower()]
        close(round(v["file_recall5"], 4), float(fr), "paper.fr")
        close(round(v["line_recall5"], 4), float(lr), "paper.lr")
        close(v["failures"], int(count), "paper.failures")
    if study == "s1":
        text = (root / "paper/tables/revision_numbers.tex").read_text()
        macros = dict(re.findall(r"\\newcommand\{\\(SOne\w+)\}\{([^}]+)\}", text))
        for key, value in (("SOnePrimary", primary["difference"]),
                           ("SOneAgentRagFR", secondary["agent-rag-fr"]["difference"]),
                           ("SOneAgentRagFRP", secondary["agent-rag-fr"]["mc_sign_flip_p"]),
                           ("SOneAgentRagLR", secondary["agent-rag-lr"]["difference"]),
                           ("SOneAgentRagLRQ", secondary["agent-rag-lr"]["bh_q_unrounded"])):
            close(round(value, 4), float(macros[key]), "paper." + key)
        if macros["SOnePrimaryCI"] != "[" + ", ".join(f"{v:.4f}" for v in primary["entry_bootstrap_ci95"]) + "]":
            raise ValueError("Paper primary CI mismatch")
        contrasts = (root / "paper/tables/revision_contrasts.tex").read_text()
        for name, a, b, metric in [("Agent--Pack FR", "agent", "pack", "fr"),
                                  ("Agent--RAG FR", "agent", "rag", "fr"),
                                  ("Agent--RAG LR", "agent", "rag", "lr"),
                                  ("RAG--Pack FR", "rag", "pack", "fr"),
                                  ("RAG--Pack LR", "rag", "pack", "lr")]:
            value = primary if name == "Agent--Pack FR" else secondary[f"{a}-{b}-{metric}"]
            row = next((line for line in contrasts.splitlines() if line.startswith(name + " &")), None)
            if row is None:
                raise ValueError("Paper contrast row missing: " + name)
            columns = [v.strip() for v in row.removesuffix("\\\\").split("&")]
            displayed(value["difference"], columns[2])
            expected_ci = "[" + ", ".join(f"{v:.4f}" for v in value["entry_bootstrap_ci95"]) + "]"
            if columns[3] != expected_ci:
                raise ValueError("Paper contrast CI mismatch: " + name)
            for display, number in [(columns[4], value["mc_sign_flip_p"])] + (
                    [(columns[5], value["bh_q_unrounded"])] if value is not primary else []):
                if display == "$<0.0001$":
                    if not number < .0001:
                        raise ValueError("Paper p/q bound mismatch")
                else:
                    close(round(number, 4), float(display), "paper p/q")
    return {"study": study, "entries": 80, "units": 720, "arms": arms,
            "primary": primary, "secondary": secondary, "seed": 20260928,
            "bootstrap_draws": 10000, "permutation_draws": 100000,
            "official_and_paper_checks": "PASS",
            "scope": "L1 score aggregation; not raw answer re-scoring or model collection"}


def _study_rows(study, value):
    rows = []
    for arm in ARMS:
        item = value["arms"][arm]
        rows.append({
            "study": study,
            "arm": arm,
            "file_recall5": item["file_recall5"],
            "line_recall5": item["line_recall5"],
            "failures": item["failures"],
            "units": item["units"],
        })
    return rows


def _write_rows_csv(path, rows):
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["study", "arm", "file_recall5", "line_recall5", "failures", "units"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_rows_markdown(path, rows, title):
    lines = [title, "", "All failures retained; repeats averaged within each entry.", "",
             "| Study | Arm | FR@5 | LR@5 | Failures |", "|---|---|---:|---:|---:|"]
    for row in rows:
        lines.append(
            f'| {row["study"].upper()} | {row["arm"]} | '
            f'{row["file_recall5"]:.4f} | {row["line_recall5"]:.4f} | '
            f'{row["failures"]}/240 |'
        )
    Path(path).write_text("\n".join(lines) + "\n")


def _write_combined(dest, output):
    rows = []
    for study in ("s0", "s1"):
        if study not in output:
            raise ValueError("Combined table requires both s0 and s1")
        rows.extend(_study_rows(study, output[study]))
    expected = {(s, a) for s in ("s0", "s1") for a in ARMS}
    if len(rows) != 6 or {(r["study"], r["arm"]) for r in rows} != expected:
        raise ValueError("Combined table must contain exactly six study/arm rows")
    for row in rows:
        if row["units"] != 240:
            raise ValueError("Each arm must contain 240 inference units")
        finite_number(row["file_recall5"], "combined FR")
        finite_number(row["line_recall5"], "combined LR")
    _write_rows_csv(dest / "main_results.csv", rows)
    _write_rows_markdown(dest / "main_results.md", rows, "# Recomputed main results")
    payload = {
        "schema_version": "1.0",
        "scope": "L1 offline reproduction from validated stored scores; not raw re-scoring",
        "study_relation": (
            "S0 is the original confirmatory study; S1 is the supplemental "
            "same-known-entry study. They are reported separately, not pooled, "
            "and S1 is not an independent confirmation."
        ),
        "studies": {},
        "notes": [
            "All model-output failures remain in the denominator and score zero.",
            "Three repeats are averaged within each entry before inference (n=80, not 240).",
            "S1 does not establish an Agent advantage over RAG in file recall.",
            "S0 LR@5 uses the historical parser, which already truncates candidates to five.",
        ],
    }
    for study in ("s0", "s1"):
        value = output[study]
        payload["studies"][study] = {
            "study": study,
            "entries": value["entries"],
            "units": value["units"],
            "arms": {
                arm: {
                    "file_recall5": value["arms"][arm]["file_recall5"],
                    "line_recall5": value["arms"][arm]["line_recall5"],
                    "failures": value["arms"][arm]["failures"],
                    "units": value["arms"][arm]["units"],
                }
                for arm in ARMS
            },
            "provenance": value["provenance"],
        }
    (dest / "main_results.json").write_text(json.dumps(payload, indent=2) + "\n")


def run(root, studies=("s0", "s1"), output_dir=None):
    root = Path(root).resolve()
    if np.__version__ != "2.5.3":
        raise ValueError("Historical S1 RNG reproduction requires numpy==2.5.3")
    requested = tuple(studies)
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("Studies must be a non-empty unique sequence")
    if set(requested) - {"s0", "s1"}:
        raise ValueError("Unknown study; expected s0 and/or s1")
    verify(root)
    output = {study: compute(root, study) for study in requested}
    # Generated outputs never overwrite inputs or historical paper files.
    dest = Path(output_dir).resolve() if output_dir is not None else root / "results"
    dest.mkdir(parents=True, exist_ok=True)
    for study, value in output.items():
        value["provenance"] = {
            "scope": PROVENANCE_SCOPE,
            "inputs_sha256": input_manifest(root, study),
            "environment": environment(),
        }
        assert_finite_tree(value, study + " statistics")
        (dest / f"{study}_statistics.json").write_text(json.dumps(value, indent=2) + "\n")
        rows = _study_rows(study, value)
        _write_rows_csv(dest / f"main_results_{study}.csv", rows)
        _write_rows_markdown(
            dest / f"main_results_{study}.md", rows,
            f"# Recomputed main results — {study.upper()}",
        )
    # The shared table is rebuilt only when both studies were actually recomputed.
    if set(requested) == {"s0", "s1"}:
        _write_combined(dest, output)
    return output
