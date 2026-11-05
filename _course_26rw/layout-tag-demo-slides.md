---
layout: reveal
title: 'Markdown-only layout demo'
author: 'Nathan Gibson'
category: slides
---

# Markdown-only layouts

The `layout` tag — no HTML containers needed.

## Full-width photo

{% layout photo-full %}
![dome-of-the-rock](../assets/img/dome-of-the-rock.jpg)
{% endlayout %}

## Split: text left, image right

{% layout split %}
Hier steht der Text auf der linken Spalte.

- Gewöhnliches **Markdown** funktioniert normal.
- Listen, Links, alles.

{% col image %}
![candle](../assets/img/candle.jpg)
{% endlayout %}

## Split: image left

{% layout split image-left %}
{% col image %}
![stars](../assets/img/stars.jpg)
{% col text %}
Text auf der rechten Spalte — das Bild wurde mit `image-left` nach links
verschoben.
{% endlayout %}

## Text 2/3, image 1/3

{% layout split text-2-3 %}
Breite Textspalte (zwei Drittel) — für textlastige Folien.
{% col image %}
![mosque](../assets/img/mosque.jpg)
{% endlayout %}

## Ende

Jede Folie: erst die `##` Überschrift, dann der Layout-Block.
