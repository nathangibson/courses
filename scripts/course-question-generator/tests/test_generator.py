#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_generator.py — acceptance tests for the course question generator.

Acceptance criteria from kanban task t_ed34a09a:
  1. At most three prompts per class.                (hard alert-channel limit)
  2. Prompts are short enough for a morning alert.   (concise, one-line)
  3. The payload validates against the alert channel schema.
     (t_4d31b4d9's tuesday_alert.validate)
  4. Exactly one prompt per selected area.
  5. Area-specific templates are used.
  6. Output is deterministic/stable (two runs byte-identical).

Run:  <hermes-venv-python> tests/test_generator.py
"""
import io
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
GEN_DIR = os.path.dirname(HERE)
sys.path.insert(0, GEN_DIR)
import question_generator as G  # noqa: E402

# The alert channel's validate() lives in the sibling Buzz module.
ALERT_MODULE = os.path.expanduser(
    "~/git/git-local/buzz/deploy/tuesday_alert/tuesday_alert.py"
)

ANALYSIS_JSON = os.path.join(
    GEN_DIR, "..", "course-slide-analyzer", "data", "analysis.json"
)

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL  {name}  {detail}")


def _load_analysis():
    with open(ANALYSIS_JSON, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _payloads(analysis):
    """Run the generator twice and return (p1, p2, payload_json_both)."""
    p1 = G.generate(analysis, run_date=analysis["as_of"])
    p2 = G.generate(analysis, run_date=analysis["as_of"])
    s1 = json.dumps(p1, ensure_ascii=False, sort_keys=True)
    s2 = json.dumps(p2, ensure_ascii=False, sort_keys=True)
    return p1, p2, s1, s2


def main():
    analysis = _load_analysis()
    p1, p2, s1, s2 = _payloads(analysis)

    print("[1] Determinism: two runs byte-identical")
    check("deterministic output", s1 == s2)

    print("[2] Per-class limits + per-area one-prompt")
    all_areas_per_class_ok = True
    max_ok = True
    short_ok = True
    n_classes = 0
    n_questions = 0
    for c in p1["classes"]:
        n_classes += 1
        qs = c["questions"]
        n_questions += len(qs)
        if not 1 <= len(qs) <= 3:
            max_ok = False
            print(f"    ! {c['class_title']}: {len(qs)} questions")
        areas = [q["area"] for q in qs]
        if len(set(areas)) != len(areas):
            all_areas_per_class_ok = False
            print(f"    ! duplicate area in {c['class_title']}: {areas}")
        for q in qs:
            # short enough for a morning alert (< ~200 chars, one sentence)
            if len(q["prompt_text"]) > 240:
                short_ok = False
                print(f"    ! too long ({len(q['prompt_text'])}): {q['prompt_text']}")
    check("1..3 questions per class", max_ok)
    check("one prompt per selected area (no dupes)", all_areas_per_class_ok)
    check("prompts fit a morning alert (<240 chars)", short_ok)
    print(f"    ({n_classes} classes, {n_questions} questions total)")

    print("[3] Exactly one prompt of each type per class (rotation)")
    rot_ok = True
    for c in p1["classes"]:
        types = [q["prompt_type"] for q in c["questions"]]
        if len(set(types)) != len(types):
            rot_ok = False
            print(f"    ! repeated prompt_type in {c['class_title']}: {types}")
        for t in types:
            if t not in G.PROMPT_TYPES:
                rot_ok = False
                print(f"    ! invalid prompt_type {t}")
    check("valid + non-repeated prompt types", rot_ok)

    print("[4] Area-specific templates used")
    area_ok = True
    for c in p1["classes"]:
        for q in c["questions"]:
            area = q["area"]
            key = {v: k for k, v in {
                "flow": "Flow", "examples": "Examples", "images": "Images",
                "mental_hooks": "Mental hooks", "thought_provoking": "Thought-provoking",
                "language": "Language"}.items()}[area]
            templ = G.AREA_TEMPLATES[key][q["prompt_type"]]
            base = templ.split("{")[0]  # text before first placeholder
            if not q["prompt_text"].startswith(base.rstrip()):
                area_ok = False
                print(f"    ! {area} prompt does not start with its template: "
                      f"{q['prompt_text']!r}")
    check("prompts start from area-specific templates", area_ok)

    print("[5] Alert-channel schema validation")
    try:
        sys.path.insert(0, os.path.dirname(ALERT_MODULE))
        import importlib.util
        spec = importlib.util.spec_from_file_location("tuesday_alert",
                                                       ALERT_MODULE)
        if spec is None or spec.loader is None:
            raise ImportError("could not build loader for alert module")
        ta = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ta)
    except Exception as exc:  # noqa: BLE001
        print(f"    ! could not load alert module: {exc}")
        FAIL.append("alert-channel schema validation")
        check("payload validates against alert channel", False, str(exc))
        _finish()
        return

    try:
        ta.validate(p1)
        check("payload validates against alert channel", True)
    except ValueError as exc:
        check("payload validates against alert channel", False, str(exc))

    # A malformed variant must be rejected (max-3 rule present in the channel).
    bad = json.loads(json.dumps(p1))
    bad_class = {"class_title": "X", "class_date": "2026-11-17",
                 "questions": [{"area": "Flow", "prompt_type": "suggestion",
                                "prompt_text": "a"} for _ in range(4)]}
    bad["classes"] = [bad_class]
    try:
        ta.validate(bad)
        check("4-question class rejected by channel", False, "was not rejected")
    except ValueError:
        check("4-question class rejected by channel", True)

    print(f"\n{'='*60}\nPASS: {len(PASS)}   FAIL: {len(FAIL)}")
    _finish()


def _finish():
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
