"""One materialized source universe for authorization, search, indexing and packing."""

from __future__ import annotations
import json, os, subprocess
from pathlib import Path, PurePosixPath
from core import ROOT, IntegrityError, digest_bytes, fingerprint


def policy():
    return json.loads(
        (ROOT / "06_experiments/c06_repair/source_policy.json").read_text()
    )


def repo_for(row):
    return ROOT / "05_code/repos" / f"{row['project']}__{row['commit'][:8]}"


class Universe:
    def __init__(self, root, manifest):
        self.root = Path(root).resolve()
        self.manifest = manifest
        self.files = {f["path"]: f for f in manifest["files"]}
        self.directories = {"."}
        for p in self.files:
            self.directories.update(str(parent) for parent in PurePosixPath(p).parents)
        self.fingerprint = fingerprint(manifest)

    @classmethod
    def scan(cls, root, identity=None, verify_git=False):
        root = Path(root).resolve()
        p = policy()
        entries = []
        excluded = {}
        if verify_git:
            got = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            if got != identity["commit"]:
                raise IntegrityError("Repository commit mismatch")
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(
                d
                for d in dirs
                if d not in p["skip_directories"]
                and not (Path(directory) / d).is_symlink()
            )
            for name in sorted(files):
                full = Path(directory) / name
                rel = full.relative_to(root).as_posix()

                def skip(reason):
                    excluded[reason] = excluded.get(reason, 0) + 1

                if full.is_symlink():
                    skip("symlink")
                    continue
                if "\n" in rel or "\r" in rel or "\x00" in rel:
                    skip("unsupported_path")
                    continue
                if name in p["skip_filenames"]:
                    skip("filename")
                    continue
                ext = full.suffix.lower()
                if ext and ext not in p["extensions"]:
                    skip("extension")
                    continue
                if full.stat().st_size > p["max_file_bytes"]:
                    skip("size")
                    continue
                raw = full.read_bytes()
                if b"\x00" in raw[: p["binary_prefix_bytes"]]:
                    skip("binary")
                    continue
                # Explicit universal-newline normalization, shared by all three arms.
                text = (
                    raw.decode("utf-8", errors="replace")
                    .replace("\r\n", "\n")
                    .replace("\r", "\n")
                )
                entries.append(
                    {
                        "path": rel,
                        "bytes": len(raw),
                        "sha256": digest_bytes(raw),
                        "lines": len(text.splitlines()),
                        "nonblank": bool(text.strip()),
                    }
                )
        manifest = {
            "identity": identity or {},
            "policy": p,
            "files": sorted(entries, key=lambda e: e["path"]),
            "excluded_counts": excluded,
        }
        return cls(root, manifest)

    def read(self, rel):
        if rel not in self.files:
            raise PermissionError("Path outside common source universe")
        full = self.root / rel
        if full.is_symlink() or not full.resolve().is_relative_to(self.root):
            raise IntegrityError("Source path changed")
        raw = full.read_bytes()
        if digest_bytes(raw) != self.files[rel]["sha256"]:
            raise IntegrityError("Source content changed")
        return (
            raw.decode("utf-8", errors="replace")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .splitlines()
        )

    def listing(self, rel="."):
        rel = str(PurePosixPath(rel))
        if rel not in self.directories:
            raise PermissionError("Directory outside common universe")
        prefix = "" if rel == "." else rel + "/"
        children = set()
        for p in self.files:
            if p.startswith(prefix):
                tail = p[len(prefix) :]
                part = tail.split("/")[0]
                children.add(part + ("/" if "/" in tail else ""))
        return sorted(children)

    def verify(self):
        if fingerprint(self.manifest) != self.fingerprint:
            raise IntegrityError("Source manifest mutated in memory")
        if self.files != {f["path"]: f for f in self.manifest["files"]}:
            raise IntegrityError("Authorization table changed")
        current = Universe.scan(self.root, self.manifest["identity"])
        if current.fingerprint != self.fingerprint:
            raise IntegrityError("Universe changed since preparation")


def chunks(universe, lines=60, overlap=15):
    if not 0 <= overlap < lines:
        raise ValueError("Invalid chunk configuration")
    for path in universe.files:
        content = universe.read(path)
        for offset in range(0, len(content), lines - overlap):
            segment = content[offset : offset + lines]
            if any(s.strip() for s in segment):
                yield {
                    "path": path,
                    "start": offset + 1,
                    "end": offset + len(segment),
                    "text": "\n".join(segment),
                }


def validate_commit(universe, expected_commit):
    """HEAD equality alone is insufficient: verify every eligible file's Git blob."""
    import hashlib

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=universe.root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if head != expected_commit:
        raise IntegrityError("Repository HEAD differs")
    tree = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "HEAD"],
        cwd=universe.root,
        capture_output=True,
        check=True,
    ).stdout
    blobs = {}
    for item in tree.split(b"\0"):
        if not item:
            continue
        info, path = item.split(b"\t", 1)
        mode, kind, oid = info.split()
        if kind == b"blob":
            blobs[path.decode("utf-8")] = oid.decode()
    for path in universe.files:
        if path not in blobs:
            raise IntegrityError("Eligible source is not in declared commit: " + path)
        raw = (universe.root / path).read_bytes()
        payload = b"blob " + str(len(raw)).encode() + b"\0" + raw
        actual = (
            hashlib.sha1(payload) if len(blobs[path]) == 40 else hashlib.sha256(payload)
        ).hexdigest()
        if actual != blobs[path]:
            raise IntegrityError("Working source differs from commit blob: " + path)
