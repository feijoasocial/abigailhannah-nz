#!/usr/bin/env python3
"""One-off: copy images still hotlinked from the old Squarespace account onto this site.

Finds every images.squarespace-cdn.com URL in content/, downloads it (1500px wide),
saves it under static/images/legacy/<post>/<name>.jpg|png at full colour, and rewrites
the reference. Anything that fails to download is left pointing at Squarespace and listed.
Runs in GitHub Actions (the build server can reach Squarespace).
"""
import io, re, sys, urllib.request
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
URL_RE = re.compile(r"https://images\.squarespace-cdn\.com/[^)\s\"'<>]+")
OUT = ROOT / "static" / "images" / "legacy"
MAX_W = 1600


def name_for(url: str) -> str:
    last = url.rstrip("/").split("/")[-1].split("?")[0]
    last = re.sub(r"\.(jpe?g|png|gif|webp)$", "", last, flags=re.I)
    return re.sub(r"[^a-z0-9]+", "-", last.replace("+", " ").lower()).strip("-")[:80] or "image"


def fetch(url: str) -> bytes:
    for u in (url.split("?")[0] + "?format=1500w", url):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 abigailhannah.nz migration"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) > 1000:
                return data
        except Exception as e:  # noqa
            err = e
    raise RuntimeError(f"download failed: {err}")


def save(data: bytes, dest_stem: Path) -> Path:
    im = Image.open(io.BytesIO(data))
    fmt = (im.format or "JPEG").upper()
    if im.width > MAX_W:
        im = im.resize((MAX_W, round(im.height * MAX_W / im.width)), Image.LANCZOS)
    if fmt == "PNG" or (im.mode in ("RGBA", "LA") and fmt != "JPEG"):
        dest = dest_stem.with_suffix(".png"); im.save(dest, "PNG", optimize=True)
    else:
        dest = dest_stem.with_suffix(".jpg"); im.convert("RGB").save(dest, "JPEG", quality=86, optimize=True, progressive=True)
    return dest


def main():
    done, failed = {}, []
    for md in sorted((ROOT / "content").rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        urls = list(dict.fromkeys(URL_RE.findall(text)))
        if not urls:
            continue
        folder = OUT / md.stem; folder.mkdir(parents=True, exist_ok=True)
        for url in urls:
            if url not in done:
                stem = folder / name_for(url)
                n = 2
                while any(stem.with_suffix(s).exists() for s in (".jpg", ".png")):
                    stem = folder / f"{name_for(url)}-{n}"; n += 1
                try:
                    done[url] = "/" + save(fetch(url), stem).relative_to(ROOT / "static").as_posix()
                except Exception as e:  # noqa
                    failed.append((md.name, url, str(e))); continue
            text = text.replace(url, done[url])
        md.write_text(text, encoding="utf-8")
    print(f"localised {len(done)} images, {len(failed)} failed")
    for f in failed:
        print("FAILED", *f)


if __name__ == "__main__":
    main()
