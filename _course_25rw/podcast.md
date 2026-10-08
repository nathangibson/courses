---
layout: default
title: Podcast
permalink: /courses/25rw/podcast/
---
<div class="post-content">
<h1>{{ page.title }}</h1>
Welcome to Ulis podcast page. Here are our latest episodes.

To subscribe to this podcast, go to your podcast player and choose "Subscribe with URL" (or similar). Then paste this URL there: {{ site.url }}{{ site.baseurl }}/podcast.xml

{% for entry in site.podcasts %}
  <article>
    <h2><a href="{{ entry.url }}">{{ entry.title }}</a></h2>
    <p>{{ entry.short_description }}</p>
      {% if entry.image %}
        {% include featured-image.html image=entry.image %}
      {% endif %}
      {% include audio.html mp3=entry.mp3 %}
  </article>
{% endfor %}
</div>