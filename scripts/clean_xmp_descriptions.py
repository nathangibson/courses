#!/usr/bin/env python3
"""Remove /Users/nathan/Github/jirelations/.* (or /Users/nathan/.../jirelations/...)
path junk from dc:description in .xmp sidecars. If the description is only the
path, drop the whole dc:description element. Files are otherwise left as-is.
"""
import os, re, glob

PATHS = re.compile(
    r"/Users/nathan/(?:Github|github|git|GitHub|Git)/jirelations[^\"]*"
)

def clean(xmp):
    text = open(xmp, encoding="utf-8").read()
    changed = False
    # Remove entire dc:description element when its rdf:li matches an absolute jirelations path
    def drop_desc(m):
        nonlocal changed
        inner = m.group(0)
        # only drop if the description value is a bare path (starts with /Users/nathan and contains jirelations)
        li = re.search(r'<rdf:li[^>]*>(.*?)</rdf:li>', inner, re.S)
        if li and li.group(1).strip().startswith("/Users/nathan") and "jirelations" in li.group(1):
            changed = True
            return ""
        return inner
    out = re.sub(r"<dc:description>\s*<rdf:Alt>.*?</rdf:Alt>\s*</dc:description>",
                 drop_desc, text, flags=re.S)
    # Also strip path text from any remaining description value
    if not changed:
        new_text = PATHS.sub("", out)
        if new_text != out:
            changed = True
        out = new_text
    if changed:
        open(xmp, "w", encoding="utf-8").write(out)
        return True
    return False

if __name__ == "__main__":
    n = 0
    for xmp in glob.glob("assets/img/*.xmp"):
        if clean(xmp):
            print("cleaned:", xmp)
            n += 1
    print(f"--- cleaned {n} files ---")
