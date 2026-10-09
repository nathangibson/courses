#!/usr/bin/env python3
"""Dry-run analysis: consolidate course images + attributions from jirelations.

- Images: every course assets/img -> target assets/img, dedup by filename, newest course wins.
  Newest = highest course year prefix (25 > 24 > 23). Within same year, tie-break by mtime.
- Attributions: every course _posts/*-attribution.md -> target _includes/attributions/,
  dedup by basename (image name), newest course wins.
Prints a plan; does NOT write in dry-run mode.
"""
import os, re, sys, shutil
from collections import defaultdict

JIREL = "/Users/nathan/git/Github/jirelations"
TGT_IMG = "/Users/nathan/git/Github/courses/assets/img"
TGT_ATTR = "/Users/nathan/git/Github/courses/_includes/attributions"
DRY = "--dry" in sys.argv
JUNK = {".DS_Store", ".gitattributes"}

def course_rank(name):
    """Higher = newer. 25xx > 24xx > 23xx."""
    m = re.match(r"(\d\d)([a-z].*)", name)
    if not m: return (0, name)
    return (int(m.group(1)), name)

def attribution_basename(filename):
    """Return the image basename an attribution file names, or None if not an attribution.
    Handles both `{image}-attribution.md` and `{image}-attribution.md.txt`."""
    if filename.endswith("-attribution.md.txt"):
        return filename[: -len("-attribution.md.txt")]
    if filename.endswith("-attribution.md"):
        return filename[: -len("-attribution.md")]
    return None

def collect():
    courses = [d for d in os.listdir(JIREL) if os.path.isdir(os.path.join(JIREL,d)) and re.match(r"\d\d", d)]
    courses.sort(key=course_rank)
    img_by_name = {}   # name -> (rank, srcpath)
    attr_by_name = {}  # image basename -> (rank, srcpath)
    for c in courses:
        rank = course_rank(c)
        imgdir = os.path.join(JIREL, c, "assets", "img")
        if os.path.isdir(imgdir):
            for f in os.listdir(imgdir):
                if f in JUNK: continue
                src = os.path.join(imgdir, f)
                if not os.path.isfile(src): continue
                cur = img_by_name.get(f)
                if cur is None or rank > cur[0]:
                    img_by_name[f] = (rank, src)
        # attributions can live in _posts, pages, and assets/img
        for d in ("_posts", "pages"):
            p = os.path.join(JIREL, c, d)
            if os.path.isdir(p):
                for f in os.listdir(p):
                    base = attribution_basename(f)
                    if not base: continue
                    src = os.path.join(p, f)
                    if not os.path.isfile(src): continue
                    cur = attr_by_name.get(base)
                    if cur is None or rank > cur[0]:
                        attr_by_name[base] = (rank, src)
        # also scan assets/img for {image}-attribution.md[.txt]
        if os.path.isdir(imgdir):
            for f in os.listdir(imgdir):
                base = attribution_basename(f)
                if not base: continue
                src = os.path.join(imgdir, f)
                if not os.path.isfile(src): continue
                cur = attr_by_name.get(base)
                if cur is None or rank > cur[0]:
                    attr_by_name[base] = (rank, src)
    return courses, img_by_name, attr_by_name

def main():
    courses, img, attr = collect()
    raw_imgs = 0
    for c in courses:
        d = os.path.join(JIREL, c, "assets", "img")
        if os.path.isdir(d):
            raw_imgs += len([f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))])
    print(f"Courses scanned: {len(courses)}")
    print(f"Unique images to copy (dedup'd 25>24>23): {len(img)}")
    print(f"Total raw image instances across courses: {raw_imgs}")
    print(f"Unique attributions to copy (dedup'd): {len(attr)}")
    if DRY:
        print("\n[DRY RUN] Nothing written.")
        return
    os.makedirs(TGT_IMG, exist_ok=True)
    os.makedirs(TGT_ATTR, exist_ok=True)
    n_i = n_a = 0
    for name, (rank, src) in sorted(img.items()):
        if name in JUNK: continue
        shutil.copy2(src, os.path.join(TGT_IMG, name)); n_i += 1
    for base, (rank, src) in sorted(attr.items()):
        # normalize output name to {image}-attribution.md (source may be .md or .md.txt)
        out = base + "-attribution.md"
        shutil.copy2(src, os.path.join(TGT_ATTR, out)); n_a += 1
    print(f"Copied {n_i} images, {n_a} attributions.")
    print(f"Image extensions: {sorted(set(os.path.splitext(n)[1] for n in img if n not in JUNK))}")

if __name__=="__main__":
    main()
