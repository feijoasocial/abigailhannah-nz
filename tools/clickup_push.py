#!/usr/bin/env python3
"""Write edited BLOG ARTICLES pages back to ClickUp (used by the clickup-push workflow).

Usage: python tools/clickup_push.py PAYLOAD_DIR STATUS_JSON [ONLY_IDS]

PAYLOAD_DIR holds pages/<page-id>.md (the new content) and manifest.json
({page_id: sha256 of the content Claude pulled}). For each page:
  1. read the page's current content from ClickUp
  2. if it no longer matches the pulled version, skip it (someone edited it since)
  3. otherwise replace the page content, then read it back and record how closely
     the stored version matches what was sent.
Only page ids, statuses and character counts go to STATUS_JSON and the log. No text.
"""
import hashlib, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

WORKSPACE = "36641775"
DOC = "12y6zf-14676"
API = f"https://api.clickup.com/api/v3/workspaces/{WORKSPACE}/docs/{DOC}/pages"


def call(method, url, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": os.environ["CLICKUP_TOKEN"], "Accept": "application/json", "Content-Type": "application/json"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(5 * (attempt + 1)); continue
            return {"_error": e.code, "_body": e.read()[:200].decode("utf-8", "replace")}
    return {"_error": "retries"}


def sha(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()


def main(payload: Path, status_path: Path, only: set, export_dir: Path):
    manifest = json.loads((payload / "manifest.json").read_text(encoding="utf-8"))
    status = []
    for pid, expected in manifest.items():
        if only and pid not in only: continue
        new = (payload / "pages" / f"{pid}.md").read_text(encoding="utf-8")
        cur = call("GET", f"{API}/{pid}?content_format=text/md")
        if "_error" in cur:
            status.append({"id": pid, "status": "read-failed", "code": cur["_error"]}); continue
        if sha(cur.get("content") or "") != expected:
            status.append({"id": pid, "status": "skipped-changed-in-clickup"}); continue
        res = call("PUT", f"{API}/{pid}", {"content": new, "content_format": "text/md", "content_edit_mode": "replace"})
        if "_error" in res:
            status.append({"id": pid, "status": "write-failed", "code": res["_error"], "detail": res.get("_body", "")[:120]}); continue
        back = call("GET", f"{API}/{pid}?content_format=text/md").get("content") or ""
        if export_dir:
            (export_dir / f"{pid}.md").write_text(back, encoding="utf-8")
        norm = lambda s: " ".join(s.split())  # ClickUp re-spaces bullets; compare the words
        status.append({"id": pid, "status": "written", "sent_chars": len(new), "stored_chars": len(back),
                       "identical": back == new, "same_words": norm(back).replace("(http://abigailhannah.nz)", "") .replace("[abigailhannah.nz]", "abigailhannah.nz") == norm(new)})
        time.sleep(0.6)
    status_path.write_text(json.dumps(status, indent=1), encoding="utf-8")
    counts = {}
    for s in status: counts[s["status"]] = counts.get(s["status"], 0) + 1
    print("push result:", counts)


if __name__ == "__main__":
    only = set(filter(None, (sys.argv[3] if len(sys.argv) > 3 else "").split(",")))
    exp = Path(sys.argv[4]) if len(sys.argv) > 4 else None
    if exp: exp.mkdir(parents=True, exist_ok=True)
    main(Path(sys.argv[1]), Path(sys.argv[2]), only, exp)
