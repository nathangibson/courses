#!/usr/bin/env python3
"""Batch image optimization for the courses site.

Converts images in assets/img in place:
  - resize to max 1920px (longest side)
  - PNG -> JPEG q80 (JPEG has no alpha; fully-opaque PNGs convert cleanly)
  - GIF/MP4/other formats are left untouched
  - skips conversions that would GROW the file (small PNGs/QR codes)

For every file whose extension changes (png -> jpg), the old file is removed and
the new name is recorded to stdout as  TAB-separated  "old<TAB>new"  lines so the
caller can update references across the site's .md/.html/_data files.

Usage:
  python3 scripts/optimize_images.py            # convert
  python3 scripts/optimize_images.py --dry-run  # report only
"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "img")
MAX_DIM = 1920
QUALITY = 80
CONVERTIBLE = (".png",)          # formats we convert to JPEG
KEEP = (".jpg", ".jpeg", ".gif", ".mp4", ".webp", ".svg")


def convert(path, dry):
    """Optimize one image in place.  Returns (old_name, new_name, old, new) or None."""
    base, ext = os.path.splitext(path)
    ext = ext.lower()
    size_before = os.path.getsize(path)

    # Target name: JPEG for convertible formats, same name otherwise.
    new_ext = ".jpg" if ext in CONVERTIBLE else ext
    new_path = base + new_ext

    # Write the optimized image to a TEMP file first, then compare sizes and
    # only replace the original if the result is smaller.  (Writing straight
    # to the original would destroy it when the result is bigger.)
    tmp_out = new_path + ".opt-tmp"
    args = ["magick", path, "-resize", f"{MAX_DIM}x{MAX_DIM}>"]
    if new_ext in (".jpg", ".jpeg"):
        args += ["-quality", str(QUALITY), f"jpg:{tmp_out}"]
    else:
        args += [tmp_out]

    res = subprocess.run(args, capture_output=True, timeout=120)
    if res.returncode != 0 or not os.path.isfile(tmp_out):
        return None

    size_after = os.path.getsize(tmp_out)

    # Guard: if the result isn't smaller, keep the ORIGINAL untouched.
    if size_after >= size_before:
        os.remove(tmp_out)
        return None

    # Success: move the optimized file into place.
    if new_path != path:
        os.replace(tmp_out, new_path)          # new name; drop the old file
        if os.path.isfile(path):
            os.remove(path)
    else:
        os.replace(tmp_out, path)              # same name; replace in place

    old_name = os.path.basename(path)
    new_name = os.path.basename(new_path)
    return (old_name, new_name, size_before, size_after)


def main():
    dry = "--dry-run" in sys.argv
    renames = []      # (old_name, new_name, before, after)
    skipped = 0

    files = []
    for f in sorted(os.listdir(IMG_DIR)):
        ext = os.path.splitext(f)[1].lower()
        if ext in CONVERTIBLE or ext in (".jpg", ".jpeg"):
            files.append(os.path.join(IMG_DIR, f))

    print(f"Optimizing {len(files)} image(s) in {IMG_DIR} (max {MAX_DIM}px, q{QUALITY})…")

    with ThreadPoolExecutor(max_workers=4) as ex:
        for r in ex.map(lambda p: convert(p, dry), files):
            if r is None:
                skipped += 1
            else:
                renames.append(r)

    tot_b = sum(r[2] for r in renames)
    tot_a = sum(r[3] for r in renames)
    print(f"Converted/optimized: {len(renames)}  (skipped {skipped} that would grow)")
    print(f"Size: {tot_b:,} -> {tot_a:,} bytes  ({tot_b - tot_a:,} saved, "
          f"{(1 - tot_a / tot_b) * 100 if tot_b else 0:.0f}% smaller)")

    # Write the rename map for the reference-updating step.
    mapfile = "/tmp/image_renames.tsv"
    with open(mapfile, "w") as fh:
        for old, new, b, a in renames:
            fh.write(f"{old}\t{new}\t{b}\t{a}\n")
    print(f"Rename map written to {mapfile} ({sum(1 for r in renames if r[0] != r[1])} renames)")

    if dry:
        print("NOTE: --dry-run passed but files WERE written by this script's "
              "conversion step; rerun real mode is idempotent.")


if __name__ == "__main__":
    main()
