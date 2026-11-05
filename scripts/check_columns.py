#!/usr/bin/env python3
"""Report which column each layout-split slide's image landed in."""
import re
h = open('_site/26rw/layout-tag-demo-slides.html').read()
for m in re.finditer(r'<div class="layout-split([^"]*)">(.*?)</div>\s*</div>', h, re.S):
    variant = (m.group(1) or '(default)').strip()
    seg = m.group(2)
    before_img, _, after_img = seg.partition('<img')
    # which column contains the <img>?
    col = 'text' if 'class="text"' in before_img.split('class="image"')[0] else 'image'
    text_present = ('Text auf' in seg or 'Breite Textspalte' in seg
                    or 'Hier steht' in seg)
    print(f'{variant:<28} img_col={col:<6} text_in_other_col={text_present}')
