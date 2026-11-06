"""Explicit preparation, dry-run and live execution with append-only call journal."""

from __future__ import annotations
import argparse, csv, datetime, fcntl, json, math, os, random, sys, time
from pathlib import Path
from core import (
    ROOT,
    SYSTEM,
    TOOLS,
    IntegrityError,
    TransportError,
    SpendingPause,
    Ledger,
    canonical,
    digest_file,
    fingerprint,
    load_rows,
    public_task,
    read_config,
    tokens,
)
from source import Universe, repo_for, validate_commit
from methods import Session, run
import index
from transport import PiRpcLLM
from billing import inspect_journal


def append(path, obj):
    with Path(path).open("a") as f:
        f.write(canonical(obj) + "\n")
        f.flush()
        os.fsync(f.fileno())


def code_hashes():
    paths = (
        list(Path(__file__).parent.glob("*.py"))
        + list(Path(__file__).parent.glob("*.ts"))
        + [
            ROOT / "06_experiments/c06_repair" / n
            for n in (
                "source_policy.json",
                "embedding_compatibility.json",
                "legacy_origin.json",
                "repair_origin.json",
                "development.json",
                "formal_proposal.json",
                "development_multirepo.json",
                "development_multirepo.csv",
            )
        ]
    )
    return {str(p.relative_to(ROOT)): digest_file(p) for p in sorted(paths)}


def identity(cfg):
    return {
        "config": cfg,
        "code": code_hashes(),
        "manifest_sha256": digest_file(ROOT / cfg["sample_manifest"]),
    }


def verify_resume_artifacts(out, cfg, expected, contract, preflight):
    try:
        if json.loads((out / "config.json").read_text()) != cfg:
            raise IntegrityError("Resume config snapshot changed")
        for name, value in expected["code"].items():
            if digest_file(out / "implementation" / name) != value:
                raise IntegrityError("Resume implementation snapshot changed")
        if digest_file(out / "sample_manifest.csv") != expected["manifest_sha256"]:
            raise IntegrityError("Resume sample snapshot changed")
        if (
            contract is not None
            and json.loads((out / "launch_contract.json").read_text()) != contract
        ):
            raise IntegrityError("Resume launch snapshot changed")
        if preflight is not None and digest_file(
            out / "preflight_report.json"
        ) != digest_file(preflight):
            raise IntegrityError("Resume preflight snapshot changed")
    except (OSError, ValueError) as error:
        raise IntegrityError("Missing or unreadable resume snapshot") from error


def schedule(rows, cfg):
    rng = random.Random(cfg["seed"])
    out = []
    for rep in range(1, cfg["repeats"] + 1):
        entries = list(rows)
        rng.shuffle(entries)
        for row in entries:
            arms = list(cfg["arms"])
            rng.shuffle(arms)
            out.extend(
                {"entry_id": row["entry_id"], "arm": a, "repeat": rep} for a in arms
            )
    return out


class Spending:
    def __init__(self, out, cfg, mock):
        self.path = out / "call_journal.jsonl"
        self.pause = cfg["spending_pause_usd"]
        self.mock = mock
        journal = inspect_journal(self.path, allow_missing=True)
        self.total = journal["known_cost_usd"]
        if journal["pending"]:
            raise IntegrityError(
                "Unresolved provider calls; reconcile billing before resume"
            )
        self.number = 0
        self.pending_id = None
        self.unit = None

    def before(self):
        if self.total >= self.pause:
            raise SpendingPause("Cumulative reported cost reached pause guard")
        self.number += 1
        self.pending_id = f"{time.time_ns()}-{self.number}"
        append(
            self.path,
            {
                "id": self.pending_id,
                "state": "started",
                "unit": self.unit,
                "timestamp": time.time(),
            },
        )

    def after(self, response):
        cost = response.get("cost")
        if not self.mock and not response.get("cost_available", False):
            raise IntegrityError("Provider cost absent; call remains unresolved")
        if (
            not isinstance(cost, (int, float))
            or isinstance(cost, bool)
            or not math.isfinite(cost)
            or cost < 0
        ):
            raise IntegrityError("Invalid reported provider cost")
        append(
            self.path,
            {
                "id": self.pending_id,
                "state": "finished",
                "unit": self.unit,
                "cost_usd": cost,
                "timestamp": time.time(),
            },
        )
        self.pending_id = None
        self.total += cost


class MockEmbedder:
    def embed(self, texts):
        import numpy as np

        v = np.zeros((len(texts), 384), dtype="float32")
        v[:, 0] = 1
        return v


class MockLLM:
    def prompt(self, text):
        return {
            "text": '{"candidate_files":[]}',
            "input": tokens(text),
            "cacheRead": 0,
            "output": 7,
            "reasoning": 0,
            "cost": 0.0,
            "cost_available": True,
            "saw_message_end": True,
        }

    def close(self):
        pass


def prepare_all(cfg, out, mock=False, inventory=False):
    rows = load_rows(cfg)
    out.mkdir(parents=True, exist_ok=True)
    summary = []
    seen = {}
    for row in rows:
        key = (row["repo_url"], row["commit"])
        u = Universe.scan(
            repo_for(row),
            {"repo_url": row["repo_url"], "commit": row["commit"]},
            verify_git=True,
        )
        if key in seen:
            if seen[key] != u.fingerprint:
                raise IntegrityError(
                    "Alias snapshots differ for same repository commit"
                )
            continue
        (out / (u.fingerprint + ".json")).write_text(canonical(u.manifest))
        if not inventory:
            meta = index.prepare(u, cfg, mock=mock)
            index.load(
                u, cfg, mock
            )  # Real content/coordinate completeness, not a metadata PASS.
        else:
            meta = {
                "chunks": sum(
                    1
                    for _ in __import__("source").chunks(
                        u, cfg["chunk_lines"], cfg["chunk_overlap"]
                    )
                )
            }
        item = {
            "project": row["project"],
            "commit": row["commit"],
            "source_files": len(u.files),
            "universe": u.fingerprint,
            "chunks": meta["chunks"],
            "cache_hits": meta.get("cache_hits"),
            "cache_misses": meta.get("cache_misses"),
        }
        summary.append(item)
        seen[key] = u.fingerprint
        (out / "progress.json").write_text(
            canonical(
                {"completed": summary, "mode": "inventory" if inventory else "prepared"}
            )
        )
        print(canonical(item), flush=True)
    (out / "summary.json").write_text(
        canonical(
            {
                "config": cfg,
                "code": code_hashes(),
                "repos": summary,
                "mock": mock,
                "inventory_only": inventory,
            }
        )
    )


def freeze(cfg, out, mock=False):
    rows = load_rows(cfg)
    checked = {}
    for row in rows:
        key = row["repo_url"] + "@" + row["commit"]
        u = Universe.scan(
            repo_for(row),
            {"repo_url": row["repo_url"], "commit": row["commit"]},
            verify_git=True,
        )
        if key in checked:
            if checked[key]["universe"] != u.fingerprint:
                raise IntegrityError("Alias snapshots differ")
            continue
        validate_commit(u, row["commit"])
        _, _, meta = index.load(u, cfg, mock)
        checked[key] = {
            "universe": u.fingerprint,
            "index_meta_sha256": digest_file(
                index.directory(u, cfg, mock) / "meta.json"
            ),
        }
    out.mkdir(parents=True, exist_ok=True)
    contract = {
        "identity": identity(cfg),
        "mock": mock,
        "repos": checked,
        "schedule": schedule(rows, cfg),
        "science": "Supplemental study of known original samples; original primary Agent-Pack FR retained. No result is guaranteed.",
    }
    dest = out / (fingerprint(contract) + ".json")
    if not dest.exists():
        dest.write_text(canonical(contract))
    print("Frozen launch contract: " + str(dest.relative_to(ROOT)), flush=True)
    return dest


def verify_run_history(out, done):
    paths = [
        out / n for n in ("records.jsonl", "unit_journal.jsonl", "call_journal.jsonl")
    ]
    if any(not p.exists() for p in paths):
        raise IntegrityError("Resume history incomplete; no automatic paid rerun")
    billing = inspect_journal(paths[2])
    if billing["pending"]:
        raise IntegrityError(
            "Unresolved provider calls; reconcile billing before resume"
        )
    states = {}
    for line in paths[1].read_text().splitlines():
        event = json.loads(line)
        key = tuple(event["unit"])
        previous = states.get(key)
        if event["state"] == "started" and previous is None:
            states[key] = "started"
        elif event["state"] == "recorded" and previous == "started":
            states[key] = "recorded"
        else:
            raise IntegrityError("Duplicate or invalid unit history")
    if set(states) != done or any(v != "recorded" for v in states.values()):
        raise IntegrityError("Unit history and completed records differ")
    paid_units = set()
    for line in paths[2].read_text().splitlines():
        event = json.loads(line)
        if event["state"] == "started":
            unit = event.get("unit") or {}
            paid_units.add((unit.get("entry_id"), unit.get("arm"), unit.get("repeat")))
    if paid_units != done:
        raise IntegrityError("Billed unit history and completed records differ")
    records = [json.loads(s) for s in paths[0].read_text().splitlines()]
    if not math.isclose(
        billing["known_cost_usd"],
        sum(r["reported_cost_usd"] for r in records),
        abs_tol=1e-9,
    ):
        raise IntegrityError("Resume billing and records do not reconcile")


def execute(cfg, out, mock=False, launch=None, preflight=None):
    if not out.is_dir():
        raise ValueError("Use the research harness to supply RESULTS_DIR")
    contract = None
    if cfg["stage"] == "formal":
        if launch is None:
            raise ValueError("Formal stage requires explicit frozen launch contract")
        contract = json.loads(Path(launch).read_text())
        if contract["identity"] != identity(cfg) or contract["mock"] != mock:
            raise IntegrityError("Frozen launch contract differs")
        if not mock:
            if preflight is None:
                raise IntegrityError(
                    "Formal paid run requires a completed preflight report"
                )
            from preflight import validate

            validate(json.loads(Path(preflight).read_text()), cfg, launch)
    resumed = (out / "identity.json").exists()
    if not resumed and any(p.name != ".writer.lock" for p in out.iterdir()):
        raise IntegrityError(
            "Existing run artifacts without identity; refusing fresh initialization"
        )
    context = out / "run_context.json"
    if context.exists():
        run_id = json.loads(context.read_text())["run_id"]
    else:
        run_id = os.environ.get("RUN_ID")
        if not run_id:
            raise ValueError("A harness run_id is required")
        context.write_text(canonical({"run_id": run_id}))
    expected = identity(cfg)
    fp = out / "identity.json"
    if resumed:
        if json.loads(fp.read_text()) != expected:
            raise IntegrityError("Resume config/code/source identity changed")
        verify_resume_artifacts(out, cfg, expected, contract, preflight)
    else:
        fp.write_text(canonical(expected))
        archive = out / "implementation"
        archive.mkdir()
        for name in expected["code"]:
            target = archive / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        (out / "sample_manifest.csv").write_bytes(
            (ROOT / cfg["sample_manifest"]).read_bytes()
        )
        if contract is not None:
            (out / "launch_contract.json").write_text(canonical(contract))
        if preflight is not None:
            (out / "preflight_report.json").write_bytes(Path(preflight).read_bytes())
    (
        (out / "config.json").write_text(canonical(cfg))
        if not (out / "config.json").exists()
        else None
    )
    rows = load_rows(cfg)
    by = {r["entry_id"]: r for r in rows}
    sched = schedule(rows, cfg)
    sp = out / "schedule.json"
    if sp.exists() and json.loads(sp.read_text()) != sched:
        raise IntegrityError("Schedule changed")
    if not sp.exists():
        sp.write_text(canonical(sched))
    records = out / "records.jsonl"
    done = set()
    if records.exists():
        for line in records.read_text().splitlines():
            r = json.loads(line)
            key = (r["entry_id"], r["arm"], r["repeat"])
            if key in done:
                raise IntegrityError("Duplicate recorded unit")
            if r.get("failure_category") in (
                "infrastructure_error",
                "transport_error",
                "spending_pause",
            ):
                raise IntegrityError(
                    "Previous failed paid unit; do not silently rerun or omit"
                )
            done.add(key)
    allowed = {(s["entry_id"], s["arm"], s["repeat"]) for s in sched}
    if done - allowed:
        raise IntegrityError("Unexpected recorded unit")
    unit_journal = out / "unit_journal.jsonl"
    if unit_journal.exists():
        started_units = set()
        for line in unit_journal.read_text().splitlines():
            event = json.loads(line)
            started_units.add(tuple(event["unit"]))
        if started_units - done:
            raise IntegrityError(
                "Interrupted unit may already be billed; no automatic rerun"
            )
    if resumed:
        verify_run_history(out, done)
    spending = Spending(out, cfg, mock)
    embedding = MockEmbedder() if mock else None
    universes = {}
    for unit in sched:
        key = (unit["entry_id"], unit["arm"], unit["repeat"])
        if key in done:
            continue
        row = by[unit["entry_id"]]
        uid = (row["repo_url"], row["commit"])
        if uid not in universes:
            u = Universe.scan(
                repo_for(row),
                {"repo_url": row["repo_url"], "commit": row["commit"]},
                verify_git=True,
            )
            validate_commit(u, row["commit"])
            _, _, indexmeta = index.load(
                u, cfg, mock
            )  # Same corpus verified before first paid call.
            if contract is not None:
                expectation = contract["repos"][row["repo_url"] + "@" + row["commit"]]
                if expectation != {
                    "universe": u.fingerprint,
                    "index_meta_sha256": digest_file(
                        index.directory(u, cfg, mock) / "meta.json"
                    ),
                }:
                    raise IntegrityError("Source/index differs from frozen launch")
            (out / (u.fingerprint + ".index.json")).write_text(canonical(indexmeta))
            universes[uid] = u
            (out / (u.fingerprint + ".universe.json")).write_text(canonical(u.manifest))
        u = universes[uid]
        u.verify()
        validate_commit(u, row["commit"])
        if unit["arm"] == "rag" and embedding is None:
            embedding = index.Embedder()
        append(
            unit_journal,
            {"unit": list(key), "state": "started", "timestamp": time.time()},
        )
        spending.unit = unit
        started = time.monotonic()
        llm = None
        bridge = None
        session = None
        result = {}
        fatal = None
        ev = out / f"{unit['entry_id']}__{unit['arm']}__{unit['repeat']}.events.jsonl"
        try:
            with ev.open("x") as event_log:
                if unit["arm"] == "agent" and not mock:
                    from native_bridge import NativeBridge

                    bridge = NativeBridge(
                        u, cfg, spending, out / (ev.stem + ".native.jsonl")
                    )
                    bridge.extension_path = (
                        out
                        / "implementation/06_experiments/scripts/c06_repair/native_tools.ts"
                    )
                llm = (
                    MockLLM()
                    if mock
                    else PiRpcLLM(
                        SYSTEM
                        + (
                            " Use the registered repository tools to inspect source as needed. Return the final answer JSON when finished."
                            if bridge
                            else ""
                        ),
                        provider=cfg["provider"],
                        model=cfg["model"],
                        thinking=cfg["thinking"],
                        event_log=event_log,
                        turn_timeout=cfg["turn_timeout"],
                        pi_bin=cfg["pi_bin"],
                        native_bridge=bridge,
                    )
                )
                session = Session(llm, spending)
                result = run(
                    unit["arm"], public_task(row), u, cfg, session, embedding, mock
                )
        except SpendingPause as ex:
            fatal = ex
            result = {
                "answer": None,
                "failure_category": "spending_pause",
                "error": str(ex),
            }
        except TransportError as ex:
            fatal = ex
            result = {
                "answer": None,
                "failure_category": "transport_error",
                "error": str(ex),
            }
        except Exception as ex:
            fatal = ex
            result = {
                "answer": None,
                "failure_category": "infrastructure_error",
                "error": str(ex),
            }
        finally:
            if llm is not None:
                llm.close()
                if hasattr(llm, "stderr_path") and Path(llm.stderr_path).exists():
                    (out / (ev.stem + ".stderr.log")).write_bytes(
                        Path(llm.stderr_path).read_bytes()
                    )
            if bridge is not None:
                bridge.close()
        if session is not None and "blocks" not in result:
            result.update(
                {
                    "blocks": getattr(
                        session, "ledger", Ledger(cfg["budget_a"])
                    ).blocks,
                    "A": getattr(session, "ledger", Ledger(cfg["budget_a"])).used,
                }
            )
        calls = session.calls if session else []
        result.update(
            {
                **unit,
                "mock": mock,
                "run_id": run_id,
                "provider": cfg["provider"],
                "model": cfg["model"],
                "thinking": cfg["thinking"],
                "universe": u.fingerprint,
                "calls": calls,
                "wall_seconds": time.monotonic() - started,
                "reported_cost_usd": sum(c["response"]["cost"] for c in calls),
                "B": sum(
                    c["response"]["input"] + c["response"].get("cacheRead", 0)
                    for c in calls
                ),
                "output_tokens": sum(c["response"]["output"] for c in calls),
            }
        )
        append(records, result)
        done.add(key)
        append(
            unit_journal,
            {"unit": list(key), "state": "recorded", "timestamp": time.time()},
        )
        print(
            canonical(
                {
                    "unit": unit,
                    "failure": result["failure_category"],
                    "reported_cost_usd": result["reported_cost_usd"],
                    "cumulative_reported_cost_usd": spending.total,
                    "completed": len(done),
                    "planned": len(sched),
                }
            ),
            flush=True,
        )
        if fatal:
            (out / "execution_summary.json").write_text(
                canonical(
                    {
                        "status": "stopped",
                        "reason": str(fatal),
                        "cost_usd": spending.total,
                        "completed": len(done),
                    }
                )
            )
            raise fatal
    (out / "execution_summary.json").write_text(
        canonical(
            {
                "status": "complete",
                "stage": cfg["stage"],
                "mock": mock,
                "cost_usd": spending.total,
                "completed": len(done),
            }
        )
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument(
        "--mode", choices=["prepare", "inventory", "freeze", "run"], required=True
    )
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--resume-dir")
    ap.add_argument("--output")
    ap.add_argument("--launch")
    ap.add_argument("--preflight")
    args = ap.parse_args()
    cfg = read_config(ROOT / args.config)
    if args.mode == "freeze":
        if not args.output:
            raise ValueError("Freeze output directory required")
        freeze(cfg, ROOT / args.output, args.mock)
        return
    if args.mode in ("prepare", "inventory"):
        if not args.output:
            raise ValueError("Explicit output directory required")
        prepare_all(cfg, ROOT / args.output, args.mock, args.mode == "inventory")
        return
    out = Path(args.resume_dir or os.environ["RESULTS_DIR"])
    if (
        args.resume_dir
        and os.environ.get("RESULTS_DIR")
        and Path(os.environ["RESULTS_DIR"]) != out
    ):
        (Path(os.environ["RESULTS_DIR"]) / "resume_parent.json").write_text(
            canonical({"parent_directory": str(out), "mode": "resume-existing-run"})
        )
    out.mkdir(parents=True, exist_ok=True)
    # Single writer lock also prevents duplicate paid launches into one run.
    with (out / ".writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        execute(
            cfg,
            out,
            args.mock,
            ROOT / args.launch if args.launch else None,
            ROOT / args.preflight if args.preflight else None,
        )


if __name__ == "__main__":
    main()
