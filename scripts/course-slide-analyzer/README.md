# Course Slide Analyzer

Scans Nathan Gibson's upcoming-class slide decks and scores each one across six
**pedagogical areas** on a 0–100 scale, then ranks the most *underdeveloped*
areas. It is the scoring stage of the Tuesday class-prep workflow: it consumes
the normalized class JSON produced by the sibling
[course-week-fetcher](../course-week-fetcher), inspects each class's slides,
notes, linked literature and images, and emits per-class scores + evidence +
ranked underdeveloped areas for the question generator (`t_ed34a09a`) and the
end-to-end integrator (`t_fcd06286`) to consume.

Created for kanban task `t_f2559172`.

## How it fits the pipeline

```
course-week-fetcher  —>  data/latest.json  —>  THIS analyzer  —>  data/analysis.json
   (Tuesday 07:00 cron)                                    |      (scores + evidence + ranking)
                                                           v
                                          question generator (top-3) —> Tuesday alert (Buzz)
```

## The six areas & their explicit heuristics

| Area | What it checks |
|------|----------------|
| **Flow** | Transitions and forward/backward tie-ins across the session: `Rückblick` / "letztes Lernziel" (backward), `Vorschau` / next-session (forward), learning objectives, agenda/signposting (`Gliederung`, `Ansage`), and *empty* stub sections (a bare `## Einleitung` with no content) counted as broken transitions. |
| **Examples** | Specific historical/contemporary/fictional-character examples: named figures (Warburg, Frazer, Weber, Jesus, Buddha, …), real places, era dates, explicit claim markers (`Beispiel`, `z. B.`), and stylistic teaching cases (paper aeroplane, "Beeren-Problem", football ethnography, the medicine-trial analogy). |
| **Images** | Book covers, portraits, field archives, maps, illustrative drawings, metaphor images: every `![…](…)`, `{% include img-row.html %}` set, front-matter `image`/`parallaxBackgroundImage`, `figcaption`s, plus recognition of cover/portrait/map/drawing categories from filenames. |
| **Mental hooks** | Metaphors & comparisons (`wie ein`, `analog zu`, `Metapher`), mnemonics (`Eselsbrücke`, "drei Ebenen", bolded parallel lists), and diagrams (mermaid / `*diagram*.png` / `Schema`). |
| **Thought-provoking** | Comics (Calvin & Hobbes, Vater & Sohn, B.C.) and provocations: challenge prompts that push back on the reader's default ("Würdest du dieses Medikament nehmen?"), plus open reflection questions. |
| **Language** | German grammar + precise vocabulary: curated, high-precision German grammar/typo flaw patterns (documented in `course_slide_analyzer.py`) and technical terms with glosses (`_charis_, „Gnade, Geschenk"`), Fachbegriffe (`außeralltäglich`, `Vergemeinschaftung`, `Ikonographie`, …). |

Each area returns a weighted 0–100 score (present-signal credits minus deficit
signals, clamped), with **evidence snippets** that are real substrings of the
source so the score is auditable.

> **Precision note on `language`:** German-grammar detection is heuristic — a
> curated list of specific flaw patterns rather than a full parser, so it stays
> fast, deterministic, and free of false positives on well-formed deck prose.
> `Materiellen`/`alle Genders`/`entschiedet`/`Fortschitt`-style issues are the
> intended catches. Extend `GRAMMAR_FLAWS` in the script to cover more.

## Output schema (`data/analysis.json`)

Top level: `analyzer_version`, `input_file`, `generated_at`, `as_of`,
`window_start/end`, `count`, `underdeveloped_threshold`, `classes[]`.

Each class:

```jsonc
{
  "class_id": "26rw-2026-11-16-6",
  "title": "Welche Rolle spielt Gender in der Religion?",
  "date": "2026-11-16",
  "slides_available": true,
  "sources": { "slides": "…-slides.md", "notes": "….md", "literature": [ "…" ] },
  "scores": { "flow": 64, "examples": 100, "images": 30, "mental_hooks": 45,
              "thought_provoking": 65, "language": 20 },
  "evidence": { "<area>": [ { "kind": "…", "snippet": "…", "note": "…" } ] },
  "details": { "<area>": { "<signal>": <count>, … } },
  "underdeveloped_threshold": 60,
  "ranked_all":  [ { "area": "language", "score": 20, "label": "Language" }, … ],  // ascending
  "ranked_underdeveloped": [ /* areas below threshold, ascending */ ]
}
```

The question generator reads `ranked_underdeveloped` (respecting `ranked_all`
order) to pick each class's top-3 underdeveloped areas.

## Usage

Requires the Hermes dependency venv's Python (`3.13`, has `yaml`):
`/Users/nathan/.hermes/hermes-agent/venv/bin/python3`.

```bash
cd /Users/nathan/git/Github/nathangibson/courses/scripts/course-slide-analyzer

# Analyze the fetcher's latest.json -> writes data/analysis.json (config-driven)
$PY python3 course_slide_analyzer.py

# Pretty table to stdout, nothing written (default input from config.yml)
$PY python3 course_slide_analyzer.py --pretty --dry-run

# Point at a specific fetcher JSON / raise the underdeveloped cutoff
$PY python3 course_slide_analyzer.py --input ../course-week-fetcher/data/latest.json --threshold 62

# Acceptance tests
$PY python3 tests/test_analyzer.py
```

where `$PY=/Users/nathan/.hermes/hermes-agent/venv/bin/python3`.

## Configuration (`config.yml`)

- `input_json` — fetcher JSON to consume (relative to the analyzer dir).
- `output_dir` — where `analysis.json` is written.
- `underdeveloped_threshold` — cutoff below which an area is "underdeveloped"
  (default 60).

## Determinism / stability

The analyzer is **deterministic by construction**: pure regex/text analysis, no
randomness, no LLM calls. Identical input always produces identical output
(verified by `tests/test_analyzer.py`). PDF *bodies* are intentionally not
parsed — literature is scored from JSON metadata (titles/authors) so the cron
stays fast and dependency-free.

## Failure behaviour

- Missing/unreadable `input_json` → clear exception and non-zero exit.
- Missing slide/notes file for a class → that class records `slides_available:
  false` and is scored from whatever exists (never crashes the run).
- No config file → defaults apply (fetcher `latest.json`, threshold 60);
  a malformed config logs a warning and falls back.

## Notes for the integrator (`t_fcd06286`)

Call as `$PY course_slide_analyzer.py` after the fetcher runs; read
`data/analysis.json`. The analyzer dir is _not_ committed (like the fetcher's)
so `data/` stays out of git — commit when the user approves.
