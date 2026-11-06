"""Release-candidate security screening with explicit blocking/review classes.

This is a screening aid, not a release authorization or a replacement for
professional scanners and human/legal review. It never prints matched values.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT_DEFAULT = Path(__file__).resolve().parents[1]
# Frontend dependencies/build caches are not publication-candidate files. Any
# tracked/selected file under a skipped directory still fails the selected-file
# coverage check below; site/dist has its own mandatory publication scanner.
SKIP_DIRS = {".git", ".local", ".venv", "__pycache__", ".pytest_cache", "build", "dist",
             "node_modules", ".astro", "test-results", "playwright-report"}
FORBIDDEN_SEGMENTS = {
    ".local", ".venv", "data/raw", "data/repos", "data/index_cache",
    "embedding_cache", "c06_revision_indices", "c06_revision_embeddings",
}
BLOCKING = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
    "credential_url": re.compile(r"https?://[^/\s:@]+:[^/\s@]+@"),
    "strong_api_key": re.compile(
        r"(?:sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{20,}|sk-proj-[A-Za-z0-9_-]{20,}|"
        r"sk-live-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16})"
    ),
}
REVIEW = {
    "generic_api_key_shape": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "email": re.compile(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}"),
    "personal_path": re.compile(r"(?:/home/|/Users/|[A-Z]:[\\/]Users[\\/])[A-Za-z0-9_.-]+"),
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "credential_assignment": re.compile(r"(?i)(?:api_key|access_token|password)\s*[=:]\s*[\"'][^\"'\s]{12,}[\"']"),
}


def _git(root, *args, binary=False):
    return subprocess.run(
        ["git", "--no-optional-locks", *args], cwd=root, capture_output=True,
        text=not binary, check=False,
    )


def _selected_files(root):
    proc = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", binary=True)
    if proc.returncode != 0:
        raise RuntimeError("git ls-files failed; cannot establish candidate boundary")
    return {p.decode("utf-8", "replace") for p in proc.stdout.split(b"\0") if p}


def _walk_files(root):
    files = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info"))
        for name in sorted(names):
            p = Path(directory) / name
            if p.is_symlink():
                files.append(p)
            elif p.is_file():
                files.append(p)
        for name in list(dirs):
            p = Path(directory) / name
            if p.is_symlink():
                files.append(p)
    return files


def _text_for(path):
    if path.suffix.lower() == ".pdf":
        try:
            proc = subprocess.run(["pdftotext", str(path), "-"], capture_output=True, check=False)
        except OSError:
            return None  # Report unreadable PDF as a review item, never crash scanning.
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8", "replace")
    try:
        return path.read_bytes().decode("utf-8", "replace")
    except OSError:
        return None


def _scan_text(text, rel, findings, history=False):
    for kind, pattern in BLOCKING.items():
        count = len(pattern.findall(text))
        if count:
            findings.append({"path": rel, "kind": kind, "severity": "blocking",
                             "count": count, "review": "credential/high-confidence secret" if not history else "git-history-secret"})
    for kind, pattern in REVIEW.items():
        count = len(pattern.findall(text))
        if count:
            findings.append({"path": rel, "kind": kind, "severity": "review",
                             "count": count, "review": "manual-review-required (not automatically cleared)"})


def _history_findings(root, findings):
    revs = _git(root, "rev-list", "--all")
    commits = revs.stdout.splitlines() if revs.returncode == 0 else []
    if not commits:
        return {"commits": 0, "status": "empty fresh history"}
    objects = _git(root, "rev-list", "--objects", "--all")
    if objects.returncode != 0:
        findings.append({"path": "git-history", "kind": "history-unreadable", "severity": "blocking",
                         "count": 1, "review": "cannot inspect history"})
        return {"commits": len(commits), "status": "blocked: history unreadable"}
    seen = set()
    scanned = 0
    for line in objects.stdout.splitlines():
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        oid = parts[0]
        if oid in seen:
            continue
        seen.add(oid)
        kind = _git(root, "cat-file", "-t", oid)
        if kind.returncode != 0 or kind.stdout.strip() != "blob":
            continue
        size = _git(root, "cat-file", "-s", oid)
        try:
            if int(size.stdout.strip()) > 5_000_000:
                continue
        except ValueError:
            continue
        blob = _git(root, "cat-file", "-p", oid, binary=True)
        if blob.returncode != 0:
            continue
        _scan_text(blob.stdout.decode("utf-8", "replace"), f"git:{oid}", findings, history=True)
        scanned += 1
    return {"commits": len(commits), "blobs_scanned": scanned, "status": "scanned"}


def scan(root=ROOT_DEFAULT):
    root = Path(root).resolve()
    findings = []
    blocked = []
    try:
        selected = _selected_files(root)
        git_available = True
    except RuntimeError:
        # A source tarball has no Git boundary. Scan all non-ignored files and
        # report that the tracked/untracked distinction and history are unavailable.
        selected = None
        git_available = False
        findings.append({
            "path": "git", "kind": "git-unavailable", "severity": "review",
            "count": 1, "review": "manual-review-required: tracked/untracked boundary and history unavailable",
        })
    selected_paths = set()
    if selected is None:
        selected = {
            p.relative_to(root).as_posix()
            for p in _walk_files(root)
            if p.is_file() and not p.is_symlink()
        }
    for rel in sorted(selected):
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or path == root:
            blocked.append({"path": rel, "reason": "selected path escapes candidate"})
            continue
        if path.is_symlink():
            blocked.append({"path": rel, "reason": "selected symlink"})
            continue
        if not path.is_file():
            blocked.append({"path": rel, "reason": "selected path missing/not file"})
            continue
        selected_paths.add(rel)
        parts = rel.split("/")
        if any(rel == segment or rel.startswith(segment + "/") or segment in parts
               for segment in FORBIDDEN_SEGMENTS):
            blocked.append({"path": rel, "reason": "forbidden candidate path class"})
        if path.name in {".env", ".key", ".pem"} or path.name.startswith("secrets"):
            blocked.append({"path": rel, "reason": "credential-like filename"})
    # Explicit symlink check, including directory links that os.walk does not follow.
    for p in _walk_files(root):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            target = os.path.realpath(p)
            outside = not target.startswith(str(root) + os.sep)
            blocked.append({"path": rel, "reason": "symlink" + (" -> outside candidate" if outside else "")})
    # Scan every non-ignored file, plus verify selected files are a subset of that set.
    scanned = []
    for p in _walk_files(root):
        rel = p.relative_to(root).as_posix()
        if p.is_symlink() or not p.is_file():
            continue
        if any(rel == s or rel.startswith(s + "/") for s in (".local", ".venv")):
            continue
        # The scanner's own report contains candidate paths, not credentials.
        if rel == "docs/provenance/safety_scan.json":
            scanned.append(rel)
            continue
        text = _text_for(p)
        if text is None:
            findings.append({"path": rel, "kind": "unreadable", "severity": "review",
                             "count": 1, "review": "manual-review-required"})
            continue
        scanned.append(rel)
        _scan_text(text, rel, findings)
    for rel in sorted(selected_paths - set(scanned)):
        blocked.append({"path": rel, "reason": "selected file not scanned"})
    # Website/build directory must not contain private caches, raw data, or links.
    site = root / "site"
    if site.exists():
        for p in _walk_files(site):
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                blocked.append({"path": rel, "reason": "website symlink"})
            if any(seg in p.parts for seg in (".local", ".venv", "raw", "repos", "index_cache", "embedding_cache")):
                blocked.append({"path": rel, "reason": "website private/build artifact"})
    history = _history_findings(root, findings)
    if not git_available:
        history = {"commits": 0, "status": "git unavailable; tracked boundary and history not scanned"}
    remotes = _git(root, "remote", "-v")
    remote_lines = len([x for x in remotes.stdout.splitlines() if x.strip()]) if remotes.returncode == 0 else 0
    blocking_findings = [f for f in findings if f["severity"] == "blocking"]
    review_findings = [f for f in findings if f["severity"] == "review"]
    report = {
        "scope": "publication candidate only; .local/.venv and original research are NOT publishable",
        "root": str(root),
        "selected_files": len(selected_paths),
        "scanned_files": len(scanned),
        "blocked_paths": blocked,
        "findings": findings,
        "blocking_count": len(blocking_findings),
        "review_count": len(review_findings),
        "history": history,
        "git_available": git_available,
        "git_remote_count": remote_lines,
        "release_authorized": False,
        "packaging_ready": not blocked and not blocking_findings,
        "human_review_required": bool(review_findings),
        "limitations": "Regex/PDF text screening only. Public emails and historical fixture paths are review items, not automatic credentials. Hidden PDF metadata, binary data, names/phone/addresses, and provider-side secrets may be missed.",
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT_DEFAULT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    report = scan(args.root)
    target = args.output or Path(args.root).resolve() / "docs/provenance/safety_scan.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in (
        "selected_files", "scanned_files", "blocking_count", "review_count",
        "packaging_ready", "release_authorized", "history",
    )}, indent=2))
    if not report["packaging_ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
