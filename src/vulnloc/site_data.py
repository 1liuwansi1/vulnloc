"""Validated website data interface for P3; no raw/model access."""
import csv
import math
from pathlib import Path

from .integrity import read_json

ARMS = ("agent", "rag", "pack")
STUDIES = ("s0", "s1")


def _finite(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"Non-finite or non-numeric site value: {label}")
    return float(value)


def load_site_data(root, results_dir=None):
    root = Path(root).resolve()
    dest = Path(results_dir).resolve() if results_dir is not None else root / "results"
    json_path = dest / "main_results.json"
    csv_path = dest / "main_results.csv"
    if not json_path.is_file() or not csv_path.is_file():
        raise ValueError("Website data incomplete: main_results.json/csv missing; run 'vulnloc reproduce' for both studies")
    payload = read_json(json_path)
    if payload.get("schema_version") != "1.0":
        raise ValueError("Unsupported website data schema")
    studies = payload.get("studies")
    if not isinstance(studies, dict) or set(studies) != set(STUDIES):
        raise ValueError("Website data must contain exactly s0 and s1, not pooled")
    expected = {(s, a) for s in STUDIES for a in ARMS}
    rows = {}
    with csv_path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["study", "arm", "file_recall5", "line_recall5", "failures", "units"]:
            raise ValueError("Website CSV schema mismatch")
        for row in reader:
            key = (row["study"], row["arm"])
            if key in rows:
                raise ValueError("Duplicate study/arm row in website CSV")
            rows[key] = row
    if set(rows) != expected or len(rows) != 6:
        raise ValueError("Website CSV must contain exactly six study/arm rows")
    for study in STUDIES:
        value = studies[study]
        if value.get("study") != study or value.get("entries") != 80 or value.get("units") != 720:
            raise ValueError(f"Invalid study metadata: {study}")
        if set(value.get("arms", {})) != set(ARMS):
            raise ValueError(f"Invalid arms: {study}")
        per_study = dest / f"main_results_{study}.csv"
        if not per_study.is_file():
            raise ValueError(f"Per-study table missing: {per_study.name}")
        with per_study.open(newline="") as stream:
            per = list(csv.DictReader(stream))
        if len(per) != 3 or {(r["study"], r["arm"]) for r in per} != {(study, a) for a in ARMS}:
            raise ValueError(f"Per-study table incomplete: {study}")
        for arm in ARMS:
            item = value["arms"][arm]
            row = rows[(study, arm)]
            if type(item.get("units")) is not int or item["units"] != 240:
                raise ValueError(f"Invalid arm unit count: {study}/{arm}")
            if type(item.get("failures")) is not int or not 0 <= item["failures"] <= 240:
                raise ValueError(f"Invalid failure count: {study}/{arm}")
            fr = _finite(item.get("file_recall5"), f"{study}/{arm}/FR")
            lr = _finite(item.get("line_recall5"), f"{study}/{arm}/LR")
            if not 0 <= fr <= 1 or not 0 <= lr <= 1:
                raise ValueError(f"Recall outside [0,1]: {study}/{arm}")
            if abs(fr - float(row["file_recall5"])) > 1e-12 or abs(lr - float(row["line_recall5"])) > 1e-12:
                raise ValueError(f"CSV/JSON mismatch: {study}/{arm}")
            if int(row["failures"]) != item["failures"] or int(row["units"]) != 240:
                raise ValueError(f"CSV/JSON failure/unit mismatch: {study}/{arm}")
        stats = dest / f"{study}_statistics.json"
        if not stats.is_file():
            raise ValueError(f"Study statistics missing: {stats.name}")
        stat = read_json(stats)
        if stat.get("study") != study or stat.get("entries") != 80 or stat.get("units") != 720:
            raise ValueError(f"Study statistics metadata mismatch: {study}")
    return payload
