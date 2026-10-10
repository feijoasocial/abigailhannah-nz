#!/usr/bin/env python3
"""Static site generator for abigailhannah.nz.

    python3 build.py            # build into dist/
    python3 build.py --offline  # never fetch the feed, use data/feed.xml

Reads content/episodes/*.md and content/posts/*.md (YAML front matter + Markdown),
merges the episode posts with the live Captivate RSS feed, and renders Jinja2 templates.
Every old WordPress URL is reproduced at the same path.
"""
from __future__ import annotations
import argparse, datetime as dt, html, json, re, shutil, sys, urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown, yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).parent
import os
BASE = os.environ.get("SITE_BASE", "").rstrip("/")  # e.g. "/abigailhannah-nz" on the github.io preview; empty on the real domain
_ATTR_RE = re.compile(r'((?:href|src|poster|action)=")/(?!/)')
def rebase(html_text: str) -> str:
    return _ATTR_RE.sub(lambda m: m.group(1) + BASE + "/", html_text) if BASE else html_text
CONTENT, TEMPLATES, STATIC, DATA, DIST = ROOT / "content", ROOT / "templates", ROOT / "static", ROOT / "data", ROOT / "dist"
NZ = ZoneInfo("Pacific/Auckland")
cfg = yaml.safe_load((ROOT / "config.yml").read_text(encoding="utf-8"))
MD = markdown.Markdown(extensions=["extra", "sane_lists", "toc"], output_format="html5")

# ---------- helpers ----------
def slugify(s: str) -> str:
    s = html.unescape(s).lower().replace("&", "and")
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", s))

def strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()

def fmt_date(d: dt.datetime | dt.date) -> str:
    if isinstance(d, dt.datetime):
        d = d.astimezone(NZ)
    return f"{d.day} {d.strftime('%B %Y')}"

def fmt_duration(d: str) -> str:
    if not d or d.strip("0:") == "": return ""
    if d.isdigit():
        s = int(d); h, m = divmod(s, 3600); m = round(m / 60)
        return f"{h} hr {m} min" if h else f"{m} min"
    parts = d.split(":")
    if len(parts) == 3: return f"{int(parts[0])} hr {int(parts[1])} min" if int(parts[0]) else f"{int(parts[1])} min"
    if len(parts) == 2: return f"{int(parts[0])} min"
    return d

def ep_label(e) -> str:
    if e.get("bonus"): return "Bonus"
    return f"{e['number']:03d}" if e.get("number") is not None else ""

def to_dt(v) -> dt.datetime:
    if isinstance(v, dt.datetime): return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)
    if isinstance(v, dt.date): return dt.datetime(v.year, v.month, v.day, tzinfo=dt.timezone.utc)
    return dt.datetime.fromisoformat(str(v)).replace(tzinfo=dt.timezone.utc)

EP_RE = re.compile(r"^\s*(\d{3}|BONUS)\s*[:\-]\s*(.*)$", re.I)
GUEST_RE = re.compile(r"\bwith\s+(.+?)\s*[.!]?$", re.I)

# ---------- content ----------
def load_md(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    meta = yaml.safe_load(m.group(1)) if m else {}
    body = m.group(2) if m else text
    MD.reset()
    meta["html"] = MD.convert(body)
    meta["words"] = len(re.findall(r"\w+", body))
    meta["date"] = to_dt(meta["date"])
    meta["updated"] = to_dt(meta.get("updated") or meta["date"])
    meta.setdefault("categories", []); meta.setdefault("tags", [])
    meta["categories"] = [html.unescape(c) for c in meta["categories"]]
    meta.setdefault("image", ""); meta.setdefault("imageAlt", ""); meta.setdefault("description", "")
    meta.setdefault("seoTitle", ""); meta.setdefault("archive", False)
    meta["url"] = f"/{meta['slug']}/"
    return meta

def load_collection(name: str) -> list[dict]:
    return sorted((load_md(p) for p in (CONTENT / name).glob("*.md")), key=lambda m: m["date"], reverse=True)

# ---------- feed ----------
def fetch_feed(offline: bool) -> str:
    snap = DATA / "feed.xml"
    if not offline:
        try:
            req = urllib.request.Request(cfg["feed_url"], headers={"User-Agent": "abigailhannah.nz build"})
            with urllib.request.urlopen(req, timeout=60) as r:
                xml = r.read().decode("utf-8")
            if "<item>" not in xml: raise RuntimeError("feed has no items")
            DATA.mkdir(exist_ok=True); snap.write_text(xml, encoding="utf-8")
            print(f"[feed] fetched live feed ({len(xml):,} bytes)")
            return xml
        except Exception as e:  # noqa
            print(f"[feed] live fetch failed: {e}", file=sys.stderr)
    if snap.exists():
        print("[feed] using snapshot data/feed.xml")
        return snap.read_text(encoding="utf-8")
    raise SystemExit("No feed available: live fetch failed and data/feed.xml is missing")

NSF = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd", "content": "http://purl.org/rss/1.0/modules/content/"}

def parse_feed(xml: str) -> list[dict]:
    ch = ET.fromstring(xml).find("channel")
    out = []
    for it in ch.findall("item"):
        title = (it.findtext("title") or "").strip()
        m = EP_RE.match(title)
        ep_field = (it.findtext("itunes:episode", namespaces=NSF) or "").strip()
        number = int(m.group(1)) if m and m.group(1).upper() != "BONUS" else (int(ep_field) if ep_field.isdigit() else None)
        bonus = bool(m) and m.group(1).upper() == "BONUS"
        clean = m.group(2) if m else title
        g = GUEST_RE.search(clean)
        desc = it.findtext("content:encoded", namespaces=NSF) or it.findtext("description") or ""
        link = (it.findtext("link") or "").strip()
        enc = it.find("enclosure")
        img = it.find("itunes:image", namespaces=NSF)
        pub = it.findtext("pubDate") or ""
        out.append({
            "guid": (it.findtext("guid") or "").strip(), "number": number, "bonus": bonus, "title": title,
            "clean_title": clean, "guest": g.group(1).strip() if g else "", "date": parsedate_to_datetime(pub),
            "description_html": desc, "summary": strip_html(desc)[:160], "link": link,
            "feed_slug": link.rstrip("/").split("/")[-1] if link else "",
            "audio_url": enc.get("url") if enc is not None else "", "audio_bytes": int(enc.get("length") or 0) if enc is not None else 0,
            "duration": (it.findtext("itunes:duration", namespaces=NSF) or "").strip(),
            "image": img.get("href") if img is not None else "",
        })
    return out

def merge_episodes(feed: list[dict], posts: list[dict]) -> list[dict]:
    by_num = {p["episode"]: p for p in posts if p.get("episode") is not None}
    bonus_by_day = {p["date"].date(): p for p in posts if p.get("bonus")}
    used, merged = set(), []
    for f in feed:
        c = by_num.get(f["number"]) if f["number"] is not None else None
        if c is None and f["bonus"]:
            c = bonus_by_day.get(f["date"].astimezone(NZ).date()) or bonus_by_day.get(f["date"].date())
        if c: used.add(c["slug"])
        e = dict(f)
        e["slug"] = c["slug"] if c else f["feed_slug"]
        e["spotify"] = (c or {}).get("spotify", "")
        e["content"] = c
        e["image"] = (c or {}).get("image") or f["image"]
        e["description"] = (c or {}).get("description") or f["summary"]
        merged.append(e)
    for c in posts:  # content with no feed match keeps its URL alive
        if c["slug"] in used: continue
        m = EP_RE.match(c["title"])
        merged.append({**{"guid": "", "number": c.get("episode"), "bonus": c.get("bonus", False), "title": c["title"],
                          "clean_title": m.group(2) if m else c["title"], "guest": c.get("guest", ""), "date": c["date"],
                          "description_html": "", "summary": c["description"], "link": "", "feed_slug": c["slug"],
                          "audio_url": "", "audio_bytes": 0, "duration": "", "image": c["image"]},
                       "slug": c["slug"], "spotify": c.get("spotify", ""), "content": c, "description": c["description"]})
    merged.sort(key=lambda e: e["date"], reverse=True)
    for e in merged:
        e["url"] = f"/{e['slug']}/"; e["label"] = ep_label(e)
    return merged

# ---------- render ----------
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--offline", action="store_true"); args = ap.parse_args()
    episode_posts = load_collection("episodes")
    posts = load_collection("posts")
    episodes = merge_episodes(parse_feed(fetch_feed(args.offline)), episode_posts)
    numbered = sum(1 for e in episodes if e["number"] is not None)

    cats: dict[str, dict] = {}
    for p in posts:
        for c in p["categories"]:
            cats.setdefault(slugify(c), {"name": c, "slug": slugify(c), "posts": []})["posts"].append(p)

    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)
    env.filters.update(date=fmt_date, duration=fmt_duration, slugify=slugify, tojson=json.dumps)
    now = dt.datetime.now(dt.timezone.utc)
    base = {"cfg": cfg, "year": now.year, "episodes": episodes, "numbered": numbered, "posts": posts, "cats": cats}

    if DIST.exists(): shutil.rmtree(DIST)
    shutil.copytree(STATIC, DIST)
    pages: list[tuple[str, dt.datetime, str]] = []  # (url, lastmod, priority)

    def write(url: str, template: str, lastmod: dt.datetime | None = None, priority="0.5", **ctx):
        out = DIST / url.strip("/") / "index.html" if url != "/" else DIST / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rebase(env.get_template(template).render(**base, url=url, **ctx)), encoding="utf-8")
        if template != "404.html": pages.append((url, lastmod or now, priority))

    latest = episodes[0]
    favs = [e for n in cfg["favourite_episodes"] for e in episodes if e["number"] == n]
    picks = [p for s in cfg["blog_picks"] for p in posts if p["slug"] == s]
    write("/", "index.html", priority="1.0", latest=latest, recent=episodes[1:6], favourites=favs, picks=picks)
    by_year: dict[int, list] = {}
    for e in episodes: by_year.setdefault(e["date"].astimezone(NZ).year, []).append(e)
    write("/podcast/", "podcast.html", latest["date"], "0.9", latest=latest, years=sorted(by_year, reverse=True), by_year=by_year)
    write("/blog/", "blog.html", posts[0]["date"] if posts else None, "0.8")
    for c in cats.values():
        write(f"/category/{c['slug']}/", "category.html", c["posts"][0]["date"], "0.4", cat=c)
    for i, e in enumerate(episodes):
        related = [x for x in (episodes[i - 1:i] + episodes[i + 1:i + 3]) if x is not e][:3]
        write(e["url"], "episode.html", (e["content"] or {}).get("updated") or e["date"], "0.7", e=e, related=related)
    for p in posts:
        cat = p["categories"][0] if p["categories"] else None
        rel = [x for x in posts if x is not p and (cat in x["categories"] if cat else True)][:3]
        write(p["url"], "post.html", p["updated"], "0.6", p=p, related=rel)
    if cfg.get("itinerary_form_embed"):
        write("/south-island-itinerary/", "itinerary.html", priority="0.7")
    write("/quiz/", "quiz.html", priority="0.7")
    for name in ("about", "map", "contact", "privacy", "terms"):
        write(f"/{name}/", f"{name}.html", priority="0.6")
    write("/404/", "404.html")
    (DIST / "404.html").write_text((DIST / "404/index.html").read_text(encoding="utf-8"), encoding="utf-8")
    shutil.rmtree(DIST / "404")

    # sitemap
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u, lm, pr in pages:
        sm.append(f"<url><loc>{cfg['domain']}{u}</loc><lastmod>{lm.date().isoformat()}</lastmod><priority>{pr}</priority></url>")
    sm.append("</urlset>")
    (DIST / "sitemap.xml").write_text("\n".join(sm), encoding="utf-8")

    # blog RSS (articles only; the podcast feed is Captivate's)
    rss = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0"><channel>',
           f"<title>Abigail Hannah blog</title><link>{cfg['domain']}/blog/</link><description>{html.escape(cfg['description'])}</description>"]
    for p in posts[:30]:
        rss.append(f"<item><title>{html.escape(p['title'])}</title><link>{cfg['domain']}{p['url']}</link><guid>{cfg['domain']}{p['url']}</guid>"
                   f"<pubDate>{p['date'].strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate><description>{html.escape(p['description'])}</description></item>")
    rss.append("</channel></rss>")
    (DIST / "rss.xml").write_text("\n".join(rss), encoding="utf-8")

    if BASE: print(f"[base] links rebased under {BASE} (preview build)")
    print(f"built {len(pages)} pages: {len(episodes)} episodes ({numbered} numbered), {len(posts)} articles, {len(cats)} categories -> {DIST}")

if __name__ == "__main__":
    main()
