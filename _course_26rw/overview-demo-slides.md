---
layout: reveal
title: 'Overview & Auto-Animate Demo'
author: 'Nathan Gibson'
category: slides
---

# Overview & Auto-Animate

Two features of reveal.js and how to use them in this Jekyll course site.

## The deck

Press **ESC** to enter overview and see all the slides in this deck at once.
Requires reveal.js to finish initializing (see the `Reveal.initialize().then(...)`
handler in `_layouts/reveal.html`, which surfaces init errors).

## Auto-animate — how opt-in works

Auto-animate runs between two CONSECUTIVE `<section data-auto-animate>` slides
that contain matching elements (same tag + `id`). It is NOT automatic for every
transition — you opt in with `data-auto-animate` on each slide.

<section data-auto-animate>
  <h2 id="q">What is religion?</h2>
  <ul id="list">
    <li>system of meaning</li>
    <li>practice</li>
    <li>community</li>
  </ul>
</section>

<section data-auto-animate>
  <h2 id="q">What is religion?</h2>
  <ul id="list">
    <li>system of meaning</li>
    <li>practice</li>
    <li>community</li>
    <li>studied comparatively</li>
  </ul>
</section>

## Markdown headings still split slides

Any `##` heading starts a new slide as usual — auto-animate only applies to the
explicit `<section data-auto-animate>` pairs above and below.

## The End

Overview (ESC) should list every slide in this deck (7 total).
