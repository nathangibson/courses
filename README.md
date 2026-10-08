# Courses — Nathan P. Gibson

Consolidated Jekyll site for Nathan Gibson's course websites, served at
**https://npgibson.com/courses**.

## Structure

One shared theme, one build pipeline, each course a Jekyll **collection**.

```
_course_<slug>/     course content (posts, slides, pages) — one dir per course
_data/course_<slug>/  per-course data: sessions.csv, settings.yml, glossary.csv, zotero.yaml
_includes/ _layouts/ _sass/ _plugins/   shared Millennial theme + revealify.rb (once)
assets/reveal.js      shared reveal.js submodule
assets/course-website-tools  shared tooling submodule
assets/img/           centralized image pool (Git LFS)
```

## Adding a course

1. Copy the course's content into `_course_<slug>/` (posts + pages) and its
   `sessions.csv`/`settings.yml`/`glossary.csv`/`zotero.yaml` into
   `_data/course_<slug>/`.
2. Move any shared images into `assets/img/` (Git LFS).
3. Register the course in `_config.yml`:
   ```yaml
   collections:
     course_<slug>:
       output: true
       permalink: /courses/<slug>/:title
   ```
4. Add a course card to `index.html`.

## Local development

```bash
rbenv install 3.3.1        # once
rbenv global 3.3.1
bundle install             # once
bundle exec jekyll serve --baseurl /courses   # http://localhost:4000/courses/...
```

## Build / deploy

GitHub Actions (`.github/workflows/pages.yml`) builds the site with Jekyll on
every push to `main` and deploys to GitHub Pages. Git LFS handles the image
pool (`.gitattributes`). The build relies on a custom plugin (`_plugins/revealify.rb`)
that renders reveal.js slides, so it MUST go through the Actions build — plain
GitHub Pages `--safe` builds will not run it.

## Conventions / gotchas

- Frontmatter strings are **not** Liquid-rendered: keep `parallaxBackgroundImage`
  as a root-relative path (`assets/img/x.jpg`) — the reveal layout prepends `baseurl`.
- Inline markdown image refs (in post/slide bodies) **are** Liquid-rendered, so use
  `{{ site.baseurl }}/assets/img/x.jpg`.
- Jekyll collection docs strip a leading ISO date from filenames when deriving
  the `:title` slug, so `2025-10-13-1.md` becomes URL `/courses/25rw/1` unless a
  `title:`/`permalink:` is set. Decide the final slug scheme during bulk migration.
