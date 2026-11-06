"""Static site input allowlist. No copied research documents or directory aliases."""
from pathlib import Path
import re
import sys

SITE = Path(__file__).resolve().parents[1]


def validate(site=SITE):
    source = site / "src"
    if site.is_symlink() or any(p.is_symlink() or p.name.startswith('.env') for p in site.iterdir() if p.is_file() or p.is_symlink()):
        raise ValueError("Symlinked root file or private environment configuration")
    for root in (source, site / "public"):
        if root.is_symlink() or not root.is_dir():
            raise ValueError("Missing or symlinked source directory")
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("Symlink source forbidden")
            if any(part in {'.local', '.venv', 'raw', 'repos', 'index_cache', 'embedding_cache'} for part in path.relative_to(site).parts):
                raise ValueError("Private source directory forbidden")
            if path.is_dir():
                continue
            rel = path.relative_to(site).as_posix()
            if root.name == "public":
                if rel != "public/.nojekyll" or path.stat().st_size:
                    raise ValueError("Unapproved public asset")
                continue
            if path.suffix not in {".ts", ".tsx", ".astro", ".css", ".json"}:
                raise ValueError("Unapproved source type")
            if path.suffix == ".json" and rel != "src/data/verified.json":
                raise ValueError("Only generated verified data may be imported")
            if path.suffix == ".json":
                continue
            text = path.read_text(encoding="utf-8")
            # This text-only site has no approved URL-loaded CSS assets. Vite
            # resolves @import url() and background url() before output scanning,
            # which can erase an unsafe file's origin. Reject these at input,
            # including comment-separated tokens; CSS escapes are not needed by
            # the authored stylesheet and could otherwise hide the URL token.
            clean = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
            styles = [clean] if path.suffix == '.css' else re.findall(r'<style\b[^>]*>(.*?)</style\s*>', clean, re.IGNORECASE | re.DOTALL)
            if re.search(r"url\s*\(", clean, re.IGNORECASE) or any('\\' in style for style in styles):
                raise ValueError("Unapproved CSS URL or escape")
            # No arbitrary filesystem access, HTTP loading, globs, or dynamic data
            # imports. React and ECharts imports are explicit package dependencies.
            if re.search(r"node:|\b(?:require|fetch)\s*\(|import\s*\(|import\.meta\.glob|readFile|process\.env", text):
                raise ValueError("Unapproved dynamic input mechanism")
            imports = re.findall(r"(?:from\s*|import\s*|@import\s*)[\"']([^\"']+)[\"']", clean)
            for name in imports:
                if name.startswith("."):
                    target = (path.parent / name).resolve()
                    if not target.is_relative_to(source.resolve()):
                        raise ValueError("Source import escapes site source")
                elif name.split('/')[0] not in {"react", "echarts", "tailwindcss"}:
                    raise ValueError("Unapproved package import")
    return True


if __name__ == "__main__":
    try:
        validate()
        print("PASS: source import and static asset allowlist")
    except (ValueError, OSError):
        print("FAIL: unsafe website input", file=sys.stderr)
        sys.exit(1)
