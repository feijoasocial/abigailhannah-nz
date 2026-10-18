#!/usr/bin/env python3
"""Turn a BLOG ARTICLES page (ClickUp markdown export) into content/episodes/<slug>.md.

Usage: python tools/import_article.py path/to/page.md [more.md ...]

- Reads the ```yaml front matter block at the top of the page.
- Drops everything from the "Notes for Abigail" section down.
- Drops the "(Each anchor id becomes...)" helper line.
- Turns "Heading · `#anchor`" bullets into jump links and tags the matching H2 with {#anchor}.
- Keeps the live URL: if a content file for this episode already exists, its slug, date,
  image, spotify, guest and oldUrl are kept. Otherwise the slug and date come from the feed.
"""
import re, sys, datetime as dt
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
EPS = ROOT / "content" / "episodes"
FEED = ROOT / "data" / "feed.xml"

JUMP_RE = re.compile(r"^(\s*[*\-]\s+)(.+?)\s+·\s+`#([a-z0-9\-]+)`\s*$")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower().replace("’", "'")).strip()


def feed_lookup(number: int) -> dict:
    sys.path.insert(0, str(ROOT))
    import build  # noqa: E402
    for f in build.parse_feed(FEED.read_text(encoding="utf-8")):
        if f["number"] == number and not f["bonus"]:
            return f
    return {}


def existing_for(number: int) -> tuple[Path | None, dict]:
    for p in EPS.glob("*.md"):
        m = re.match(r"^---\n(.*?)\n---\n", p.read_text(encoding="utf-8"), re.S)
        meta = yaml.safe_load(m.group(1)) if m else {}
        if meta.get("episode") == number and not meta.get("bonus"):
            return p, meta
    return None, {}


def convert(src: Path) -> Path:
    text = src.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.match(r"^\s*```ya?ml\n(.*?)\n```\n(.*)$", text, re.S)
    if not m:
        raise SystemExit(f"{src}: no ```yaml block at the top")
    art = yaml.safe_load(m.group(1))
    body = m.group(2)

    # cut the private notes (and the divider just above them)
    notes = re.search(r"^#+\s*\S*\s*Notes for Abigail.*$", body, re.M | re.I)
    if notes:
        body = body[:notes.start()]
        body = re.sub(r"\n\s*(\* \* \*|---|\*\*\*)\s*\n*\Z", "\n", body.rstrip() + "\n")
    body = re.sub(r"^_\(Each anchor id becomes.*?\)_\s*\n", "", body, flags=re.M)

    # jump links
    anchors = []
    lines = []
    for ln in body.split("\n"):
        j = JUMP_RE.match(ln)
        if j:
            anchors.append((j.group(2), j.group(3)))
            ln = f"{j.group(1)}[{j.group(2)}](#{j.group(3)})"
        lines.append(ln)
    body = "\n".join(lines)

    h2s = [(mm.start(), mm.group(0), mm.group(1)) for mm in re.finditer(r"^## (.+?)[ \t]*$", body, re.M)]
    missing = []
    for label, aid in anchors:
        hit = next((h for h in h2s if norm(h[2]) == norm(label)), None)
        if hit is None:
            missing.append(f"{label} #{aid}")
            continue
        body = body.replace(hit[1], f"## {hit[2]} {{#{aid}}}", 1)
        h2s.remove(hit)
    if missing:
        raise SystemExit(f"{src}: no H2 matches jump link(s): {missing}")

    number = int(art["episode"])
    path, old = existing_for(number)
    feed = feed_lookup(number)
    if not old and not feed:
        raise SystemExit(f"{src}: episode {number} is not in the feed or content yet")

    slug = old.get("slug") or feed["feed_slug"]
    if str(art.get("slug", slug)) != slug:
        print(f"  note: page slug '{art.get('slug')}' differs from live slug '{slug}', keeping the live one")
    title = old.get("title") or feed["title"]
    date = old.get("date") or feed["date"].astimezone(dt.timezone(dt.timedelta(hours=12))).date()

    fm = {
        "title": title,
        "slug": slug,
        "date": date,
        "updated": art.get("updated") or dt.date.today(),
        "description": art.get("description", "") or old.get("description", ""),
        "seoTitle": art.get("seoTitle", "") or "",
        "focusKeyword": art.get("focusKeyword", "") or "",
        "image": old.get("image", ""),
        "imageAlt": old.get("imageAlt", ""),
        "categories": old.get("categories") or ["Podcast"],
        "tags": old.get("tags") or [],
        "episode": number,
        "bonus": False,
        "guest": old.get("guest") or feed.get("guest", ""),
        "spotify": old.get("spotify", ""),
        "source": "clickup-blog-articles",
    }
    if old.get("oldUrl"):
        fm["oldUrl"] = old["oldUrl"]

    out = path or (EPS / f"{slug}.md")
    front = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=10_000).strip()
    out.write_text(f"---\n{front}\n---\n{body.strip()}\n", encoding="utf-8")
    print(f"{src.name} -> {out.relative_to(ROOT)}  ({len(anchors)} jump links, {'updated' if path else 'new'})")
    return out


if __name__ == "__main__":
    for a in sys.argv[1:]:
        convert(Path(a))
