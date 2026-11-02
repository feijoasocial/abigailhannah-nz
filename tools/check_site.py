#!/usr/bin/env python3
"""Pre-deploy checks on the built site (run by the build workflow after check_links.py).

Fails the build, so nothing goes live, if:
  - any structured data block (application/ld+json) is not valid JSON or has no @type
  - any local image, srcset copy or video poster a page points to is missing
Warns (does not fail) for search titles over 60 characters.

Usage: python tools/check_site.py
"""
import html as H
import json
import re
import sys
from pathlib import Path

DIST = Path(__file__).resolve().parent.parent / "dist"
LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
SRCS = re.compile(r'\s(?:src|poster|data-src)="(/[^"]+)"')
SRCSET = re.compile(r'\ssrcset="([^"]+)"')


def exists(url: str) -> bool:
    p = DIST / url.split("?")[0].split("#")[0].lstrip("/")
    return p.is_file() or (p / "index.html").is_file()


def main() -> int:
    errors, warnings, pages = [], [], 0
    for page in sorted(DIST.rglob("*.html")):
        t = page.read_text(encoding="utf-8")
        if "Page moved" in t[:400]:
            continue
        pages += 1
        rel = page.relative_to(DIST)
        for block in LD.findall(t):
            try:
                if "@type" not in json.loads(block):
                    errors.append(f"{rel}: structured data has no @type")
            except json.JSONDecodeError as e:
                errors.append(f"{rel}: structured data is not valid JSON ({e.msg})")
        for tag in re.findall(r"<(?:img|video|source)\b[^>]*>", t):
            urls = SRCS.findall(tag)
            for s in SRCSET.findall(tag):
                urls += [c.strip().split(" ")[0] for c in s.split(",")]
            for u in urls:
                if u.startswith("//") or exists(u):
                    continue
                errors.append(f"{rel}: missing file {u}")
        if 'name="robots" content="noindex' not in t:
            m = re.search(r"<title>(.*?)</title>", t, re.S)
            if m and len(H.unescape(m.group(1))) > 60:
                warnings.append(f"{rel}: title is {len(H.unescape(m.group(1)))} characters")
    for w in warnings:
        print("warning:", w)
    for e in errors[:50]:
        print("ERROR:", e)
    print(f"checked {pages} pages: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
