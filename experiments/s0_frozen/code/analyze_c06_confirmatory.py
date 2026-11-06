#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyze_c06_confirmatory.py — C-06 confirmatory 独立分析 entrypoint（D-013 re-audit Phase 1+2）。

严格 provenance 隔离：不接受仅"名字像 confirmatory"的虚构 run。
拒绝：Attempt 1、aborted_infra、pilot、unknown、metadata 缺失/状态非 success、
git commit 与冻结 implementation_commit 不匹配、frozen 文件 hash 漂移、
record 的 experiment_run_id 混入、duplicate/missing/extra units、infrastructure_error。
要求：exactly 720 expected schedule units == 720 valid completed units + 0 infra failures。
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
import commit_identity
import confirmatory_stats as CS

ABORTED_RUNS = {"c06-confirmatory-20260929T114451Z-bb50"}  # Attempt 1 (ABORTED_INFRA)
PILOT_PREFIX = "c06-micro-mve"
# BLOCKER 3：infra/transport 失败 denylist（不得进入 confirmatory analysis）
INFRA_DENYLIST = {"infrastructure_error", "api_error", "runner_error", "timeout"}
# 合法科学观测（模型行为，计入分析）：成功 / 合法空答案 / correction 后仍格式失败 / 未产出最终答案
VALID_SCIENTIFIC_OUTCOMES = {None, "empty_answer", "parse_failed", "invalid_json", "budget_exhausted_no_final"}


def sha(path):
    return C.sha256_norm(path)


def load_launch_manifest():
    return json.load(open(C.LAUNCH_MANIFEST, encoding="utf-8"))


def check_run_id(run_id):
    if run_id in ABORTED_RUNS:
        return False, f"Attempt 1 / aborted_infra: {run_id}"
    if run_id.startswith(PILOT_PREFIX):
        return False, f"pilot run: {run_id}"
    if not run_id.startswith("c06-confirmatory-"):
        return False, f"unknown run_id: {run_id}"
    return True, None


def _hex_string(value, length):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def check_record_schema(records):
    """Validate serialized runner records, not model quality; no coercion/defaults."""
    if not isinstance(records, list):
        return False, ["records must be a list"]
    string_fields = ("entry_id", "arm", "experiment_run_id", "provider", "model", "thinking",
                     "report_id", "project", "repo_url", "commit", "stratum", "vuln_category_l2",
                     "prompt_config_hash")
    required = set(string_fields) | {"repeat", "mock", "seed", "answer", "failure_category"}
    for i, r in enumerate(records):
        if not isinstance(r, dict) or required - r.keys():
            return False, [f"record {i}: required fields missing / not an object"]
        if any(type(r[k]) is not str for k in string_fields):
            return False, [f"record {i}: provenance field must be a string"]
        if type(r["repeat"]) is not int or r["repeat"] not in (1, 2, 3):
            return False, [f"record {i}: repeat must be integer 1/2/3"]
        if r["arm"] not in ("agent", "rag", "pack") or not r["entry_id"] or not r["experiment_run_id"]:
            return False, [f"record {i}: invalid unit key"]
        if type(r["mock"]) is not bool or type(r["seed"]) is not int:
            return False, [f"record {i}: invalid mock/seed type"]
        if not _hex_string(r["commit"], 40) or not _hex_string(r["prompt_config_hash"], 16):
            return False, [f"record {i}: invalid repo commit / prompt hash"]
        fc, answer = r["failure_category"], r["answer"]
        if fc is not None and (type(fc) is not str or fc not in VALID_SCIENTIFIC_OUTCOMES | INFRA_DENYLIST):
            return False, [f"record {i}: invalid failure_category"]
        if fc is not None:
            if answer is not None:
                return False, [f"record {i}: failed outcome must retain answer=null"]
        else:
            if not isinstance(answer, dict) or "candidate_files" not in answer or not isinstance(answer["candidate_files"], list):
                return False, [f"record {i}: successful answer must contain candidate_files list"]
            candidates = answer["candidate_files"]
            if len(candidates) > 5 or any(not isinstance(c, dict) or
                    not {"path", "line_start", "line_end"} <= c.keys() or type(c["path"]) is not str
                    for c in candidates):
                return False, [f"record {i}: malformed parsed candidates"]
            # Preserve parser/evaluator treatment of model-supplied line values,
            # nonexistent paths and empty candidate lists; never judge accuracy here.
    return True, []


def check_provenance(run_id, metadata_path, records, raw_dir, manifest_by_entry):
    """Required provenance is never optional, including empty/null documents (B2)."""
    import yaml
    ok, issues = check_record_schema(records)
    if not ok:
        return False, issues
    fi_path = os.path.join(raw_dir, "freeze_identity.json")
    try:
        lm = load_launch_manifest()
        with open(fi_path, encoding="utf-8") as f:
            fi = json.load(f)
        if not metadata_path:
            return False, ["metadata 文件缺失"]
        with open(metadata_path, encoding="utf-8") as f:
            meta = yaml.safe_load(f)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as ex:
        return False, [f"provenance 文件缺失或无法解析: {ex}"]

    # Validate structure before dereferencing; {} must not bypass any check.
    if not isinstance(lm, dict) or not _hex_string(lm.get("implementation_commit"), 40):
        return False, ["launch manifest implementation_commit 缺失或格式错误"]
    frozen_hashes = lm.get("frozen_file_sha256")
    if not isinstance(frozen_hashes, dict) or any(
            not _hex_string(frozen_hashes.get(k), 64) for k in C.FROZEN_FILES):
        return False, ["launch manifest frozen_file_sha256 不完整或格式错误"]
    if not isinstance(fi, dict):
        return False, ["freeze_identity 必须是完整 object"]
    for key in ("actual_runtime_git_commit", "implementation_commit"):
        if not _hex_string(fi.get(key), 40):
            issues.append(f"freeze_identity.{key} 缺失/null/格式错误")
    bindings = {"config_sha256": "experiment_config", "sample_manifest_sha256": "sample_manifest",
                "schedule_sha256": "run_schedule", "index_manifest_sha256": "index_manifest",
                "evaluator_sha256": "evaluator"}
    for key in ("launch_manifest_sha256", *bindings):
        if not _hex_string(fi.get(key), 64):
            issues.append(f"freeze_identity.{key} 缺失/null/格式错误")
    expected_model = {"provider": "deepseek", "model": "deepseek-v4-pro", "reasoning": "high"}
    for key, expected in expected_model.items():
        if fi.get(key) != expected:
            issues.append(f"freeze_identity.{key} 缺失或与冻结不一致")
    if lm.get("model") != {"provider": "deepseek", "model": "deepseek-v4-pro", "thinking": "high"}:
        issues.append("launch manifest model 与冻结不一致")

    if not isinstance(meta, dict):
        return False, issues + ["metadata 必须是完整 object"]
    if meta.get("status") != "success":
        issues.append("metadata.status != success")
    if not isinstance(meta.get("run_id"), str) or meta["run_id"] != run_id:
        issues.append("metadata.run_id 缺失或不匹配")
    git = meta.get("git")
    if not isinstance(git, dict) or not _hex_string(git.get("commit"), 40):
        issues.append("metadata.git.commit 缺失/null/格式错误")
    config = meta.get("config")
    if not isinstance(config, dict) or config.get("name") != "c06-confirmatory":
        issues.append("metadata.config 缺失或 name 不匹配")
    if issues:
        return False, issues

    impl_commit = lm["implementation_commit"]
    if fi["implementation_commit"] != impl_commit:
        issues.append("freeze_identity.implementation_commit 与 launch manifest 不匹配")
    if git["commit"] != fi["actual_runtime_git_commit"]:
        issues.append("metadata.git.commit != freeze_identity.runtime")
    try:
        if fi["launch_manifest_sha256"] != sha(C.LAUNCH_MANIFEST):
            issues.append("launch_manifest_sha256 不匹配")
        for key, name in bindings.items():
            if fi[key] != frozen_hashes[name]:
                issues.append(f"{key} 与冻结不一致")
        # Check actual analysis inputs as well as the runtime Git tree.
        for name, rel in C.FROZEN_FILES.items():
            if sha(os.path.join(C.ROOT, rel)) != frozen_hashes[name]:
                issues.append(f"当前 frozen 文件 hash 漂移: {name}")
        with open(os.path.join(C.ROOT, C.FROZEN_FILES["experiment_config"]), encoding="utf-8") as f:
            frozen_config = yaml.safe_load(f)
    except (OSError, ValueError, yaml.YAMLError) as ex:
        return False, issues + [f"frozen 文件读取失败: {ex}"]
    # The harness stores the complete config plus defaults. Require every frozen
    # key, while allowing those harness-added defaults (e.g. absolute workdir).
    for key, value in frozen_config.items():
        if type(config.get(key)) is not type(value) or config.get(key) != value:
            issues.append(f"metadata.config.{key} 缺失或与冻结不一致")
    if meta.get("command") != frozen_config["command"]:
        issues.append("metadata.command 缺失或与冻结不一致")
    if type(meta.get("seed")) is not int or meta["seed"] != frozen_config["seed"]:
        issues.append("metadata.seed 缺失或与冻结不一致")
    if issues:
        return False, issues

    ok, succ_issues = commit_identity.validate_successor(
        impl_commit, fi["actual_runtime_git_commit"], C.ROOT, C.FROZEN_FILES, frozen_hashes, None)
    if not ok:
        issues += succ_issues

    # Bind every unit to the frozen run AND sample, not just the run metadata.
    from runner import config_hash
    for i, r in enumerate(records):
        if r["experiment_run_id"] != run_id:
            issues.append(f"record {i}: experiment_run_id mismatch")
        if (r["provider"], r["model"], r["thinking"]) != (fi["provider"], fi["model"], fi["reasoning"]):
            issues.append(f"record {i}: provider/model/thinking mismatch")
        if r["mock"] is not False:
            issues.append(f"record {i}: mock must be false")
        # This is the runner's existing per-record seed, not the schedule seed.
        if r["seed"] != 0:
            issues.append(f"record {i}: runner seed mismatch")
        if r["entry_id"] not in manifest_by_entry:
            issues.append(f"record {i}: entry outside frozen sample")
            continue
        row = manifest_by_entry[r["entry_id"]]
        for field in ("report_id", "project", "repo_url", "commit", "stratum", "vuln_category_l2"):
            if r[field] != row[field]:
                issues.append(f"record {i}: sample {field} mismatch")
        if r["prompt_config_hash"] != config_hash(r["arm"], row):
            issues.append(f"record {i}: prompt_config_hash mismatch")
        if r["failure_category"] in INFRA_DENYLIST:
            issues.append(f"record {i}: infra/transport failure {r['failure_category']}")

    return (not issues), issues


def check_completeness(records, expected_units):
    issues = []
    for r in records:
        if (not isinstance(r, dict) or not {"entry_id", "repeat", "arm", "failure_category"} <= r.keys()
                or type(r["entry_id"]) is not str or type(r["arm"]) is not str
                or type(r["repeat"]) is not int or r["repeat"] not in (1, 2, 3)
                or r["arm"] not in ("agent", "rag", "pack")):
            return False, ["invalid schedule-unit key (no coercion allowed)"]
    got_set = {(r["entry_id"], r["repeat"], r["arm"]) for r in records}
    exp_set = set(expected_units)
    if len(exp_set) != 720:
        issues.append(f"expected != 720: {len(exp_set)}")
    if len(records) != 720:
        issues.append(f"records != 720: {len(records)}")
    if len(got_set) != len(records):
        issues.append(f"duplicate units: {len(records)} records -> {len(got_set)} unique")
    if exp_set - got_set:
        issues.append(f"missing units: {len(exp_set - got_set)}")
    if got_set - exp_set:
        issues.append(f"extra units: {len(got_set - exp_set)}")
    if any(r["failure_category"] == "infrastructure_error" for r in records):
        issues.append("infrastructure_error records present")
    return (not issues), issues


def fail(msg):
    print(f"[analyze_confirmatory] FAIL: {msg}")
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--metadata")
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--processed-dir", required=True)
    ap.add_argument("--tables-dir", required=True)
    ap.add_argument("--figures-dir", required=True)
    args = ap.parse_args()

    # 1. run_id
    ok, err = check_run_id(args.run_id)
    if not ok:
        fail(f"拒绝 {err}")

    # 2. frozen manifest + schedule
    manifest = [r for r in csv.DictReader(open(C.CONFIRMATORY_MANIFEST, encoding="utf-8"))
                if r["role"] == "confirmatory"]
    manifest_by_entry = {r["entry_id"]: r for r in manifest}
    sched = list(csv.DictReader(open(C.CONFIRMATORY_SCHEDULE, encoding="utf-8")))
    expected_units = {(r["entry_id"], int(r["repeat"]), r["arm"]) for r in sched}

    # 3. records
    rec_path = os.path.join(args.raw_dir, "records.jsonl")
    if not os.path.exists(rec_path):
        fail(f"records.jsonl 不存在: {rec_path}")
    try:
        records = [json.loads(l) for l in open(rec_path, encoding="utf-8")]
    except (OSError, ValueError) as ex:
        fail(f"records.jsonl unreadable/malformed: {ex}")

    # 4. provenance 隔离
    ok, issues = check_provenance(args.run_id, args.metadata, records, args.raw_dir, manifest_by_entry)
    if not ok:
        for i in issues:
            print(f"  - {i}")
        fail("provenance isolation FAILED")

    # 5. 完整性
    ok, issues = check_completeness(records, expected_units)
    if not ok:
        for i in issues:
            print(f"  - {i}")
        fail("720-unit completeness check FAILED")

    print(f"[analyze_confirmatory] run_id={args.run_id} records={len(records)} "
          f"expected={len(expected_units)} unique_units={len({(r['entry_id'], r['repeat'], r['arm']) for r in records})} "
          f"-> provenance + completeness OK")

    # 6. 冻结统计
    cluster_id_fn = lambda row: row.get("cluster_id")  # noqa: E731
    repo_dir_fn = lambda row, rec: C.repo_dir(row["project"], row["commit"])  # noqa: E731
    entries = sorted(manifest_by_entry.keys())
    stats = CS.run_primary_and_secondary(records, manifest_by_entry, entries, cluster_id_fn, repo_dir_fn)

    # 7. 输出
    os.makedirs(args.processed_dir, exist_ok=True)
    os.makedirs(args.tables_dir, exist_ok=True)
    with open(os.path.join(args.processed_dir, "stats.json"), "w", encoding="utf-8") as f:
        json.dump({"run_id": args.run_id, "stats": stats}, f, indent=2, ensure_ascii=False)

    lines = [f"# C-06 confirmatory 结果摘要 — {args.run_id}", "",
             "## PRIMARY (Agent vs Pack / File Recall@5)", ""]
    p = stats["primary"]["agent_vs_pack"]
    lines.append(f"- mean={p['mean']} 95%CI={p['bootstrap_ci95']} d_z={p['cohens_dz']} "
                 f"perm_p={p['permutation_p']} wilcoxon_p={p['wilcoxon_p']}")
    lines += ["", "## 臂均值 FR@5", ""]
    for a, m in stats["primary"]["arm_means_fr"].items():
        lines.append(f"- {a}: {m}")
    lines += ["", "## 臂均值 LineRecall@5", ""]
    for a, m in stats["secondary"]["arm_means_lr"].items():
        lines.append(f"- {a}: {m}")
    lines += ["", "## Secondary family (BH-FDR)", ""]
    for k, d in stats["secondary"].items():
        if isinstance(d, dict) and "mean" in d:
            lines.append(f"- {k}: mean={d['mean']} CI={d['bootstrap_ci95']} perm_p={d['permutation_p']} "
                         f"q={stats['secondary'].get('bh_fdr_qvalues', {}).get(k)}")
    lines += ["", "## Subgroups（PATH_HINT / NO_PATH_HINT）", ""]
    for name, d in stats["subgroups"].items():
        ap_ = d["agent_vs_pack"]
        lines.append(f"- {name} (n={d['n']}): agent_vs_pack mean={ap_['mean']} CI={ap_['bootstrap_ci95']} "
                     f"perm_p={ap_['permutation_p']}; arms={d['arm_means_fr']}")
    lines += ["", "## Cluster sensitivity", ""]
    cs = stats["cluster_sensitivity"]
    ap_ = cs["leave_dominant_out_agent_vs_pack"]
    lines.append(f"- dominant={cs['dominant_cluster']} (n={cs['dominant_n']}); leave-out n={cs['leave_dominant_out_n']}: "
                 f"mean={ap_['mean']} CI={ap_['bootstrap_ci95']} perm_p={ap_['permutation_p']}")
    lines.append(f"- leave-one-cluster-out: {cs.get('leave_one_out')}")
    lines += ["", "## Invalid path rate", ""]
    for a, d in stats["invalid_path"].items():
        lines.append(f"- {a}: {d['rate']} ({d['bad']}/{d['total']})")
    lines += ["", "## Repeat stability / cost-latency", ""]
    lines.append(f"- repeat |diff|: {stats['repeat_stability']}")
    for a, d in stats["cost_latency"].items():
        lines.append(f"- {a}: cost_mean=${d['cost_mean']} latency={d['latency_mean_s']}s")
    open(os.path.join(args.tables_dir, "summary.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")

    print("[analyze_confirmatory] done. primary agent_vs_pack mean=", p["mean"],
          "CI=", p["bootstrap_ci95"], "perm_p=", p["permutation_p"])


if __name__ == "__main__":
    main()
