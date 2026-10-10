#!/usr/bin/env python3
"""Convert course image attribution.md files into XMP Dublin Core sidecars.

Reads _includes/attributions/{image}-attribution.md and writes
assets/img/{image}.xmp for the images that parse cleanly. Files whose
attribution cannot be reliably split into DC fields are reported for manual
review (human-verified workflow) rather than mis-written.

Field mapping (mirrors the main-site _data/image_credits.yaml via exiftool):
  dc:description -> description   (image/subject description)
  dc:creator     -> creator       (photographer/artist)
  dc:identifier  -> identifier    (museum/collection object id, accession no.)
  dc:publisher   -> publisher     (institution/platform)
  dc:source      -> source_url    (original page URL)
  dc:rights      -> rights        (license note)

Usage:
  python3 scripts/attribution_to_xmp.py            # classify + write XMP for clean
  python3 scripts/attribution_to_xmp.py --dry-run  # classify + report, no writes
  python3 scripts/attribution_to_xmp.py --report   # write messy list to review.md
"""
import os, re, sys, html
from collections import Counter, defaultdict

ATTR_DIR = "_includes/attributions"
IMG_DIR  = "assets/img"
REPORT   = "scripts/attribution_review.md"

DRY = "--dry-run" in sys.argv
WRITE_REPORT = "--report" in sys.argv

def strip_tags(s):
    # unescape -> remove tags -> unescape again (handles double-encoded entities),
    # then collapse whitespace
    for _ in range(2):
        s = html.unescape(s)
        s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def first_link_pairs(body):
    """Return list of (anchor_text, href) for <a href=...>...</a>"""
    out = []
    for m in re.finditer(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
        out.append((strip_tags(m.group(2)).strip(), m.group(1)))
    return out

class XMP:
    def __init__(self):
        self.description = None  # str | None
        self.creator = None      # str | None
        self.identifier = None   # str | None
        self.publisher = None    # str | None
        self.source = None       # str | None
        self.rights = None       # str | None
    def empty(self):
        return not any([self.description, self.creator, self.identifier,
                        self.publisher, self.source, self.rights])
    def fields(self):
        return dict(description=self.description, creator=self.creator,
                    identifier=self.identifier, publisher=self.publisher,
                    source=self.source, rights=self.rights)

def _rdf_alt(field, value):
    return (f"   <dc:{field}>\n"
            f"    <rdf:Alt>\n"
            f"     <rdf:li xml:lang=\"x-default\">{value}</rdf:li>\n"
            f"    </rdf:Alt>\n"
            f"   </dc:{field}>\n")

def _rdf_bag(field, value):
    return (f"   <dc:{field}>\n"
            f"    <rdf:Bag>\n"
            f"     <rdf:li>{value}</rdf:li>\n"
            f"    </rdf:Bag>\n"
            f"   </dc:{field}>\n")

def write_xmp(img_path, x: XMP):
    """Write a minimal .xmp sidecar for image img_path using DC fields."""
    base = os.path.basename(img_path)
    xmp_path = img_path + ".xmp"
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 5.0.0">\n'
    xml += ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
    xml += '  <rdf:Description rdf:about=""\n'
    xml += '    xmlns:dc="http://purl.org/dc/elements/1.1/"'
    if x.source:
        # escape attribute
        xml += f'\n   dc:source="{x.source.replace(chr(34), "&quot;")}"'
    if x.identifier:
        xml += f'\n   dc:identifier="{x.identifier.replace(chr(34), "&quot;")}"'
    xml += '>\n'
    if x.description:
        xml += _rdf_alt("description", x.description)
    if x.creator:
        xml += _rdf_bag("creator", x.creator)
    if x.publisher:
        xml += _rdf_bag("publisher", x.publisher)
    if x.rights:
        xml += _rdf_alt("rights", x.rights)
    xml += '  </rdf:Description>\n'
    xml += ' </rdf:RDF>\n'
    xml += '</x:xmpmeta>\n'
    with open(xmp_path, "w", encoding="utf-8") as fh:
        fh.write(xml)

def parse_attribution(text):
    """Return (xmp, kind, note) where kind in pixabay|unsplash|wikimedia|bm|clean|MESSY."""
    body = text.strip()
    x = XMP()
    links = first_link_pairs(body)
    ltext = strip_tags(body)

    # --- Pixabay: "Image by <a>Creator</a> from <a>Pixabay</a>" ---
    if "pixabay.com" in body and re.search(r"image by", body, re.I):
        x.publisher = "Pixabay"
        for t, h in links:
            if "users/" in h and "picture" not in h:
                x.creator = t or None
                # source = the photographer's profile page (cleaner source URL)
                x.source = x.source or h.split("?")[0]
        x.rights = x.rights or "Pixabay Content License"
        return (x, "pixabay", None)

    # --- Unsplash: "[desc]. Photo by <a>Creator</a> on <a>Unsplash</a>." ---
    if "unsplash.com" in body:
        # description = text before "Photo by"/"photo by"
        m = re.split(r"\s*[Pp]hoto by\s*", ltext)
        if len(m) > 1:
            before = m[0].strip(" .")
            x.description = before or None
        for t, h in links:
            if "unsplash.com" not in h:
                x.creator = t or None
            if "unsplash.com" in h and x.source is None:
                x.source = h.split("?")[0]
        x.publisher = "Unsplash"
        x.rights = x.rights or "Unsplash License"
        return (x, "unsplash", None)

    # --- Wikimedia/Commons ---
    if "wikimedia" in body.lower() or "commons" in body.lower() or "wikipedia" in body.lower():
        # title/desc from first link text, rights from license phrase, publisher/source
        if links:
            x.description = links[0][0] or None
            x.source = links[0][1] or None
        rm = re.search(r"(Public domain|CC BY[^,]*|Creative Commons[^,]*|CC0)", ltext, re.I)
        if rm:
            x.rights = rm.group(1).strip()
        if re.search(r"via\s+Wikimedia\s+Commons", ltext, re.I):
            x.publisher = "Wikimedia Commons"
        return (x, "wikimedia", None)

    # --- British Museum / 'Trustees' pattern ---
    if "trustees of the" in ltext.lower() or "british museum" in ltext.lower():
        m = re.search(r"\(c\)\s*([^)]+)", ltext, re.I)
        if m:
            x.publisher = m.group(1).strip()
        # accession/identifier: pattern like "no. 123,345.6"
        am = re.search(r"no\.?\s*([0-9][0-9,\s.]*)", ltext, re.I)
        if am:
            x.identifier = am.group(1).strip()
        # source URL from angle-bracket URLs http://... or https://...
        um = re.search(r"<((?:https?://)[^>]+)>", body)
        if not um:
            um = re.search(r"((?:https?://)[^\s<>,;)\"]+)", body)
        if um:
            x.source = um.group(1).strip(".,")
        rm = re.search(r"(CC BY[^,.;]*|Public Domain)", ltext, re.I)
        if rm:
            x.rights = rm.group(1).strip()
        # description = text before "image (c)"
        dm = re.split(r"image\s*\(c\)", ltext, flags=re.I)
        if len(dm) > 1 and dm[0].strip():
            x.description = dm[0].strip(" ,.")
        return (x, "bm", None)

    # --- Generic "... attributed to ..." / "From ..." with author ---
    m = re.search(r"[\w\s,]+", ltext)
    # Try: "By Author" or "Photo: Author"
    am = re.match(r"\s*(?:by|photo[:\s]+|credit[:\s]+|©)\s*([A-Za-z][\w\s.'-]{1,60}?)(?:\s*-\s*|,|\s*\(|$)", ltext, re.I)
    if am:
        x.creator = am.group(1).strip()

    return (x, "clean", None)

def classify(counter, images, attrs):
    kinds = Counter()
    messy = []
    clean_good = []
    for img in sorted(images):
        if img not in attrs:
            continue
        x, kind, note = parse_attribution(attrs[img])
        kinds[kind] += 1
        if kind == "MESSY":
            messy.append(img)
        elif not x.empty():
            clean_good.append(img)
    return kinds, messy, clean_good

def main():
    if not os.path.isdir(ATTR_DIR):
        print("No attributions dir", ATTR_DIR); return
    attrs = {}
    for f in os.listdir(ATTR_DIR):
        if f.endswith("-attribution.md"):
            img = f[: -len("-attribution.md")]
            attrs[img] = open(os.path.join(ATTR_DIR, f), encoding="utf-8").read()
    images = sorted(attrs.keys())
    kinds = Counter()
    for img in images:
        x, kind, _ = parse_attribution(attrs[img])
        kinds[kind] += 1
    # good = confidently classified (structured fields) OR messy (raw desc fallback)
    good = []
    review_only = []
    CONFIDENT = {"pixabay", "unsplash", "wikimedia", "bm"}
    for img in images:
        x, kind, _ = parse_attribution(attrs[img])
        if kind in CONFIDENT and not x.empty():
            good.append((img, x, "structured"))
        else:
            # messy: sidecar created with raw attribution text in dc:description
            x.description = strip_tags(attrs[img]) or None
            good.append((img, x, "description-only"))
            review_only.append(img)
    print(f"Total attribution files: {len(images)}")
    print("Classification:", dict(kinds))
    print(f"Sidecar files to write: {len(good)}  (structured: {len(good) - len(review_only)} | description-only: {len(review_only)})")
    if DRY:
        print("\n[DRY RUN] no XMP written.")
    else:
        os.makedirs(IMG_DIR, exist_ok=True)
        n = 0
        for img, x, _tag in good:
            write_xmp(os.path.join(IMG_DIR, img), x)
            n += 1
        print(f"Wrote {n} .xmp sidecar files to {IMG_DIR}/")
    if WRITE_REPORT or DRY:
        with open(REPORT, "w") as fh:
            fh.write("# Attribution review (auto-generated)\n\n")
            fh.write(f"Total: {len(images)} | structured: {len(good) - len(review_only)} | description-only (needs review): {len(review_only)}\n\n")
            fh.write("## Description-only XMP (raw attribution in dc:description — needs cleaning)\n")
            fh.write(f"   {len(review_only)} files; fill in creator/publisher/source/rights later.\n")
            for img in review_only:
                fh.write(f"- {img}\n")
            fh.write("\n## Structured XMP (confidently parsed)\n")
            fh.write("   Pixabay / Unsplash / Wikimedia / British Museum\n")
            for img, x, tag in good:
                if tag == "structured":
                    fh.write(f"- {img}\n")
        print(f"Wrote report: {REPORT}")

if __name__ == "__main__":
    main()
