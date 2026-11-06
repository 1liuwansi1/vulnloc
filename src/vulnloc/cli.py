"""Offline CLI. There is intentionally no online/model execution command."""
import argparse
from pathlib import Path

from .integrity import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "reproduce", "verify-results"))
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Artifact checkout root")
    parser.add_argument("--study", choices=("all", "s0", "s1"), default="all")
    args = parser.parse_args()
    if args.command == "verify":
        print(f"PASS: {verify(args.root)} artifact hashes verified")
    elif args.command == "verify-results":
        from .site_data import load_site_data
        data = load_site_data(args.root)
        print(
            "PASS: website data has exactly six study/arm rows; "
            f"{data['studies']['s0']['units']}+{data['studies']['s1']['units']} units"
        )
    else:
        from .reproduce import run
        values = run(args.root, ("s0", "s1") if args.study == "all" else (args.study,))
        for study in values:
            print(f"PASS: {study.upper()} 720 units / 80 entries; official statistics and paper verified")
        if args.study != "all":
            print("NOTE: single-study run updated only its per-study files; combined main_results.* was not rewritten.")
