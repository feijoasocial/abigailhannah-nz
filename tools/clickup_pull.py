#!/usr/bin/env python3
"""Read every page of the ClickUp BLOG ARTICLES doc, exactly as written (read-only).

Usage (in GitHub Actions, with the CLICKUP_TOKEN secret in the environment):
    python tools/clickup_pull.py OUT_DIR

Writes OUT_DIR/<page-id>.md (the page's markdown) and OUT_DIR/index.json
(id, name, parent, updated) for every page. Never writes to ClickUp.
The raw pages include the private "Notes for Abigail" sections, so the workflow
encrypts OUT_DIR before saving it anywhere (the repo is public).
"""
import json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

WORKSPACE = "36641775"
DOC = "12y6zf-14676"
API = f"https://api.clickup.com/api/v3/workspaces/{WORKSPACE}/docs/{DOC}"


def get(url: str):
    req = urllib.request.Request(url, headers={"Authorization": os.environ["CLICKUP_TOKEN"], "Accept": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(5 * (attempt + 1)); continue
            raise SystemExit(f"ClickUp API {e.code} on {url.split('?')[0]}: {e.read()[:300]!r}")
    raise SystemExit("ClickUp API kept failing")


def walk(pages, parent=None):
    for p in pages or []:
        yield p, parent
        yield from walk(p.get("pages"), p.get("id"))


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    listing = get(f"{API}/pageListing?max_page_depth=-1")
    pages = listing if isinstance(listing, list) else listing.get("pages", listing)
    index = []
    for meta, parent in walk(pages):
        pid = meta["id"]
        page = get(f"{API}/pages/{pid}?content_format=text/md")
        content = page.get("content") or ""
        (out / f"{pid}.md").write_text(content, encoding="utf-8")
        index.append({"id": pid, "name": page.get("name") or meta.get("name"), "parent": parent,
                      "updated": page.get("date_updated") or meta.get("date_updated"), "chars": len(content)})
        time.sleep(0.4)  # stay well inside the rate limit
    (out / "index.json").write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"pulled {len(index)} pages")  # counts only: page text never goes in the public log


if __name__ == "__main__":
    main(Path(sys.argv[1]))
