#!/usr/bin/env python3
"""Debug why update_image_refs didn't update references."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_image_refs import load_map, text_files

renames = load_map()
print("map size:", len(renames))
print("sample map entries:", list(renames.items())[:3])

pat = re.compile(
    "|".join(re.escape(os.path.splitext(o)[0]) + r"\." + re.escape(os.path.splitext(o)[1])
             for o in renames)
)
test = "![alt](/courses/assets/img/ba-beratung.png)"
print("pattern matches test string:", pat.findall(test))

# check a file known to reference ba-beratung.png
p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "_course_26rw", "2026-11-23-7-slides.md")
print("file exists:", os.path.isfile(p))
t = open(p, encoding="utf-8").read()
print("ba-beratung in file:", "ba-beratung" in t)
print("pattern matches in file:", pat.findall(t)[:3])
