---
layout: reveal
title: 'Slide Layout Class Examples'
author: 'Nathan Gibson'
category: slides
---

# Slide layout classes

Examples of the `.layout-split` media layouts for reveal.js slides.

## 1. Image right half, text left half (default)

<div class="layout-split">
<div class="text">

**Text column (left, 50%)**

The default `.layout-split` puts the text on the left and the image on the right,
each taking half the slide width, vertically centered, with a comfortable gap.

- Use `## ...` headings and lists here as usual.
- The text column is vertically centered.

</div>
<div class="image">

![candle](/courses/assets/img/candle.jpg)

</div>
</div>

## 2. Image left half, text right half

<div class="layout-split image-left">
<div class="image">

![stars](/courses/assets/img/stars.jpg)

</div>
<div class="text">

**Text column (right, 50%)**

Add the `image-left` modifier to move the image to the left (and text to the right)
while keeping the 50/50 split.

- Great for leading with a photo before the text.

</div>
</div>

## 3. Text 2/3, image right 1/3

<div class="layout-split text-2-3">
<div class="text">

**Wide text column (left, ~2/3)**

The `text-2-3` variant gives the text two thirds of the slide and the image one
third on the right.

- Use this when the text carries most of the content.
- The image column stays centered and fills its third.

</div>
<div class="image">

![mosque](/courses/assets/img/mosque.jpg)

</div>
</div>

## 4. Image 1/3 left, text 2/3 right

<div class="layout-split image-left-1-3">
<div class="image">

![kaaba](/courses/assets/img/kaaba.jpg)

</div>
<div class="text">

**Wide text column (right, ~2/3)**

`image-left-1-3` places a one-third image on the left and a two-third text column
on the right — the mirrored companion of `text-2-3`.

- Combine `text-2-3 image-left` for the same effect.

</div>
</div>

## 5. Image 2/3 left, text 1/3 right

<div class="layout-split image-2-3">
<div class="image">

![madaba-map](/courses/assets/img/madaba-map.jpg)

</div>
<div class="text">

**Narrow text column (right, ~1/3)**

`image-2-3` lets the image dominate (two thirds) on the left with a one-third text
column on the right.

- Great for large maps/diagrams with a short caption.

</div>
</div>

## Mixing with reveal features

Layouts compose with other reveal.js markup — fragment lists, backgrounds, etc.

<div class="layout-split text-2-3">
<div class="text">

- Reveal **fragments** work inside the text column:
  <span class="fragment">first</span>,
  <span class="fragment">second</span>,
  <span class="fragment">third</span>.
- Use `--` to separate slides and `##` to start a new `layout-split` each time.

</div>
<div class="image">

![dome-of-the-rock](/courses/assets/img/dome-of-the-rock.jpg)

</div>
</div>
