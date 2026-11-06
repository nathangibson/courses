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
bin/serve                  # site tests (lint + build census), then jekyll serve
```

`bin/serve` runs the LINT layer (seconds) and the BUILD census first, so
content errors surface immediately instead of as blank pages or silent 404s.
Plain `bundle exec jekyll serve --baseurl /courses` also still works.

## Testing & CI

The suite has three gates behind one entry point, `rake ci`:

| Gate | What it catches | Speed |
|---|---|---|
| `rake lint` | YAML control chars (Zotero exports), front-matter parse errors, **unregistered collections** (silent 404s), **permalink conflicts** (mapped back to source files — Jekyll names none), session-doc sanity, unsmudged LFS pointers | seconds |
| `rake build` | jekyll build + post-build census: every registered collection emitted HTML, every slide deck rendered reveal `<section>`s, session titles composed, LFS smudge | ~1 min |
| `rake proof` | html-proofer on `_site` (offline): internal links → 404, missing images, empty srcs — **`file:line` per failure** | ~1 min |

Every finding prints:

```
ERROR [check-id] <source file>:<line> — <problem> | fix: <one-liner> | sanitizer: <tool action>
```

Severity model: **ERROR** blocks CI; **WARN** passes with fix guidance;
**WAIVED** = explicitly suppressed with a reason in `config/test_waivers.yml`
(still visible in output). Machine-readable findings: `tmp/test-*.json`.

CI layout (three workflows):
- **`ci.yml`** — runs the full suite on every PR into `main` (checks out the
  *merge commit*, so it tests what actually lands) and on feature-branch
  pushes; uploads `test-results` and built-site artifacts.
- **`preview.yml`** — a push to a `preview/<name>` branch (or a PR from one)
  deploys to the separate **`nathangibson/courses-preview`** repo, served at
  `https://npgibson.com/courses-preview/<name>` (custom domain inherited).
  One directory per branch; the live site is never touched.
- **`pages.yml`** — deploys the live site, `push: main` only, with the same
  suite layered in.

To get the preview deploys working (once): create `nathangibson/courses-preview`
(public, Pages source "Deploy from a branch" → `main` / root), add a
fine-grained PAT with **Contents: Read and write** on `courses-preview` only
as the repo secret `PREVIEW_DEPLOY_TOKEN`, and set branch protection on
`main` (require PR + required status check **`ci`**; enable auto-merge,
squash default).

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
- **Collection permalinks must NOT repeat the baseurl.** With `baseurl: /courses`,
  use `permalink: /25rw/:title` (not `/courses/25rw/:title`) or you get a doubled
  `/courses/courses/...` path.
- **reveal.js has a nested submodule** (`plugin/menu` → denehyg/reveal.js-menu).
  Always clone/init recursively — `git submodule update --init --recursive` — or
  `plugin/menu/menu.js` is missing and every slide deck is blank
  (`RevealMenu is not defined` → `Reveal.initialize()` throws). GitHub Actions
  handles this via `submodules: recursive` in the checkout step.
- To preview locally the deployed structure, serve the built `_site` under a
  `/courses/` prefix (e.g. symlink `courses -> _site` and serve the parent);
  `jekyll serve --baseurl` misroutes deep collection subpaths.
