#!/usr/bin/env python3
"""Check each layout-split slide: which column holds the <img> and the text."""
import re

h = open('_site/26rw/layout-tag-demo-slides.html').read()
# Each layout-split container: capture the full container (text col ... </div>
# image col ... </div> </div>)
pat = re.compile(
    r'<div class="layout-split([^"]*)">\s*<div class="text">(.*?)</div>'
    r'\s*<div class="image">(.*?)</div>\s*</div>', re.S)
for m in pat.finditer(h):
    v = (m.group(1) or '(default)').strip()
    tcol, icol = m.group(2), m.group(3)
    img_in_text = '<img' in tcol
    img_in_image = '<img' in icol
    text_in_text = 'Text auf' in tcol or 'Breite' in tcol or 'Hier steht' in tcol
    text_in_image = 'Text auf' in icol or 'Breite' in icol or 'Hier steht' in icol
    ok = (not img_in_text) and img_in_image and text_in_text and not text_in_image
    print(f"{v:<26} img@text={img_in_text!s:<5} img@image={img_in_image!s:<5} "
          f"txt@text={text_in_text!s:<5} txt@image={text_in_image!s:<5} "
          f"{'OK' if ok else '** BROKEN **'}")
