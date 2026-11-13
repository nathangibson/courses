---
layout: default
title: Podcast
permalink: /26ki/podcast
---

<div class="post-content">
<h1>{{ page.title }}</h1>

Podcast episodes will appear here.

To subscribe to this podcast, go to your podcast player and choose "Subscribe with URL" (or similar). Then paste this URL there: {{ site.url }}{{ site.baseurl }}/podcast.xml

{% for entry in site.podcasts %}
  <article>
    <h2><a href="{{ entry.url }}">{{ entry.title }}</a></h2>
    <p>{{ entry.short_description }}</p>
  </article>
{% endfor %}
</div>
