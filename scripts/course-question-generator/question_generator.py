#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
question_generator.py — Top-3 area questions for Nathan Gibson's Tuesday prep.

Consumes the slide-content analyzer's output (`data/analysis.json`, produced
by the sibling `../course-slide-analyzer`) and, for each class, selects the top
three underdeveloped pedagogical areas and turns each into exactly one concise,
user-facing prep prompt — an open question, a concrete suggestion, or a search
request — drawn from class-specific evidence so the prompt is specific to that
deck, not generic.

It is the "ask me what to improve" stage of the Tuesday class-prep workflow:
it feeds the alert channel payload schema defined in `t_4d31b4d9`
(`~/git/git-local/buzz/deploy/tuesday_alert`).

Six areas & the template family each uses (per the "class prep slow brew"
brief):

  flow             tighten transitions / forward- & backward-looking tie-ins
  examples         add a specific historical, contemporary, or
                   fictional-character example
  images           which book cover / portrait / map / archive / drawing to add
  mental_hooks     a metaphor, mnemonic, or diagram
  thought_provoking  a Calvin & Hobbes, Vater & Sohn, or B.C. comic / provocation
  language         a German grammar or precise-vocabulary improvement

Design notes
------------
* Deterministic by construction: no randomness, no LLM calls. The same
  analysis.json always yields the same prompt payload (accepted: stable across
  the Tuesday cron).
* Selection: read `ranked_underdeveloped` (ascending, below the analyzer's
  threshold) and take the top 3; if fewer than 3 areas fall under the
  threshold, fall back to `ranked_all` order to still reach 3.
* Prompt type: each class's 3 prompts rotate open_question -> suggestion ->
  search (stable and varied), never more than one of each per class so the
  Tuesday alert stays scannable rather than repetitive.
* Templates are filled with real evidence from the class (actual grammar flaw,
  actual empty header, actual figures/images/literature) wherever the analyzer
  recorded it, so each prompt names the concrete spot to improve.

Failure behaviour
-----------------
* Missing/unreadable input analysis.json -> clear exception + non-zero exit.
* A class with no ranked areas still yields a class entry with zero questions
  (never crashes the run); these are dropped from the alert payload.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths / defaults
# --------------------------------------------------------------------------- #
DEFAULT_INPUT = (
    Path(__file__).resolve().parent.parent
    / "course-slide-analyzer" / "data" / "analysis.json"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "course-question-generator" / "data"

# Non-empty prompt types, in the rotation order applied per class (one each).
PROMPT_TYPES = ["open_question", "suggestion", "search"]

# --------------------------------------------------------------------------- #
# Area -> template family.  Each template is a list of (kind, text) where
# `text` may contain {evidence} / {score} / {lit} placeholders; the first kind
# matching the requested prompt_type is chosen.  Fallbacks per type guarantee
# one prompt always exists for any area.
# --------------------------------------------------------------------------- #
AREA_TEMPLATES = {
    "flow": {
        # kind: text (placeholders: {evidence}, {score}, {lit})
        "open_question": (
            "Welche Verbindung oder Überleitung zwischen zwei Abschnitten "
            "würdest du gern straffen{evidence}?"
        ),
        "suggestion": (
            "Soll ich eine Übergangs/Verbindungsformulierung ergänzen, die "
            "auffälliger vor- oder zurückverweist{evidence}?"
        ),
        "search": (
            "Wonach soll ich suchen, um die Überleitungen dieser Sitzung zu "
            "verknüpfen{evidence}?"
        ),
    },
    "examples": {
        "open_question": (
            "Welches Beispiel (historisch, aktuell oder fiktiv) möchtest du "
            "hier ergänzt haben{evidence}?"
        ),
        "suggestion": (
            "Soll ich ein konkretes Beispiel aus der Literatur hinzufügen"
            "{lit_ret}?"
        ),
        "search": (
            "Soll ich nach einem bestimmten historischen oder aktuellen "
            "Beispiel suchen{evidence}?"
        ),
    },
    "images": {
        "open_question": (
            "Welches Bild (Titelbild, Porträt, Karte, Archivfoto oder "
            "Zeichnung) schwebte dir für diese Sitzung vor{evidence}?"
        ),
        "suggestion": (
            "Soll ich ein Bild zu diesem Thema ergänzen — z. B. ein "
            "Titelbild, Porträt, eine Karte oder eine Illustration{evidence}?"
        ),
        "search": (
            "Soll ich nach einem gemeinfreien Bild (Buchcover, Porträt, "
            "Karte, Archivfoto) suchen{evidence}?"
        ),
    },
    "mental_hooks": {
        "open_question": (
            "Welche Metapher, Eselsbrücke oder welches Diagramm könnte diese "
            "Sitzung besser verankern{evidence}?"
        ),
        "suggestion": (
            "Soll ich eine Metapher, Eselsbrücke oder ein Diagramm für den "
            "Kern dieser Sitzung entwerfen{evidence}?"
        ),
        "search": (
            "Soll ich nach einem passenden Schema oder Diagramm zum Thema "
            "suchen{evidence}?"
        ),
    },
    "thought_provoking": {
        "open_question": (
            "Welche provozierende Frage oder welcher Comic (z. B. Calvin & "
            "Hobbes, Vater & Sohn, B.C.) passt zu dieser Sitzung{evidence}{score_note}?"
        ),
        "suggestion": (
            "Soll ich einen passenden Comic (Calvin & Hobbes, Vater & Sohn, "
            "B.C.) oder eine Provokationsfrage vorschlagen{evidence}{score_note}?"
        ),
        "search": (
            "Soll ich nach einem thematisch passenden Comic oder einer "
            "provozierenden Frage suchen{evidence}?"
        ),
    },
    "language": {
        "open_question": (
            "Welche deutsche Grammatik- oder Wortschatzstelle möchtest du "
            "verbessert haben{evidence}?"
        ),
        "suggestion": (
            "Soll ich den Sprachfehler korrigieren und das präzise Vokabular "
            "schärfen{evidence}?"
        ),
        "search": (
            "Soll ich nach dem präzisen deutschen Fachbegriff für diese "
            "Stelle suchen{evidence}?"
        ),
    },
}

# Default search terms attached to `search` prompts, keyed by area.
AREA_SEARCH_TERMS = {
    "flow": ["Übergangsformulierung didaktisch", "Lernziel Vorwissen verknüpfen"],
    "examples": ["historisches Beispiel Religionswissenschaft"],
    "images": ["gemeinfreies Bild Religionswissenschaft", "public domain"],
    "mental_hooks": ["Diagramm Religionswissenschaft", "Schema Fachbegriff"],
    "thought_provoking": ["Calvin and Hobbes religion", "philosophischer Comic"],
    "language": ["deutscher Fachbegriff Religionswissenschaft"],
}

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _area_label(key: str) -> str:
    return {
        "flow": "Flow",
        "examples": "Examples",
        "images": "Images",
        "mental_hooks": "Mental hooks",
        "thought_provoking": "Thought-provoking",
        "language": "Language",
    }.get(key, key.title())


def _evidence_hint(evidence: list | None) -> str:
    """Return a short, real evidence snippet (if any) to anchor the prompt."""
    if not evidence:
        return ""
    # Prefer the deficit/actionable kinds that name a concrete spot.
    for item in evidence:
        kind = item.get("kind", "")
        if kind in ("grammar_flaw", "empty_section", "mnemonic", "analogy",
                    "provocation", "front_image", "images"):
            snippet = item.get("snippet", "").strip()
            if snippet:
                return f" (z. B. {snippet})"
    for item in evidence:
        snippet = item.get("snippet", "").strip()
        if snippet:
            return f" (z. B. {snippet})"
    return ""


def _lit_suffix(literature: list | None) -> str:
    """Return ' aus <Titel>' when linked literature is available."""
    if not literature:
        return ""
    title = str(literature[0]).strip()
    if not title:
        return ""
    return f" aus „{title}“"


def _score_note(score: int) -> str:
    """Brutally low-scoring thought-provoking areas get an encouraging nudge."""
    if score < 30:
        return " — da hier noch fast nichts vorhanden ist"
    return ""


def _build_prompt(area_key: str, prompt_type: str, class_data: dict) -> dict:
    """Build one prompt dict for an area using the area's template family."""
    evidence = class_data.get("evidence", {}).get(area_key)
    scores = class_data.get("scores", {})
    score = scores.get(area_key, 0)
    lit = class_data.get("sources", {}).get("literature") or []

    templ = AREA_TEMPLATES.get(area_key, {})
    text = templ.get(prompt_type) or templ.get("open_question") or (
        "Was möchtest du in diesem Bereich verbessern?"
    )

    ev = _evidence_hint(evidence)
    lit_ret = _lit_suffix(lit)
    score_note = _score_note(score)

    prompt_text = text.format(evidence=ev, lit_ret=lit_ret, score_note=score_note)
    prompt_text = prompt_text.strip()

    q: dict[str, object] = {
        "area": _area_label(area_key),
        "prompt_type": prompt_type,
        "prompt_text": prompt_text,
    }
    if prompt_type == "search":
        q["suggested_search_terms"] = AREA_SEARCH_TERMS.get(area_key, [])
    return q


def _select_top3(class_data: dict) -> list[str]:
    """Return the top-3 area keys (lowest score first) for a class.

    Prefer the analyzer's `ranked_underdeveloped` (ascending, below threshold);
    if that yields fewer than 3, top up in `ranked_all` order.
    """
    chosen: list[str] = []
    for entry in class_data.get("ranked_underdeveloped", []) or []:
        chosen.append(entry["area"])
        if len(chosen) >= 3:
            break
    if len(chosen) < 3:
        for entry in class_data.get("ranked_all", []) or []:
            if entry["area"] not in chosen:
                chosen.append(entry["area"])
            if len(chosen) >= 3:
                break
    return chosen[:3]


def generate(analysis: dict, run_date: str | None = None,
             notes: str | None = None) -> dict:
    """Turn an analysis.json document into an alert-channel payload."""
    classes_out = []
    for class_data in analysis.get("classes", []) or []:
        title = class_data.get("title", "")
        date = class_data.get("date", "")
        if not class_data.get("slides_available"):
            # No slides to improve -> nothing to ask about (skip quietly).
            continue
        areas = _select_top3(class_data)
        questions = [
            _build_prompt(area, PROMPT_TYPES[i % len(PROMPT_TYPES)], class_data)
            for i, area in enumerate(areas)
        ]
        entry = {"class_title": title, "class_date": date, "questions": questions}
        if questions:
            classes_out.append(entry)

    payload: dict[str, object] = {"classes": classes_out}
    if run_date is not None:
        payload["run_date"] = run_date
    if notes is not None:
        payload["notes"] = notes
    return payload


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default=str(DEFAULT_INPUT),
                    help="Analyzer output JSON (default: analyzer data/analysis.json)")
    ap.add_argument("--output", default=None,
                    help="Where to write the payload JSON (default: data/questions.json)")
    ap.add_argument("--run-date", default=None,
                    help="Tuesday run_date (dedupe key) to stamp on the payload; "
                         "defaults to 'as_of' from the analysis doc")
    ap.add_argument("--notes", default=None,
                    help="Optional top note for the alert")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the payload to stdout, write nothing")
    args = ap.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: input not found: {input_path}", file=sys.stderr)
        return 2
    try:
        with open(input_path, "r", encoding="utf-8") as fh:
            analysis = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: could not read analysis JSON: {exc}", file=sys.stderr)
        return 2

    run_date = args.run_date or analysis.get("as_of")
    payload = generate(analysis, run_date=run_date, notes=args.notes)

    total_questions = sum(len(c["questions"]) for c in payload["classes"])
    # Guard: never exceed 3 questions per class (alert channel hard limit).
    for c in payload["classes"]:
        if len(c["questions"]) > 3:
            print(f"ERROR: class '{c['class_title']}' exceeded 3 questions",
                  file=sys.stderr)
            return 3

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"\n# classes: {len(payload['classes'])}, "
              f"# questions: {total_questions}", file=sys.stderr)
        return 0

    out = args.output or DEFAULT_OUTPUT
    out_dir = Path(out) if Path(out).suffix else Path(out)
    if Path(out).suffix:
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        out_file = Path(out)
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "questions.json"
    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"Wrote {total_questions} questions across {len(payload['classes'])} "
          f"classes -> {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
