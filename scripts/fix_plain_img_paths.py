#!/usr/bin/env python3
"""Fix plain assets/img/... srcs in course slides to ../assets/img/... and
update stale extensions to files that actually exist on disk."""
import os, re

ROOT = "/Users/nathan/git/Github/nathangibson/courses"
IMG_DIR = os.path.join(ROOT, "assets", "img")
files = []
for c in os.listdir(os.path.join(ROOT)):
    if c.startswith("_course_") and os.path.isdir(os.path.join(ROOT, c)):
        for f in os.listdir(os.path.join(ROOT, c)):
            if f.endswith(".md"):
                files.append(os.path.join(ROOT, c, f))

pat = re.compile(r"(images=')((?:assets/img/|\.\./assets/img/)?[A-Za-z0-9._\- ]+?)(')")
changed = 0
for p in files:
    text = open(p, encoding="utf-8").read()
    orig = text
    def fix(m):
        global changed
        names = m.group(2)
        out_names = []
        for part in names.split("; "):
            part = part.strip()
            base = part.split("/")[-1]
            if not os.path.isfile(os.path.join(IMG_DIR, base)):
                # try other extensions for the same basename
                stem = os.path.splitext(base)[0]
                found = [f for f in os.listdir(IMG_DIR)
                         if os.path.splitext(f)[0] == stem and f != base]
                if found:
                    base = found[0]
            out_names.append("../assets/img/" + base)
        return m.group(1) + "; ".join(out_names) + m.group(3)
    text = pat.sub(fix, text)
    if text != orig:
        open(p, "w", encoding="utf-8").write(text)
        changed += 1
        print("fixed:", os.path.relpath(p, ROOT))
print(f"--- {changed} file(s) fixed ---")
