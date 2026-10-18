#!/usr/bin/env python3
"""Check that every internal link and #anchor in the built site resolves.

Usage: python tools/check_links.py [page-dir ...]   (default: every page in dist/)
"""
import re, sys
from pathlib import Path
from urllib.parse import urlparse, unquote

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
HOSTS = {"abigailhannah.nz", "www.abigailhannah.nz"}


def target(path: str) -> Path:
    p = DIST / unquote(path).lstrip("/")
    return p / "index.html" if p.is_dir() or not p.suffix else p


def main(pages):
    bad = 0
    for page in pages:
        html = page.read_text(encoding="utf-8")
        ids = set(re.findall(r'\sid="([^"]+)"', html))
        for href in re.findall(r'<a\s[^>]*href="([^"]+)"', html):
            u = urlparse(href)
            if u.scheme in ("mailto", "tel"):
                continue
            if u.netloc and u.netloc not in HOSTS:
                continue
            if not u.path and u.fragment:
                if u.fragment not in ids and u.fragment != "top":
                    print(f"{page.relative_to(DIST)}: missing anchor #{u.fragment}"); bad += 1
                continue
            if u.path and not target(u.path).exists():
                print(f"{page.relative_to(DIST)}: broken link {href}"); bad += 1
    print(f"checked {len(pages)} page(s), {bad} problem(s)")
    return bad


if __name__ == "__main__":
    args = sys.argv[1:]
    pages = [DIST / a.strip("/") / "index.html" for a in args] if args else sorted(DIST.rglob("*.html"))
    sys.exit(1 if main(pages) else 0)
