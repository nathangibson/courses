# Course Question Generator

Turns the slide-content analyzer's per-class scores into **top-3 prep
questions** for Nathan Gibson's Tuesday class-prep workflow. For each class it
picks the three most underdeveloped pedagogical areas and turns each into
exactly one concise, user-facing prompt — an *open question*, a *concrete
suggestion*, or a *search request* — with the prompt anchored to real evidence
from that specific deck (the actual grammar flaw, the actual empty header, the
actual figure or literature title).

This is the "ask me what to improve" stage of the pipeline. It feeds the alert
channel payload schema defined in `t_4d31b4d9`
(`~/git/git-local/buzz/deploy/tuesday_alert`).

Created for kanban task `t_ed34a09a`.

## How it fits the pipeline

```
course-week-fetcher —> data/latest.json —> analyzer —> data/analysis.json
   (Tue 07:00 cron)                                  (scores + ranking)
                                                            |
                                                            v
                                          THIS generator —> data/questions.json
                                             (top-3 per class)     |
                                                                   v
                                               Tuesday alert (Buzz, max 3/class)
```

## What it selects

Per class the generator reads `ranked_underdeveloped` (the analyzer's ranked
list of areas *below* the underdevelopment threshold, ascending by score) and
takes the **top three**. If fewer than three areas fall under the threshold, it
tops up in `ranked_all` order so every class still gets up to three actionable
prompts.

## The six areas & their prompt families

| Area | Prompt asks about |
|------|-------------------|
| **Flow** | Tightening transitions / forward- or backward-looking tie-ins across the session |
| **Examples** | Adding a specific historical, contemporary, or fictional-character example (optionally drawn from the linked literature) |
| **Images** | Which book cover, portrait, map, archive, or illustrative drawing to add |
| **Mental hooks** | A metaphor, mnemonic, or diagram |
| **Thought-provoking** | A Calvin & Hobbes, Vater & Sohn, or B.C. comic, or a provocation |
| **Language** | A German grammar or precise-vocabulary improvement |

Each area has a template family for all three prompt types
(`open_question` / `suggestion` / `search`), and the prompt text is filled with
a **real evidence snippet** from the analyzer (e.g. *“Fortschitt → Fortschritt
(typo)”*) wherever one exists, so the question names the concrete spot rather
than being generic. `search` prompts also carry default `suggested_search_terms`
(overridable by editing `AREA_SEARCH_TERMS`).

## Prompt-type rotation

To keep the Tuesday alert scannable rather than monotonous, each class's three
prompts rotate **one of each type** — open question (Q?), suggestion (💡),
search (🔎) — in a stable order. Never more than one of each per class.

## Output — alert-channel payload

Writes `data/questions.json` matching the Buzz Tuesday-alert schema:

```jsonc
{
  "run_date": "2026-11-10",       // the Tuesday (dedupe key), from analysis.as_of
  "classes": [{
    "class_title": "5. Mythos vs. Bild: Aby Warburg",
    "class_date":  "2026-11-12",
    "questions": [ {                       // at most 3 per class
      "area": "Mental hooks",
      "prompt_type": "open_question",      // open_question | suggestion | search
      "prompt_text": "Welche Metapher, Eselsbrücke oder welches Diagramm ...?"
      // "suggested_search_terms": ["..."] only on search prompts
    } ]
  } ]
}
```

This is exactly the payload the alert channel's `validate()` accepts
(`prompt_type` in `{open_question, suggestion, search}`, at most 3 questions
per class, required `class_title`/`class_date`/`prompt_text`).

## Usage

Requires the Hermes dependency venv's Python (3.13, has `yaml`):
`/Users/nathan/.hermes/hermes-agent/venv/bin/python3`.

```bash
cd /Users/nathan/git/Github/nathangibson/courses/scripts/course-question-generator

# Generate the top-3 questions -> data/questions.json (config-driven input)
$PY python3 question_generator.py

# Print the payload without writing
$PY python3 question_generator.py --dry-run

# Override run_date / add a top note / point at a specific analysis.json
$PY python3 question_generator.py --run-date 2026-11-10 --notes "for Tue"
$PY python3 question_generator.py --input ../course-slide-analyzer/data/analysis.json

# Acceptance tests (includes live validation against the alert-channel schema)
$PY python3 tests/test_generator.py
```

where `$PY=/Users/nathan/.hermes/hermes-agent/venv/bin/python3`.

## Configuration (`config.yml`)

- `input_json` — analyzer output to consume (defaults to the analyzer's
  `data/analysis.json`).
- `output_dir` — where `questions.json` is written.
- `max_questions_per_class` — hard cap (alert channel rejects 4+).

## Determinism / stability

Deterministic by construction: no randomness, no LLM calls. The same
analysis.json always yields the same payload (verified byte-identical over two
runs by `tests/test_generator.py`).

## Failure behaviour

- Missing/unreadable `input_json` → clear exception + non-zero exit.
- A class marked `slides_available: false` (nothing to improve) is skipped; a
  class whose `ranked_underdeveloped` is empty is still topped up from
  `ranked_all`, so no class silently drops out.
- If any class ever exceeds 3 questions, the generator exits non-zero rather
  than emitting a payload the alert channel would reject.

## Notes for the integrator (`t_fcd06286`)

Call `$PY question_generator.py` after the analyzer, then
`tuesday_alert.py send data/questions.json` (idempotent by `run_date`). The
generator dir is _not_ committed (like the fetcher's and analyzer's) so it can
be committed deliberately.
