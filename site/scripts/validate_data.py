"""Read-only research checks, followed by an allowlisted website data export."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from vulnloc.reproduce import (  # noqa: E402
    PROVENANCE_SCOPE, compute, environment, input_manifest,
)
from vulnloc.site_data import ARMS, STUDIES, load_site_data  # noqa: E402

COLUMNS = ["study", "arm", "file_recall5", "line_recall5", "failures", "units"]


def safe_file(root, relative):
    """Reject symlinks and private/escaping input references before opening."""
    relative = Path(str(relative).replace("\\", "/"))
    if relative.is_absolute() or re.match(r"^[A-Za-z]:", str(relative)) or any(p in ("..", ".local", ".venv", "raw", "repos", "index_cache", "embedding_cache") for p in relative.parts):
        raise ValueError("Unsafe input reference")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Symlink input is not allowed")
    if not path.is_file():
        raise ValueError("Required input missing")
    return path


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Non-finite JSON value")

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                       parse_constant=invalid)
    def finite_tree(item):
        if isinstance(item, dict):
            for child in item.values():
                finite_tree(child)
        elif isinstance(item, list):
            for child in item:
                finite_tree(child)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Non-finite JSON value")
    finite_tree(value)
    return value


def compare(actual, expected, label="value"):
    """Strict structure/types, finite numbers, and only roundoff tolerance."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise ValueError(f"Object mismatch: {label}")
        for key in expected:
            compare(actual[key], expected[key], f"{label}.{key}")
    elif isinstance(expected, (list, tuple)):
        if not isinstance(actual, (list, tuple)) or len(actual) != len(expected):
            raise ValueError(f"Array mismatch: {label}")
        for a, b in zip(actual, expected):
            compare(a, b, label)
    elif type(expected) in (int, float):
        if type(actual) not in (int, float) or not math.isfinite(actual) or not math.isfinite(expected):
            raise ValueError(f"Invalid number: {label}")
        if type(expected) is int and type(actual) is not int:
            raise ValueError(f"Expected integer: {label}")
        if not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12):
            raise ValueError(f"Numeric mismatch: {label}")
    elif type(actual) is not type(expected) or actual != expected:
        raise ValueError(f"Value mismatch: {label}")


def validate_csv(path, studies):
    expected = {(s, a): studies[s]["arms"][a] for s in studies for a in ARMS}
    seen = set()
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, strict=True)
        if reader.fieldnames != COLUMNS:
            raise ValueError("CSV header mismatch")
        for row in reader:
            if set(row) != set(COLUMNS) or any(v is None for v in row.values()):
                raise ValueError("Malformed CSV row")
            key = row["study"], row["arm"]
            if key not in expected or key in seen:
                raise ValueError("Unexpected or duplicate CSV study/arm")
            seen.add(key)
            values = {}
            for name in ("file_recall5", "line_recall5"):
                value = float(row[name])
                if not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("Invalid CSV recall")
                values[name] = value
            for name in ("failures", "units"):
                if not re.fullmatch(r"0|[1-9][0-9]*", row[name]):
                    raise ValueError("Invalid CSV count")
                values[name] = int(row[name])
            compare(values, expected[key], "CSV")
    if seen != set(expected):
        raise ValueError("Missing CSV rows")


def validate_provenance(root, study, provenance):
    if not isinstance(provenance, dict) or set(provenance) != {"scope", "inputs_sha256", "environment"}:
        raise ValueError("Invalid provenance schema")
    # Enumerate the closure independently, then require exact equality with the
    # reproduction API and stored provenance (including absence of extra keys).
    paths = {"data/processed/entries.json", "requirements.txt", "docs/METHODS.md",
             "paper/tables/revision_means.tex", "paper/tables/revision_contrasts.tex",
             "paper/tables/revision_numbers.tex",
             f"experiments/{study}_frozen/code/" + ("confirmatory_stats.py" if study == "s0" else "analysis.py")}
    base = root / "data/processed" / study
    if base.is_symlink():
        raise ValueError("Symlink study directory")
    for path in base.iterdir():
        if path.is_symlink():
            raise ValueError("Symlink study input")
        if path.is_file():
            paths.add(path.relative_to(root).as_posix())
    hashes = {p: hashlib.sha256(safe_file(root, p).read_bytes()).hexdigest() for p in sorted(paths)}
    compare(input_manifest(root, study), hashes, "input closure")
    compare(provenance["inputs_sha256"], hashes, "provenance hashes")
    compare(provenance["scope"], PROVENANCE_SCOPE)
    compare(provenance["environment"], environment(), "provenance environment")


def contrast(value, study, label, metric):
    s0 = study == "s0"
    item = {"label": label, "metric": metric,
            "difference": value["mean" if s0 else "difference"],
            "ci": list(value["bootstrap_ci95" if s0 else "entry_bootstrap_ci95"]),
            "p": value["permutation_p" if s0 else "mc_sign_flip_p"]}
    q = "bh_q" if s0 else "bh_q_unrounded"
    if q in value:
        item["q"] = value[q]
    return item


def validate(root=ROOT):
    root = Path(root).resolve()
    # Check every manifest path before the existing CLI is permitted to hash it.
    manifest = read_json(safe_file(root, "docs/provenance/artifact_checksums.json"))
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("Empty artifact manifest")
    for relative in manifest:
        safe_file(root, relative)
    for relative in ("results/main_results.json", "results/main_results.csv",
                     *(f"results/{s}_statistics.json" for s in STUDIES),
                     *(f"results/main_results_{s}.csv" for s in STUDIES)):
        safe_file(root, relative)
    env = dict(os.environ, PYTHONPATH=str(root / "src"), PYTHONDONTWRITEBYTECODE="1")
    for command in ("verify", "verify-results"):
        subprocess.run([sys.executable, "-c", "from vulnloc.cli import main; main()",
                        command, "--root", str(root)],
                       cwd=root, env=env, check=True)
    payload = read_json(root / "results/main_results.json")
    load_site_data(root)
    if payload.get("schema_version") != "1.0" or set(payload.get("studies", {})) != set(STUDIES):
        raise ValueError("Invalid main results schema")
    output = {"schema_version": "1.0", "studies": {}}
    for study in STUDIES:
        stored = read_json(root / f"results/{study}_statistics.json")
        validate_provenance(root, study, stored.get("provenance"))
        main = payload["studies"][study]
        compare(main.get("provenance"), stored["provenance"], "main provenance")
        fresh = compute(root, study)  # Never call run(): it writes research data.
        compare({k: v for k, v in stored.items() if k != "provenance"}, fresh, study)
        compare(main, {k: fresh[k] for k in ("study", "entries", "units", "arms")} |
                {"provenance": stored["provenance"]}, "main study")
        validate_csv(root / f"results/main_results_{study}.csv", {study: fresh})
        secondary = []
        for metric, a, b in (("fr", "agent", "rag"), ("fr", "rag", "pack"),
                              ("lr", "agent", "rag"), ("lr", "rag", "pack")):
            key = f"{metric}_{a}_vs_{b}" if study == "s0" else f"{a}-{b}-{metric}"
            secondary.append(contrast(fresh["secondary"][key], study,
                                      f"{a.title()} vs {b.upper() if b == 'rag' else b.title()}",
                                      "file_recall5" if metric == "fr" else "line_recall5"))
        output["studies"][study] = {
            "study": study, "entries": fresh["entries"], "units": fresh["units"],
            "units_per_arm": 240, "repeats": 3, "arms": fresh["arms"],
            "primary": contrast(fresh["primary"], study, "Agent vs Pack", "file_recall5"),
            "secondary": secondary, "seed": fresh["seed"],
            "bootstrap_draws": fresh["bootstrap_draws"], "permutation_draws": fresh["permutation_draws"],
        }
    validate_csv(root / "results/main_results.csv", output["studies"])
    return output


def main():
    target = ROOT / "site/src/data/verified.json"
    # Invalidate stale generated data even when a subsequent check fails.
    if any(path.is_symlink() for path in (target, *target.parents)):
        raise ValueError("Symlink output is not allowed")
    if target.exists():
        target.unlink()
    value = validate()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print("PASS: independently verified both studies; sanitized display data exported")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: site data validation ({type(error).__name__})", file=sys.stderr)
        sys.exit(1)
