#!/usr/bin/env python3
"""Verify no broken image references remain after the optimization pass.

Scans all site text files for image references (assets/img/... and bare
frontmatter image: values) and checks that each referenced file exists in
assets/img (or is an external/absolute URL).
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(ROOT, "assets", "img")

refs = {}
for sub in ("_course_26rw", "_course_25rw", "_course_26geschichte",
            "_course_26comm", "_includes", "_layouts", "_data"):
    d = os.path.join(ROOT, sub)
    if not os.path.isdir(d):
        continue
    for dirpath, _, files in os.walk(d):
        for f in files:
            if not f.endswith((".md", ".html", ".yml", ".yaml", ".csv")):
                continue
            p = os.path.join(dirpath, f)
            try:
                text = open(p, encoding="utf-8").read()
            except Exception:
                continue
            # assets/img/NAME references
            for m in re.finditer(r"assets/img/([A-Za-z0-9._\- ]+\.(?:png|jpe?g|gif|webp|mp4))", text):
                refs.setdefault(m.group(1), []).append(os.path.relpath(p, ROOT))
            # bare frontmatter image: NAME (no path)
            for m in re.finditer(r'^\s*(?:image|parallaxBackgroundImage|cover_image|hero):\s*[\'"]?([A-Za-z0-9._\- ]+\.(?:png|jpe?g|gif|webp))[\'"]?\s*$', text, re.M):
                refs.setdefault(m.group(1), []).append(os.path.relpath(p, ROOT))

missing = {k: v for k, v in refs.items() if not os.path.isfile(os.path.join(IMG_DIR, k)) and not k.endswith(".mp4")}
print(f"referenced image files: {len(refs)}")
print(f"MISSING on disk: {len(missing)}")
for k, v in sorted(missing.items()):
    print(f"  MISSING: {k}  (referenced in {', '.join(v[:2])})")
