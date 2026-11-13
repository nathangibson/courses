#!/usr/bin/env python3
"""Debug the pattern construction."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_image_refs import load_map

renames = load_map()
names = list(renames.keys())
print("ba-beratung.png in names:", "ba-beratung.png" in names)

# single-name pattern test
p1 = re.escape("ba-beratung.png")
print("single pattern:", p1)
print("single matches:", re.findall(p1, "![alt](/courses/assets/img/ba-beratung.png)"))

# build the full pattern and inspect a slice around ba-beratung
full = "|".join(re.escape(os.path.splitext(o)[0]) + r"\." + re.escape(os.path.splitext(o)[1])
                for o in names)
i = full.find("ba-beratung")
print("pattern length:", len(full))
print("pattern slice:", full[max(0,i-60):i+60] if i >= 0 else "ba-beratung NOT IN PATTERN")
