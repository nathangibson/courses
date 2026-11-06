#!/usr/bin/env python3
"""Update all references to renamed/converted images across the courses site.

Reads the rename map (/tmp/image_renames.tsv:  old<TAB>new<TAB>before<TAB>after)
and rewrites references in:
  - _course_*/*.md          (markdown image links, frontmatter image: /
                             parallaxBackgroundImage:)
  - index.html, _includes/*.html, _layouts/*.html   (src=..., background-image)
  - _data/image_credits.yaml (credit keys are image basenames)
Also renames .xmp sidecar files (assets/img/<old>.xmp -> <new>.xmp) and the
per-image attribution markdown files (_includes/attributions/<old>-attribution.md).

Usage: python3 scripts/update_image_refs.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPFILE = "/tmp/image_renames.tsv"


def load_map():
    """Return dict old_name -> new_name (only true renames, png->jpg)."""
    renames = {}
    with open(MAPFILE) as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[0] != parts[1]:
                renames[parts[0]] = parts[1]
    return renames


def text_files():
    """Yield every text file in the site that may reference images."""
    for sub in ("_course_26rw", "_course_25rw", "_course_26geschichte",
                "_course_26comm", "_includes", "_layouts", "_data"):
        d = os.path.join(ROOT, sub)
        if not os.path.isdir(d):
            continue
        for dirpath, _, files in os.walk(d):
            for f in files:
                if f.endswith((".md", ".html", ".yml", ".yaml", ".csv")):
                    yield os.path.join(dirpath, f)
    top = os.path.join(ROOT, "index.html")
    if os.path.isfile(top):
        yield top


def main():
    renames = load_map()
    if not renames:
        print("No renames in map; nothing to do.")
        return
    print(f"{len(renames)} image rename(s) to apply")

    changed = 0
    for path in text_files():
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, IsADirectoryError):
            continue

        new_text = text
        n = 0
        for old, new in renames.items():
            # Replace every occurrence of the old basename (with extension) in
            # any context: assets/img/old, image: old, old-attribution, etc.
            if old in new_text:
                n += new_text.count(old)
                new_text = new_text.replace(old, new)

        if n:
            open(path, "w", encoding="utf-8").write(new_text)
            changed += 1
            print(f"  {n:3d} ref(s): {os.path.relpath(path, ROOT)}")

    print(f"Updated references in {changed} file(s)")

    # Rename sidecar/attribution files that are named after the images.
    img_dir = os.path.join(ROOT, "assets", "img")
    attr_dir = os.path.join(ROOT, "_includes", "attributions")
    for old, new in renames.items():
        for base_dir, suffix in ((img_dir, ".xmp"), (attr_dir, "-attribution.md")):
            src = os.path.join(base_dir, old + suffix)
            dst = os.path.join(base_dir, new + suffix)
            if os.path.isfile(src) and not os.path.isfile(dst):
                os.rename(src, dst)
                print(f"  sidecar: {old + suffix} -> {new + suffix}")


if __name__ == "__main__":
    main()
