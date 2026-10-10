#!/usr/bin/env python3
"""Backfill 25rw session + slide frontmatter from sessions.csv (no PyYAML).

Moves genuinely-unique per-session data (unit, long-topic, image, zotero-tag,
zotero-readings, objective) into the front matter of _course_25rw/ session docs
and their -slides decks. Does NOT write derived fields (title, pad-slug) — those
are computed by _includes/session-meta.html via Liquid.

Front matter is edited textually (key: value lines) so we don't depend on
PyYAML and we preserve the existing block/flow formatting.
"""
import csv
import os
import re

BASE = "/Users/nathan/git/Github/nathangibson/courses-liquid/_course_25rw"
CSV = "/Users/nathan/git/Github/nathangibson/courses-liquid/_data/course_25rw/sessions.csv"

YAML_HEAD = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

def yaml_scalar(v):
    """Quote a value if needed for a YAML scalar."""
    v = v.strip()
    if v == "":
        return '""'
    # handle values that start with special chars or contain colons/quotes
    if re.match(r"^[\s\-\?:,\[\]{}#&*!|>'\"]", v) or ":" in v or '"' in v:
        return '"' + v.replace('"', '\\"') + '"'
    return v

def load(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = YAML_HEAD.match(text)
    body = text[m.end():] if m else ""
    return m.group(1) if m else "", body

def set_fields(fm_text, fields):
    """Return fm_text with `fields` set (insert/replace named keys), preserving order."""
    lines = []
    seen = set()
    if fm_text.strip():
        lines = fm_text.split("\n")
    # remove existing occurrences of target keys
    kept = []
    for ln in lines:
        key = ln.split(":", 1)[0].strip() if ":" in ln else ""
        if key in fields:
            seen.add(key)
            continue
        kept.append(ln)
    # append/overwrite at end
    for k, v in fields.items():
        kept.append(f"{k}: {yaml_scalar(v)}")
    return "\n".join(kept)

def write(path, fm_text, body):
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n" + fm_text + "\n---\n" + body)

def main():
    with open(CSV, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("session", "").strip()]

    for r in rows:
        fn = r.get("filename", "").strip()
        if not fn or not fn.endswith(".md"):
            continue
        slide_fn = fn[:-3] + "-slides.md"

        post_fields = {
            "unit": r.get("unit", "").strip(),
            "long-topic": r.get("long-topic", "").strip(),
            "image": r.get("image", "").strip(),
            "zotero-tag": r.get("zotero-tag", "").strip(),
            "zotero-readings": r.get("zotero-readings", "").strip(),
            "objective": r.get("objective", "").strip(),
        }
        slide_fields = {
            "zotero-tag": r.get("zotero-tag", "").strip(),
            "zotero-readings": r.get("zotero-readings", "").strip(),
        }

        p = os.path.join(BASE, fn)
        if os.path.exists(p):
            fm, body = load(p)
            write(p, set_fields(fm, post_fields), body)
            print(f"POST  {fn}")
        else:
            print(f"!! missing post {fn}")

        s = os.path.join(BASE, slide_fn)
        if os.path.exists(s):
            fm, body = load(s)
            write(s, set_fields(fm, slide_fields), body)
            print(f"SLIDE {slide_fn}")
        else:
            print(f"!! missing slide {slide_fn}")

    print("done")

if __name__ == "__main__":
    main()
