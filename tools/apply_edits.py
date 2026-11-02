#!/usr/bin/env python3
"""Apply proofreading edits (JSON from the proofreaders) to copies of the ClickUp pages.

Usage: python tools/apply_edits.py EDITS.json [...] --out OUT_DIR
Each edit's `find` must occur exactly once, before the private Notes section.
Pages are copied to OUT_DIR untouched apart from the accepted edits; rejected
edits are reported and not applied (the page is still published without them).
"""
import json, re, sys
from pathlib import Path

NOTES = re.compile(r"^#+\s*\S*\s*Notes for Abigail", re.M)
DASHES = ("—", "–")


def main(files, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    report, rejected = [], []
    for f in files:
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        for pg in data["pages"]:
            src = Path(pg["page"]); text = src.read_text(encoding="utf-8")
            m = NOTES.search(text); cut = m.start() if m else len(text)
            applied = []
            for e in pg.get("edits", []):
                find, rep = e["find"], e.get("replace", "")
                why = None
                if text.count(find) != 1: why = f"found {text.count(find)} times"
                elif text.index(find) >= cut: why = "inside the private notes"
                elif any(d in rep for d in DASHES): why = "replacement adds a dash"
                elif re.search(r"^#{1,6} |^```", find, re.M): why = "touches a heading or the front matter"
                if why:
                    rejected.append((pg["name"], e.get("type"), why, find[:90])); continue
                text = text.replace(find, rep, 1)
                cut = (NOTES.search(text).start() if NOTES.search(text) else len(text))
                applied.append(e)
            text = re.sub(r"[ \t]{2,}(?=\S)", " ", text[:cut]) + text[cut:]  # tidy double spaces left by deletions
            text = re.sub(r"\n{3,}", "\n\n", text[:cut]) + text[cut:]
            (out / src.name).write_text(text, encoding="utf-8")
            report.append({"name": pg["name"], "page": src.name, "applied": applied,
                           "summary": pg.get("summary", ""), "link_notes": pg.get("link_notes", []),
                           "verified": pg.get("verified", [])})
    (out / "_report.json").write_text(json.dumps({"pages": report, "rejected": rejected}, indent=1, ensure_ascii=False), encoding="utf-8")
    n = sum(len(r["applied"]) for r in report)
    print(f"{len(report)} pages, {n} edits applied, {len(rejected)} rejected")
    for r in rejected: print("REJECTED", *r)


if __name__ == "__main__":
    args = sys.argv[1:]; i = args.index("--out")
    main(args[:i], Path(args[i + 1]))
