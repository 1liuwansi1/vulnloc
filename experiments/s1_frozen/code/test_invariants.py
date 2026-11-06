"""Adversarial invariants, not checks for the presence of function names."""

import copy, json, sys, tempfile, unittest
from pathlib import Path
from fractions import Fraction
from unittest.mock import patch
import numpy as np
from core import *
from source import Universe, chunks, validate_commit
import index
from methods import Session, tool, run
from runner import Spending, MockLLM, MockEmbedder, execute, identity, schedule
from analysis import scores, bh, paired

CFG = read_config(ROOT / "06_experiments/c06_repair/development.json")


class Invariants(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        fixtures = {
            "src/ok.py": "alpha = 1\nneedle()\nlast = 3\n",
            "src/empty.py": "",
            "src/blank.py": " \n",
            "dist/no.py": "needle()\n",
            "src/big.py": "x" * 200001,
            "src/binary.py": "\x00needle()",
            "node_modules/no.js": "needle()",
            "README.md": "needle()",
        }
        for path, text in fixtures.items():
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        outside = self.root / "external"
        outside.write_text("nothing")
        (self.root / "src/link.py").symlink_to(outside)
        self.u = Universe.scan(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_actual_universe(self):
        self.assertEqual(
            set(self.u.files), {"src/ok.py", "src/empty.py", "src/blank.py", "external"}
        )
        for bad in (
            "dist/no.py",
            "src/big.py",
            "src/binary.py",
            "src/link.py",
            "../external",
        ):
            with self.assertRaises(PermissionError):
                self.u.read(bad)

    def test_directory_metadata_only_eligible(self):
        self.assertNotIn("dist/", self.u.listing("."))
        self.assertNotIn("link.py", self.u.listing("src"))

    def test_source_drift_fails(self):
        (self.root / "src/ok.py").write_text("changed")
        with self.assertRaises(IntegrityError):
            self.u.read("src/ok.py")
        with self.assertRaises(IntegrityError):
            self.u.verify()

    def test_symlink_swap_fails(self):
        p = self.root / "src/ok.py"
        p.unlink()
        p.symlink_to(self.root / "external")
        with self.assertRaises(IntegrityError):
            self.u.read("src/ok.py")

    def test_code_renderer_true_delivered_spans(self):
        l = Ledger(42)
        text = l.code("src/ok.py", ["一" * 15, "second", "third"], 1, "read")
        self.assertLessEqual(l.used, 42)
        if l.blocks:
            span = l.blocks[0]["spans"][0]
            self.assertTrue(
                all(f"{i}: " in text for i in range(span["start"], span["end"] + 1))
            )

    def test_unicode_and_small_caps(self):
        for cap in range(0, 45):
            l = Ledger(cap)
            l.metadata("中文🔥<|endoftext|>" * 15, "tree")
            self.assertLessEqual(l.used, cap)
            self.assertLessEqual(tokens(clip("中文🔥<|endoftext|>" * 15, cap)), cap)

    def test_zero_cap_does_not_false_label_delivery(self):
        l = Ledger(1)
        self.assertEqual(l.code("src/ok.py", ["needle()"], 1, "rag"), "")
        self.assertFalse(l.blocks)

    def test_identical_renderer_three_methods(self):
        rendered = [
            Ledger(100).code("src/ok.py", self.u.read("src/ok.py"), 1, kind)
            for kind in ("read", "rag", "pack")
        ]
        self.assertEqual(len(set(rendered)), 1)

    def test_grep_never_searches_excluded_paths(self):
        ledger = Ledger(1000)
        text = tool("grep", {"pattern": "needle"}, self.u, ledger, CFG)
        self.assertTrue(ledger.blocks)
        self.assertTrue(
            all(s["path"] == "src/ok.py" for b in ledger.blocks for s in b["spans"])
        )
        self.assertNotIn("dist/", text)

    def test_read_tool_rejects_outside_u(self):
        l = Ledger(1000)
        tool("read_file", {"path": "dist/no.py"}, self.u, l, CFG)
        self.assertTrue(all(not b["spans"] for b in l.blocks))

    def test_full_chunks_no_old_cap(self):
        p = self.root / "src/ok.py"
        p.write_text("\n".join("x=1" for _ in range(40005)))
        u = Universe.scan(self.root)
        cs = list(chunks(u, 1, 0))
        self.assertGreater(len(cs), 40000)
        self.assertEqual(cs[-1]["end"], 40005)

    def test_index_tampered_and_missing_tail(self):
        cfg = {**CFG, "chunk_lines": 2, "chunk_overlap": 1}
        dest = self.root / "idx"
        with patch("index.directory", return_value=dest):
            index.prepare(self.u, cfg, mock=True)
            cs, v, m = index.load(self.u, cfg, True)
            self.assertTrue(cs)
            shortened = cs[:-1]
            (dest / "chunks.json").write_text(canonical(shortened))
            np.save(dest / "emb.npy", np.array(v[:-1], copy=True))
            m["hashes"] = {n: digest_file(dest / n) for n in ("chunks.json", "emb.npy")}
            (dest / "meta.json").write_text(canonical(m))
            with self.assertRaises(IntegrityError):
                index.load(self.u, cfg, True)

    def test_index_corrupt_vector_fails(self):
        dest = self.root / "idx"
        with patch("index.directory", return_value=dest):
            index.prepare(self.u, CFG, mock=True)
            np.savez(dest / "emb.npy", data=np.ones((1, 384)))
            with (dest / "emb.npy").open("wb") as f:
                np.savez(f, data=np.ones((1, 384)))
            with self.assertRaises(IntegrityError):
                index.load(self.u, CFG, True)

    def test_unknown_arm_rejects(self):
        with self.assertRaises(ValueError):
            run("rag_typo", {}, self.u, CFG, None)

    def test_truth_never_in_public_task(self):
        row = {
            k: "PUBLIC"
            for k in (
                "entry_id",
                "report_id",
                "project",
                "repo_url",
                "commit",
                "vuln_title",
                "task_description",
            )
        }
        row.update({"ep_file": "PRIVATE", "co_line": "PRIVATE", "trace": "PRIVATE"})
        self.assertNotIn("PRIVATE", canonical(public_task(row)))

    def test_schema_invalid_ranges_and_bool(self):
        for start, end in ((True, 5), (0, 5), (10, 2)):
            self.assertIsNone(
                parse(
                    canonical(
                        {
                            "candidate_files": [
                                {"path": "a.py", "line_start": start, "line_end": end}
                            ]
                        }
                    )
                )
            )
        self.assertIsNone(parse('{"tool":"grep","args":{},"candidate_files":[]}'))

    def test_spending_unknown_cost_blocks_resume(self):
        spend = Spending(self.root, CFG, False)
        spend.before()
        with self.assertRaises(IntegrityError):
            spend.after({"cost": 0})
        with self.assertRaises(IntegrityError):
            Spending(self.root, CFG, False)

    def test_cumulative_guard_before_next_call(self):
        cfg = {**CFG, "spending_pause_usd": 0.2}
        spend = Spending(self.root, cfg, True)
        spend.before()
        spend.after({"cost": 0.21})
        with self.assertRaises(SpendingPause):
            spend.before()
        self.assertAlmostEqual(Spending(self.root, cfg, True).total, 0.21)

    def test_empty_answer_no_paid_correction(self):
        class Empty(MockLLM):
            def prompt(self, t):
                return {**super().prompt(t), "text": ""}

        spend = Spending(self.root, CFG, True)
        session = Session(Empty(), spend)
        task = {k: "x" for k in ("vuln_title", "task_description")}
        result = run("pack", task, self.u, CFG, session)
        self.assertEqual(result["failure_category"], "empty_answer")
        self.assertEqual(len(session.calls), 1)

    def test_provider_error_is_not_answer(self):
        class Failed(MockLLM):
            def prompt(self, t):
                return {**super().prompt(t), "provider_error": True}

        session = Session(Failed(), Spending(self.root, CFG, True))
        with self.assertRaises(TransportError):
            session.ask("test")

    def test_scoring_width_and_top_five(self):
        row = {
            "ep_file": "a.py",
            "co_file": "a.py",
            "ep_line": "10",
            "co_line": "15-16",
        }
        answer = {
            "candidate_files": [{"path": "a.py", "line_start": 1, "line_end": 1000}]
        }
        self.assertEqual(scores(row, answer), (Fraction(1), Fraction(1)))
        self.assertEqual(scores(row, answer, 64), (Fraction(1), Fraction(0)))

    def test_bh_unrounded_and_integer_signflip(self):
        self.assertEqual(bh([0.01, 0.04, 0.04]), [0.03, 0.04, 0.04])
        result = paired([Fraction(1, 3)] * 4, [Fraction(0)] * 4, draws=10000)
        self.assertGreater(result["mc_sign_flip_p"], 0.10)
        self.assertLess(result["mc_sign_flip_p"], 0.15)

    def test_mutation_authorization_is_caught(self):
        # A broken "allow everything" authorization exposes the deliberate dist counterexample.
        self.u.files["dist/no.py"] = {"sha256": digest_file(self.root / "dist/no.py")}
        self.assertEqual(self.u.read("dist/no.py"), ["needle()"])
        with self.assertRaises(IntegrityError):
            self.u.verify()

    def test_completed_resume_does_not_call_model(self):
        import os

        row = {
            k: "x"
            for k in (
                "entry_id",
                "report_id",
                "project",
                "repo_url",
                "commit",
                "vuln_title",
                "task_description",
            )
        }
        cfg = {**CFG, "arms": ["pack"]}
        (self.root / "config.json").write_text(canonical(cfg))
        (self.root / "sample_manifest.csv").write_bytes(
            (ROOT / cfg["sample_manifest"]).read_bytes()
        )
        with patch("runner.load_rows", return_value=[row]), patch(
            "runner.identity",
            return_value={
                "config": cfg,
                "code": {},
                "manifest_sha256": digest_file(ROOT / cfg["sample_manifest"]),
            },
        ):
            (self.root / "run_context.json").write_text(
                canonical({"run_id": "fixture"})
            )
            (self.root / "identity.json").write_text(
                canonical(
                    {
                        "config": cfg,
                        "code": {},
                        "manifest_sha256": digest_file(ROOT / cfg["sample_manifest"]),
                    }
                )
            )
            (self.root / "schedule.json").write_text(canonical(schedule([row], cfg)))
            (self.root / "records.jsonl").write_text(
                canonical(
                    {
                        "entry_id": "x",
                        "arm": "pack",
                        "repeat": 1,
                        "failure_category": None,
                        "reported_cost_usd": 0.0,
                    }
                )
                + "\n"
            )
            (self.root / "unit_journal.jsonl").write_text(
                canonical({"unit": ["x", "pack", 1], "state": "started"})
                + "\n"
                + canonical({"unit": ["x", "pack", 1], "state": "recorded"})
                + "\n"
            )
            (self.root / "call_journal.jsonl").write_text(
                canonical(
                    {
                        "id": "fixture",
                        "unit": {"entry_id": "x", "arm": "pack", "repeat": 1},
                        "state": "started",
                    }
                )
                + "\n"
                + canonical({"id": "fixture", "state": "finished", "cost_usd": 0.0})
                + "\n"
            )
            with patch(
                "runner.run", side_effect=AssertionError("Duplicate model call")
            ):
                execute(cfg, self.root, True)

    def test_paid_interruption_requires_reconciliation(self):
        row = {
            k: "x"
            for k in (
                "entry_id",
                "report_id",
                "project",
                "repo_url",
                "commit",
                "vuln_title",
                "task_description",
            )
        }
        cfg = {**CFG, "arms": ["pack"]}
        (self.root / "config.json").write_text(canonical(cfg))
        (self.root / "sample_manifest.csv").write_bytes(
            (ROOT / cfg["sample_manifest"]).read_bytes()
        )
        ident = {
            "config": cfg,
            "code": {},
            "manifest_sha256": digest_file(ROOT / cfg["sample_manifest"]),
        }
        (self.root / "run_context.json").write_text(canonical({"run_id": "fixture"}))
        (self.root / "identity.json").write_text(canonical(ident))
        (self.root / "unit_journal.jsonl").write_text(
            canonical({"unit": ["x", "pack", 1], "state": "started"}) + "\n"
        )
        with patch("runner.load_rows", return_value=[row]), patch(
            "runner.identity", return_value=ident
        ):
            with self.assertRaises(IntegrityError):
                execute(cfg, self.root, True)

    def test_embedding_truncation_byte_compatibility(self):
        import importlib.util

        path = ROOT / "06_experiments/scripts/c06/common.py"
        spec = importlib.util.spec_from_file_location(
            "legacy_accounting_reference", path
        )
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        samples = [
            ("def example(x):\n    return x + 1\n" * n) for n in range(1, 100, 3)
        ]
        samples += [("中文🔥<|endoftext|>\n" * n) for n in range(1, 100, 3)]
        for sample in samples:
            self.assertEqual(
                index.embedding_text(sample), legacy.truncate_to_tokens(sample, 400)
            )

    def test_head_hash_cannot_hide_modified_worktree(self):
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            cwd=self.root,
            check=True,
        )
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        validate_commit(Universe.scan(self.root), commit)
        (self.root / "src/ok.py").write_text("different committed source")
        with self.assertRaises(IntegrityError):
            validate_commit(Universe.scan(self.root), commit)

    def test_manifest_mutation_is_caught(self):
        self.u.manifest["files"][0]["sha256"] = "corrupted"
        with self.assertRaises(IntegrityError):
            self.u.verify()


if __name__ == "__main__":
    unittest.main(verbosity=2)
