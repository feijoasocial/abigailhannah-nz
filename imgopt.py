"""Responsive images for the built site (run by build.py after every page is written).

For each local JPEG or PNG used in an <img> tag, make full-colour WebP copies at a few widths and
give the tag a srcset, so phones download a small file and desktops a sharp one. The original stays
as the fallback src. Copies are cached in imgcache/ (kept between builds by the workflow's cache),
named by a hash of the source file, so a build only encodes images that are new or changed, and a
changed photo gets a fresh address.

Also: every image gets width and height (no layout shift), and loading is set so the first image on
a page loads straight away (it is usually the largest thing on screen) and the rest wait until
they are scrolled near. Video posters switch to a WebP copy too. Never palette-reduces anything.
"""
import hashlib
import re
import shutil
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).parent
CACHE = ROOT / "imgcache"
WIDTHS = (480, 960, 1600)
MAX_W = 1600   # widest copy; 1920 is added only for full-screen photos that are at least that wide
QUALITY = 82

IMG_RE = re.compile(r"<img\b[^>]*>", re.I)
PROSE_RE = re.compile(r'<div class="prose">.*?</div>\s*(?:<div class="tags"|</div>)', re.S)
POSTER_RE = re.compile(r'poster="([^"]+\.(?:jpe?g|png))"', re.I)
ATTR = lambda name: re.compile(r'\s' + name + r'="([^"]*)"', re.I)
SRC, CLS, WID, HEI, LOAD, PRIO = (ATTR(n) for n in ("src", "class", "width", "height", "loading", "fetchpriority"))

# how wide each kind of image shows on screen, so the browser picks the right copy
SIZES = {
    "hero-img": "100vw",
    "hero-art": "(max-width: 760px) 100vw, 720px",
    "side-photo": "300px",
    "ap-art": "120px",
    "thumb": "(max-width: 560px) 100vw, (max-width: 1040px) 50vw, 380px",
    "portrait": "(max-width: 760px) 100vw, 560px",
    "phone-still": "300px",
    "iphone-frame": "320px",
}
PROSE_SIZES = "(max-width: 760px) 100vw, 720px"


class Optimiser:
    def __init__(self, dist: Path, base: str = ""):
        self.dist, self.base = dist, base
        self.made = self.reused = 0
        self.info: dict[str, dict | None] = {}

    def _local(self, src: str) -> Path | None:
        if self.base and src.startswith(self.base + "/"):
            src = src[len(self.base):]
        if not src.startswith("/") or src.startswith("//"):
            return None
        f = self.dist / src.lstrip("/").split("?")[0].split("#")[0]
        return f if f.suffix.lower() in (".jpg", ".jpeg", ".png") and f.is_file() else None

    def variants(self, src: str) -> dict | None:
        """{'w': width, 'h': height, 'set': [(url, width), ...]} for a local image, or None."""
        if src in self.info:
            return self.info[src]
        f = self._local(src)
        if not f:
            self.info[src] = None
            return None
        digest = hashlib.sha1(f.read_bytes()).hexdigest()[:10]
        rel = f.relative_to(self.dist).with_suffix("")
        try:
            with Image.open(f) as im:
                im = ImageOps.exif_transpose(im)
                W, H = im.size
                widths = sorted({w for w in WIDTHS if w < W * 0.9} | {min(W, MAX_W)} | ({1920} if W >= 1900 else set()))
                out = []
                for w in widths:
                    name = f"{rel.as_posix()}.{digest}.{w}.webp"
                    cached = CACHE / name
                    if not cached.exists():
                        cached.parent.mkdir(parents=True, exist_ok=True)
                        frame = im if w == W else im.resize((w, round(H * w / W)), Image.LANCZOS)
                        if frame.mode not in ("RGB", "RGBA"):
                            frame = frame.convert("RGBA" if "A" in frame.getbands() or frame.mode == "P" else "RGB")
                        kw = {"quality": QUALITY, "method": 5}
                        if im.info.get("icc_profile"):
                            kw["icc_profile"] = im.info["icc_profile"]
                        frame.save(cached, "WEBP", **kw)
                        self.made += 1
                    else:
                        self.reused += 1
                    target = self.dist / "_img" / name
                    if not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(cached, target)
                    out.append((f"{self.base}/_img/{name}", w))
        except Exception as e:  # a broken image keeps its original tag
            print(f"[images] skipped {src}: {e}")
            self.info[src] = None
            return None
        self.info[src] = {"w": W, "h": H, "set": out}
        return self.info[src]

    def tag(self, tag: str, in_prose: bool, first: bool) -> str:
        m = SRC.search(tag)
        if not m or "srcset=" in tag:
            return tag
        v = self.variants(m.group(1))
        add = []
        if v:
            if not WID.search(tag) and not HEI.search(tag):
                add.append(f'width="{v["w"]}" height="{v["h"]}"')
            cls = (CLS.search(tag).group(1).split() if CLS.search(tag) else [])
            sizes = next((SIZES[c] for c in cls if c in SIZES), None)
            if not sizes:
                if in_prose:
                    sizes = PROSE_SIZES
                else:
                    w = int(WID.search(tag).group(1)) if WID.search(tag) else v["w"]
                    sizes = "100vw" if w >= 1200 else f"(max-width: {w}px) 100vw, {w}px"
            srcset = ", ".join(f"{u} {w}w" for u, w in v["set"])
            add.append(f'srcset="{srcset}" sizes="{sizes}"')
        if not LOAD.search(tag) and not PRIO.search(tag):
            add.append('fetchpriority="high"' if first else 'loading="lazy"')
        if "decoding=" not in tag:
            add.append('decoding="async"')
        end = "/>" if tag.endswith("/>") else ">"
        return tag[: -len(end)].rstrip() + " " + " ".join(add) + end

    def page(self, html: str) -> str:
        prose = [(m.start(), m.end()) for m in PROSE_RE.finditer(html)]
        main_at = html.find('<main')
        state = {"first": True}

        def one(m):
            pos = m.start()
            in_prose = any(a <= pos < b for a, b in prose)
            tag = m.group(0)
            # the first image in <main> with no loading hint is treated as the main image
            first = pos > main_at >= 0 and state["first"] and not LOAD.search(tag) and not PRIO.search(tag)
            if pos > main_at >= 0 and not LOAD.search(tag):
                state["first"] = False
            return self.tag(tag, in_prose, first)

        html = IMG_RE.sub(one, html)

        def poster(m):
            v = self.variants(m.group(1))
            if not v:
                return m.group(0)
            best = next((u for u, w in v["set"] if w >= 1280), v["set"][-1][0])
            return f'poster="{best}"'

        return POSTER_RE.sub(poster, html)

    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        import os
        pages = [p for p in self.dist.rglob("*.html")]
        # encode every image once up front, in parallel (Pillow releases the lock while encoding)
        srcs = set()
        for p in pages:
            t = p.read_text(encoding="utf-8")
            srcs.update(m.group(1) for m in SRC.finditer(" ".join(IMG_RE.findall(t))))
            srcs.update(POSTER_RE.findall(t))
        with ThreadPoolExecutor(max_workers=max(2, os.cpu_count() or 2)) as ex:
            list(ex.map(self.variants, sorted(srcs)))
        for p in pages:
            t = p.read_text(encoding="utf-8")
            if "<img" not in t and "poster=" not in t:
                continue
            n = self.page(t)
            if n != t:
                p.write_text(n, encoding="utf-8")
        print(f"[images] {len(pages)} pages, {self.made} WebP copies made, {self.reused} reused from imgcache/")
