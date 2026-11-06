"""Arm-blind scoring, completeness gate and explicitly descriptive development summaries."""

import argparse, csv, json, math
from fractions import Fraction
from pathlib import Path
import numpy as np
from core import ROOT, IntegrityError, canonical, digest_file


def interval(value):
    try:
        parts = str(value).split("-")
        lo = int(parts[0])
        hi = int(parts[-1])
        return (lo, hi) if 1 <= lo <= hi else None
    except ValueError:
        return None


def scores(row, answer, width=None):
    candidates = (answer or {}).get("candidate_files", [])[:5]
    targets = {p for p in (row["ep_file"], row["co_file"]) if p}
    fr = (
        Fraction(len(targets & {c["path"] for c in candidates}), len(targets))
        if targets
        else Fraction(0)
    )
    hits = 0
    for file, line in (
        (row["ep_file"], row["ep_line"]),
        (row["co_file"], row["co_line"]),
    ):
        truth = interval(line)
        if not truth:
            continue
        for c in candidates:
            start, end = c.get("line_start"), c.get("line_end")
            if type(start) is not int or type(end) is not int or not 1 <= start <= end:
                continue
            if width is not None and end - start + 1 > width:
                continue
            if c["path"] == file and start - 5 <= truth[1] and end + 5 >= truth[0]:
                hits += 1
                break
    return fr, Fraction(hits, 2)


def bh(ps):
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    q = [1.0] * len(ps)
    last = 1.0
    for rank in range(len(ps), 0, -1):
        i = order[rank - 1]
        last = min(last, ps[i] * len(ps) / rank)
        q[i] = last
    return q


def paired(a, b, seed=20261003, draws=100000):
    d = [x - y for x, y in zip(a, b)]
    rng = np.random.default_rng(seed)
    if not d:
        raise ValueError("No pairs")
    scale = math.lcm(*(x.denominator for x in d))
    ints = np.asarray([int(x * scale) for x in d], dtype=np.int64)
    observed = abs(ints.sum())
    exceed = 0
    for offset in range(0, draws, 2048):
        n = min(2048, draws - offset)
        signs = rng.integers(0, 2, (n, len(d)), dtype=np.int8) * 2 - 1
        exceed += int((np.abs(signs @ ints) >= observed).sum())
    values = np.asarray([float(x) for x in d])
    boot = values[rng.integers(0, len(d), (10000, len(d)))].mean(axis=1)
    return {
        "n_entries": len(d),
        "difference": float(values.mean()),
        "entry_bootstrap_ci95": np.quantile(boot, [0.025, 0.975]).tolist(),
        "mc_sign_flip_p": (exceed + 1) / (draws + 1),
        "mc_draws": draws,
        "exceedances": exceed,
        "note": "Entry resampling assumes independent entries; repository dependence remains a limitation.",
    }


def main():
    ap = argparse.ArgumentParser()
    for name in (
        "run-id",
        "metadata",
        "raw-dir",
        "processed-dir",
        "tables-dir",
        "figures-dir",
    ):
        ap.add_argument("--" + name, required=True)
    args = ap.parse_args()
    import yaml

    metadata = yaml.safe_load((ROOT / args.metadata).read_text())
    if metadata["run_id"] != args.run_id or metadata["status"] != "success":
        raise IntegrityError("Run metadata not successful/bound")
    raw = ROOT / args.raw_dir
    cfg = json.loads((raw / "config.json").read_text())
    ident = json.loads((raw / "identity.json").read_text())
    from runner import code_hashes

    if ident["code"] != code_hashes():
        raise IntegrityError("Current analysis/engine differs from run version")
    if cfg != ident["config"]:
        raise IntegrityError("Config differs from frozen run identity")
    for name, h in ident["code"].items():
        if digest_file(raw / "implementation" / name) != h:
            raise IntegrityError("Archived implementation hash differs")
    if digest_file(ROOT / cfg["sample_manifest"]) != ident["manifest_sha256"]:
        raise IntegrityError("Scoring manifest changed")
    snapshot = raw / "sample_manifest.csv"
    if snapshot.exists() and digest_file(snapshot) != ident["manifest_sha256"]:
        raise IntegrityError("Manifest snapshot mismatch")
    rows = {
        r["entry_id"]: r
        for r in csv.DictReader(
            (snapshot if snapshot.exists() else ROOT / cfg["sample_manifest"]).open()
        )
    }
    sched = json.loads((raw / "schedule.json").read_text())
    planned = {(r["entry_id"], r["arm"], r["repeat"]) for r in sched}
    records = [json.loads(s) for s in (raw / "records.jsonl").read_text().splitlines()]
    keys = [(r["entry_id"], r["arm"], r["repeat"]) for r in records]
    if len(keys) != len(set(keys)) or set(keys) != planned:
        raise IntegrityError("Incomplete/duplicate schedule")
    if any(
        r["failure_category"]
        in ("infrastructure_error", "transport_error", "spending_pause")
        for r in records
    ):
        raise IntegrityError("Infrastructure failure is not an accuracy outcome")
    for record in records:
        if record["run_id"] != args.run_id:
            raise IntegrityError("Record run_id mismatch")
        if any(record[k] != cfg[k] for k in ("provider", "model", "thinking")):
            raise IntegrityError("Record model identity differs")
        if (
            sum(b["tokens"] for b in record["blocks"]) != record["A"]
            or not 0 <= record["A"] <= cfg["budget_a"]
        ):
            raise IntegrityError("Repository accounting differs")
        for block in record["blocks"]:
            from core import digest_bytes, tokens

            if (
                digest_bytes(block["text"].encode()) != block["sha256"]
                or tokens(block["text"]) != block["tokens"]
            ):
                raise IntegrityError("Block text/accounting differs")
    if len({r["mock"] for r in records}) != 1:
        raise IntegrityError("Mixed mock/real")
    if cfg["stage"] == "formal" and not records[0]["mock"]:
        from preflight import validate
        from billing import inspect_journal

        report = json.loads((raw / "preflight_report.json").read_text())
        validate(report, cfg, raw / "launch_contract.json")
        contract = json.loads((raw / "launch_contract.json").read_text())
        for record in records:
            row = rows[record["entry_id"]]
            if (
                record["universe"]
                != contract["repos"][row["repo_url"] + "@" + row["commit"]]["universe"]
            ):
                raise IntegrityError(
                    "Record source universe differs from frozen contract"
                )
        billing = inspect_journal(raw / "call_journal.jsonl")
        if billing["pending"] or not math.isclose(
            billing["known_cost_usd"],
            sum(r["reported_cost_usd"] for r in records),
            abs_tol=1e-9,
        ):
            raise IntegrityError("Unresolved or inconsistent billing at analysis")
    per = []
    cells = {}
    for r in records:
        row = rows[r["entry_id"]]
        fr, lr = scores(row, r["answer"])
        key = (r["entry_id"], r["arm"])
        cells.setdefault(key, []).append((fr, lr))
        spans = [s for b in r["blocks"] for s in b["spans"]]
        target = {row["ep_file"], row["co_file"]}
        per.append(
            {
                k: r[k]
                for k in (
                    "entry_id",
                    "arm",
                    "repeat",
                    "failure_category",
                    "A",
                    "B",
                    "reported_cost_usd",
                    "wall_seconds",
                )
            }
            | {
                "file_recall5": float(fr),
                "line_recall5": float(lr),
                "delivered_target_files": len(target & {s["path"] for s in spans}),
                "lr_width64": float(scores(row, r["answer"], 64)[1]),
            }
        )
    means = {
        k: (sum(v[0] for v in vs) / len(vs), sum(v[1] for v in vs) / len(vs))
        for k, vs in cells.items()
    }
    entries = sorted({e for e, a in means})
    result = {
        "stage": cfg["stage"],
        "mock": records[0]["mock"],
        "evidence": "NOT_RESEARCH_DATA" if records[0]["mock"] else "DEVELOPMENT_ONLY",
        "units": len(records),
        "entries": len(entries),
        "arms": {},
        "reported_cost_usd": sum(r["reported_cost_usd"] for r in records),
        "statement": "Development validation is not a confirmatory result. No hypothesis test or publication claim made.",
    }
    if cfg["stage"] == "formal":
        contract = json.loads((raw / "launch_contract.json").read_text())
        if (
            contract["identity"] != ident
            or contract["schedule"] != sched
            or contract["mock"] != records[0]["mock"]
        ):
            raise IntegrityError("Analysis contract differs")
        result["evidence"] = (
            "NOT_RESEARCH_DATA"
            if records[0]["mock"]
            else "SUPPLEMENTAL_KNOWN_SAMPLE_STUDY"
        )
        result["statement"] = (
            "Supplemental comparison, known original samples; entry inference and repository sensitivity separately reported."
        )
        result["comparisons"] = {}
        family = [
            ("agent", "rag", 0),
            ("rag", "pack", 0),
            ("agent", "rag", 1),
            ("rag", "pack", 1),
        ]
        if set(cfg["arms"]) != set(("agent", "rag", "pack")):
            raise IntegrityError("Formal plan requires original three arms")
        primary = paired(
            [means[e, "agent"][0] for e in entries],
            [means[e, "pack"][0] for e in entries],
            seed=20260928,
        )
        result["primary_agent_pack_fr"] = primary
        pvalues = []
        for first, second, metric in family:
            name = f"{first}-{second}-" + ("fr" if metric == 0 else "lr")
            value = paired(
                [means[e, first][metric] for e in entries],
                [means[e, second][metric] for e in entries],
                seed=20260928,
            )
            result["comparisons"][name] = value
            pvalues.append(value["mc_sign_flip_p"])
        for name, q in zip(result["comparisons"], bh(pvalues)):
            result["comparisons"][name]["bh_q_unrounded"] = q
        # Repository sensitivity is explicit; it is not labeled CR2 or a cure for only 13 clusters.
        clusters = {e: rows[e]["repo_url"] for e in entries}
        d = {e: float(means[e, "agent"][0] - means[e, "pack"][0]) for e in entries}
        repositories = sorted(set(clusters.values()))
        byrepo = {g: [d[e] for e in entries if clusters[e] == g] for g in repositories}
        result["repo_effects"] = {
            g: {"n_entries": len(ds), "mean": float(np.mean(ds))}
            for g, ds in byrepo.items()
        }
        result["loco_primary"] = {
            g: float(np.mean([d[e] for e in entries if clusters[e] != g]))
            for g in repositories
            if len(byrepo[g]) < len(entries)
        }
        result["repo_equal_weight_mean"] = float(
            np.mean([np.mean(ds) for ds in byrepo.values()])
        )
        rng = np.random.default_rng(20260928)
        labels = np.asarray(repositories)
        cluster_draws = []
        for _ in range(10000):
            chosen = rng.choice(labels, len(labels), replace=True)
            values = [v for g in chosen for v in byrepo[g]]
            cluster_draws.append(float(np.mean(values)))
        result["repo_resampling_ci95_sensitivity"] = np.quantile(
            cluster_draws, [0.025, 0.975]
        ).tolist()
        result["cluster_limit"] = (
            "Few imbalanced clusters; repository bootstrap is supplementary, CR2 is not implemented. Entry tests do not establish cross-repository generalization."
        )
    for arm in cfg["arms"]:
        armrs = [r for r in per if r["arm"] == arm]
        result["arms"][arm] = {
            "fr_mean": sum(float(means[e, arm][0]) for e in entries) / len(entries),
            "lr_mean": sum(float(means[e, arm][1]) for e in entries) / len(entries),
            "failure_count": sum(r["failure_category"] is not None for r in armrs),
        }
    proc = ROOT / args.processed_dir
    tabs = ROOT / args.tables_dir
    proc.mkdir(parents=True, exist_ok=True)
    tabs.mkdir(parents=True, exist_ok=True)
    (proc / "summary.json").write_text(canonical(result))
    (proc / "per_record.json").write_text(canonical(per))
    (tabs / "summary.md").write_text(
        "# Development pipeline validation\n\n"
        + result["evidence"]
        + "\n\n```json\n"
        + json.dumps(result, indent=2)
        + "\n```\n"
    )
    print(canonical(result))


if __name__ == "__main__":
    main()
