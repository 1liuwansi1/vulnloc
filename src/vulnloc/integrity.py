"""Hash-checked, path-contained artifact access."""
import hashlib
import json
from pathlib import Path


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def contained(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Artifact path escapes root")
    return path


def verify(root):
    root = Path(root).resolve()
    manifest = read_json(root / "docs/provenance/artifact_checksums.json")
    if not manifest:
        raise ValueError("Empty integrity manifest")
    for relative, expected in manifest.items():
        path = contained(root, relative)
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"Integrity failure: {relative}")
    return len(manifest)
