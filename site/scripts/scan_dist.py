"""Fail-closed publication boundary; no network or deployment operations."""
from __future__ import annotations

import argparse
import html
from pathlib import Path
import re
import stat
import sys
from urllib.parse import unquote

SITE = Path(__file__).resolve().parents[1]
# Text-only output: deliberately no maps, archives, data dumps, images or PDFs.
ROUTES = {"methodology", "results", "analysis", "reproducibility", "paper", "resources"}
HTML = re.compile(r"(?:(?:en|zh)/)?(?:(?:methodology|results|analysis|reproducibility|paper|resources)/)?index\.html\Z")
ASSET = re.compile(r"_astro/[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\.[A-Za-z0-9_-]{6,}\.(?:css|js)\Z")
FORBIDDEN = re.compile(
    r"(?:/home/|/Users/|/mnt/[a-z]/Users/|[A-Z]:[\\/]Users[\\/]|"
    r"(?:^|[\s\"'/(])(?:data/raw|\.local|\.env)(?:[/\\\s\"')]|$)|"
    r"(?:^|[\s\"'/(])(?:raw|repos|index_cache|embedding_cache)/|"
    r"\.venv/(?!bin/(?:python|vulnloc)(?:[\s\"'<]|$))|"
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----|"
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|\bgh[pousr]_[A-Za-z0-9]{20,}|"
    r"\bgithub_pat_[A-Za-z0-9_]{20,}|\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}|"
    r"(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[=:]\s*[\"'][^\"']{8,}[\"']|"
    r"sourceMappingURL|metrics\.json|official_per_record|source_provenance\.json|"
    r"artifact_checksums\.json|inputs_sha256|entry_id|failure_category)",
    re.IGNORECASE | re.MULTILINE,
)


def tree(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Required directory missing or symlinked")
    for path in root.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError("Symlink or special file forbidden")
        yield path


def scan(dist, public):
    dist, public = Path(dist), Path(public)
    # public is checked independently: an unused private asset must still fail.
    for path in tree(public):
        if path.relative_to(public).as_posix() != ".nojekyll" or not path.is_file() or path.stat().st_size:
            raise ValueError("public must be empty except an empty .nojekyll")
    found = set()
    for path in tree(dist):
        relative = path.relative_to(dist).as_posix()
        if path.is_dir():
            allowed_dirs = ROUTES | {'en', 'zh'} | {f'{locale}/{route}' for locale in ('en','zh') for route in ROUTES}
            if relative != "_astro" and relative not in allowed_dirs:
                raise ValueError("Unexpected distribution directory")
            continue
        if relative == ".nojekyll":
            if path.stat().st_size:
                raise ValueError("Nonempty .nojekyll")
            continue
        if not (HTML.fullmatch(relative) or ASSET.fullmatch(relative)):
            raise ValueError("File outside publication allowlist")
        if path.stat().st_size > 5_000_000:
            raise ValueError("Unexpectedly large public file")
        text = path.read_text(encoding="utf-8", errors="strict")
        # Check plain text and common escaped/URL encoded representations.
        variants = [text, unquote(text), html.unescape(text),
                    text.replace("\\/", "/").replace("\\", "/")]
        variants.append(re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), text))
        # JS runtimes legitimately contain escaped nulls (e.g. string sanitizers).
        # Reject literal binary null bytes, not the decoded form of a JS escape.
        if "\x00" in text or any(FORBIDDEN.search(value) for value in variants):
            raise ValueError("Forbidden private content in distribution")
        found.add(relative)
    if "index.html" not in found:
        raise ValueError("Distribution has no index.html")
    return len(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=SITE / "dist")
    parser.add_argument("--public", type=Path, default=SITE / "public")
    args = parser.parse_args()
    try:
        count = scan(args.dist, args.public)
        required = [f'{locale}/{route + "/" if route else ""}index.html' for locale in ('en','zh') for route in ('', *ROUTES)]
        if any(not (args.dist / relative).is_file() for relative in required):
            raise ValueError('Incomplete bilingual static routes')
    except (ValueError, OSError, UnicodeError):
        print("FAIL: distribution rejected by publication boundary", file=sys.stderr)
        return 1
    print(f"PASS: {count} public files scanned; public directory clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
