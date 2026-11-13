#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
course_slide_analyzer.py — Slide-content analyzer for Nathan Gibson's courses.

Consumes the normalized class JSON produced by the course-week fetcher
(sibling directory `../course-week-fetcher/data/latest.json`) and inspects each
class's *available* slides deck, session notes, linked literature and image
assets. It scores six pedagogical areas on a 0–100 scale and emits, per class:

  * a deterministic 0–100 score for each area
  * short, cited *evidence snippets* backing each score
  * a ranked list of the most underdeveloped areas (lowest score first)

Six areas & their explicit heuristics
-------------------------------------
  flow             transitions + forward/backward tie-ins across the session
                   (Rückblick / Vorschau / Lernziel / Gliederung / empty
                   "Einleitung|Diskussion" sections as deficits).
  examples         specific historical / contemporary / fictional-character
                   examples (named figures, real places, concrete case studies,
                   stylistic case figures such as the paper aeroplane).
  images           book covers, portraits, field archives, maps, illustrative
                   drawings, metaphor images (markdown images, img-row
                   includes, parallax/front-matter images, figcaptions).
  mental_hooks     metaphors, comparisons, mnemonics, diagrams (analogy
                   language, "Eselsbrücke", mermaid/PNG diagrams, numbered
                   parallel lists).
  thought_provoking comics (Calvin & Hobbes, Vater & Sohn, B.C.) and
                   provocations (challenge/rhetorical questions that push back
                   on the reader's default assumption).
  language         German grammar + precise vocabulary (technical terms with
                   glosses, plus a curated set of concrete grammar/typo-flaw
                   patterns).

Design notes
------------
* Deterministic by construction: no randomness, no LLM calls. The same input
  JSON + same slide/notes files always yield the same scores (accepted).
* Literature is scored as signals from the JSON metadata (titles/authors) and
  by whether the deck text mentions the reading's key term — PDF *bodies* are
  not parsed (avoiding a fragile, slow dependency in a Tuesday cron).
* A score is a weighted blend of present-signal credits minus deficit signals,
  clamped to [0, 100]. Evidence snippets are real substrings of the source.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths / defaults
# --------------------------------------------------------------------------- #
DEFAULT_INPUT = (
    Path(__file__).resolve().parent.parent
    / "course-week-fetcher" / "data" / "latest.json"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "course-slide-analyzer" / "data"

AREA_KEYS = ["flow", "examples", "images", "mental_hooks",
             "thought_provoking", "language"]
AREA_LABELS = {
    "flow": "Flow",
    "examples": "Examples",
    "images": "Images",
    "mental_hooks": "Mental hooks",
    "thought_provoking": "Thought-provoking",
    "language": "Language",
}
UNDERDEVELOPED_THRESHOLD = 60  # scored below this => "underdeveloped"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def strip_front_matter(text: str) -> str:
    """Remove Jekyll YAML front matter (--- ... ---) so content regexes only
    see the body. Return (body, front_matter_dict_ish)."""
    body = text
    if text.startswith("---"):
        parts = text.split("\n---", 1)
        if len(parts) == 2:
            fm = parts[0][3:]  # drop leading '---'
            body = parts[1]
            return fm, body
    return "", text


def empty_headers(body: str) -> list[str]:
    """Count meaningful section headers (depth >= 2) whose body is empty before
    the next header. Used to flag 'stub' / broken-transition slides such as a
    bare '## Einleitung' with nothing under it. The title slide (everything
    before the first '##' header) and pure-subheader sections are excluded."""
    lines = body.splitlines()
    empties = []
    seen_h2 = False
    for i, line in enumerate(lines):
        m = re.match(r"^(#{2,6})\s+(.*)$", line.strip())
        if not m:
            continue
        depth = len(m.group(1))
        hdr = m.group(2).strip()
        if not seen_h2:
            if depth == 2:
                seen_h2 = True  # first real section marks end of title slide
            else:
                continue  # title-slide title/subtitle headers are not sections
        has_content = False
        k = i + 1
        while k < len(lines):
            t = lines[k].strip()
            hm = re.match(r"^(#{1,6})\s+", t)
            if hm:
                if len(hm.group(1)) > depth:
                    has_content = True  # nested sub-header counts as content
                break
            if t and not t.startswith("{:"):
                has_content = True
                break
            k += 1
        if not has_content:
            empties.append(hdr)
    return empties


def clip(x: float) -> int:
    return max(0, min(100, int(round(x))))


# --------------------------------------------------------------------------- #
# Area 1 — Flow
# --------------------------------------------------------------------------- #
BACKWARD_RE = re.compile(
    r"Rückblick|Rueckblick|zurückblicken|letzte(?:n|s)?\s+(?:Sitzung|Lernziel|Woche|Mal|Stunde)"
    r"|Erinner|Recall|Zusammenfassung|Nochmal|Zuvor|vorige(?:n|s)?|wiederholen|noch einmal",
    re.IGNORECASE,
)
FORWARD_RE = re.compile(
    r"Vorschau|Ausblick|nächste(?:n|s)?\s+(?:Sitzung|Woche|Mal|Stunde)|wird (?:folgen|kommen)"
    r"|kommen wir|Ankündigung|Ziel(?: der| dieser| der heutigen)?|Lernziel",
    re.IGNORECASE,
)
AGENDA_RE = re.compile(
    r"Gliederung|Überblick|Ueberblick|Ablauf|Programm|Tagesordnung|Ansage",
    re.IGNORECASE,
)


def score_flow(body: str, fm: str) -> tuple[int, list[dict], dict]:
    evidence: list[dict] = []
    detail: dict[str, int] = {}

    back = [m.group(0) for m in BACKWARD_RE.finditer(body)]
    fwd = [m.group(0) for m in FORWARD_RE.finditer(body)]
    agenda = [m.group(0) for m in AGENDA_RE.finditer(body)]
    empties = empty_headers(body)

    detail["backward_tieins"] = len(back)
    detail["forward_tieins"] = len(fwd)
    detail["agenda"] = len(agenda)
    detail["empty_headers"] = len(empties)

    score = 40.0
    if back:
        score += 18
        evidence.append({
            "kind": "backward_tiein",
            "snippet": back[0],
            "note": f"{len(back)} backward tie-in marker(s) (Rückblick / last session / recall)",
        })
    if fwd:
        score += 18
        evidence.append({
            "kind": "forward_tiein",
            "snippet": fwd[0],
            "note": f"{len(fwd)} forward tie-in marker(s) (Vorschau / next week / objective)",
        })
    if agenda:
        score += 10
        evidence.append({
            "kind": "agenda",
            "snippet": agenda[0],
            "note": "Agenda / structure-signposting present (Gliederung, Ansage, …)",
        })
    if empties:
        score -= 12 * len(empties)
        evidence.append({
            "kind": "empty_section",
            "snippet": f"## {empties[0]}",
            "note": f"{len(empties)} empty header(s): {', '.join(empties)} — a missing transition/content bridge",
        })

    return clip(score), evidence, detail


# --------------------------------------------------------------------------- #
# Area 2 — Examples
# --------------------------------------------------------------------------- #
# Named historical figures commonly used in the course corpus.
NAMED_FIGURES = re.compile(
    r"\b(Warburg|Frazer|Tylor|Müller|Mueller|Masuzawa|Buddha|Jesus|Mose|Moses|Muḥammad|Mohammed"
    r"|Weber|Durkheim|Eliade|Grimes|Ebertz|Wach|Dalai Lama|Freud|Marx|Otto|Lévi|Levi-Strauss"
    r"|Gemme?ke|Ibn|Uṣaybi|Asaf|Caleb|Marabout|Parliament)\b",
    re.IGNORECASE,
)
ACTUAL_DATES = re.compile(r"\b(1[5-9]\d\d|20[0-2]\d)\b")
CLAIMS = re.compile(r"\b(Beispiel|Beispiele|bspw\.|z\. ?B\.|exemplarisch|case study)\b", re.IGNORECASE)
PLACE_RE = re.compile(
    r"\b(Hamburg|Florence|Leipzig|Berlin|Bonn|München|Muenchen|Oxford|Dessau|Dakar|Senegal"
    r"|Hawaii|Iron Age|neolithisch|Pueblo|Hopi|Cochiti|New Mexico|Arizona|New York|"
    r"New Testament|Neues Testament|Iran|Ägypten|Aegypten|Rom|Jerusalem|Indien|China)\b",
    re.IGNORECASE,
)
# Stylistic / teaching case figures (fictional-charactor-like concrete props).
STYLISTIC_EXAMPLES = re.compile(
    r"\b(Papierflieger|paper aeroplane|Fußball|Fussball|Medikament|Beeren-Problem|Himbeer-Problem)\b",
    re.IGNORECASE,
)


def score_examples(body: str, fm: str, literature: list[dict]) -> tuple[int, list[dict], dict]:
    evidence: list[dict] = []
    detail: dict[str, int] = {}

    named = list(dict.fromkeys(m.group(0) for m in NAMED_FIGURES.finditer(body)))
    places = list(dict.fromkeys(m.group(0) for m in PLACE_RE.finditer(body)))
    dates = ACTUAL_DATES.findall(body)
    claims = [m.group(0) for m in CLAIMS.finditer(body)]
    stylistic = list(dict.fromkeys(m.group(0) for m in STYLISTIC_EXAMPLES.finditer(body)))

    detail["named_figures"] = len(named)
    detail["places"] = len(places)
    detail["dates"] = len(dates)
    detail["claim_markers"] = len(claims)
    detail["stylistic_examples"] = len(stylistic)
    detail["literature"] = len(literature)

    score = 35.0
    if named:
        score += 12 + 8 * min(len(named), 4)
        evidence.append({
            "kind": "named_figures",
            "snippet": ", ".join(named[:6]),
            "note": f"{len(named)} named historical figure(s)/school(s)",
        })
    if places:
        score += 6
        evidence.append({
            "kind": "places",
            "snippet": ", ".join(places[:6]),
            "note": f"{len(places)} specific place reference(s) contextualising examples",
        })
    if dates:
        score += 4
        evidence.append({"kind": "dates", "snippet": dates[0], "note": f"{len(dates)} dated/era reference(s)"})
    if claims:
        score += 6
        evidence.append({"kind": "claim_markers", "snippet": claims[0], "note": "Explicit example/claim markers (Beispiel, z. B.)"})
    if stylistic:
        score += 15
        evidence.append({
            "kind": "stylistic_example",
            "snippet": ", ".join(stylistic),
            "note": "Stylistic / character-like teaching examples present",
        })
    if literature:
        score += 5
        _first_title = next(
            (str(it.get("title") or "").strip() for it in literature
             if isinstance(it, dict) and it.get("title")),
            "",  # no usable title → placeholder
        )
        evidence.append({"kind": "literature",
                         "snippet": (_first_title or "(linked reading)")[:80],
                         "note": f"{len(literature)} linked reading(s) available as example sources"})

    return clip(score), evidence, detail


# --------------------------------------------------------------------------- #
# Area 3 — Images
# --------------------------------------------------------------------------- #
IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)|<img[^>]+src=[\"']([^\"']+)[\"']")
IMG_ROW_RE = re.compile(r"\{\%\s*include\s+img-row\.html[^%]*images=\s*[\"']([^\"']+)[\"']")
FRONT_IMG_RE = re.compile(r"^(?:image|parallaxBackgroundImage)\s*:\s*(.+)$", re.MULTILINE)
CAPTION_RE = re.compile(r"<figcaption>")
HINT_RE = re.compile(
    r"\b(map|karte|portrait|porträt|cover|buchdeckel|drawing|zeichnung|archive|archiv|"
    r"photo|foto|fotografie|abbildung|bild|illustration)\b",
    re.IGNORECASE,
)
# Common metaphor-image categories (book covers / maps / archives / portraits).
def _count_inline(images: list[str]) -> int:
    return len([i for i in images if i and not i.startswith("http")])  # count local assets


def score_images(body: str, fm: str) -> tuple[int, list[dict], dict]:
    evidence: list[dict] = []
    detail: dict[str, int] = {}

    inline = [(m.group(1) or m.group(2)) for m in IMG_RE.finditer(body)]
    inline = [i for i in inline if i]
    rows = [m.group(1) for m in IMG_ROW_RE.finditer(body)]
    front = [m.group(1).strip().strip('"\'') for m in FRONT_IMG_RE.finditer(fm)]
    captions = len(CAPTION_RE.findall(body))

    # flatten all image paths
    all_imgs = list(inline)
    for r in rows:
        all_imgs.extend(x.strip() for x in r.split(",") if x.strip())
    all_imgs = [i for i in all_imgs if i and not i.startswith("{{")]

    detail["inline_images"] = len(inline)
    detail["img_row_includes"] = len(rows)
    detail["front_matter_images"] = len(front)
    detail["figcaptions"] = captions
    detail["total_images"] = len(all_imgs)

    score = 25.0
    if all_imgs:
        score += 12 + 8 * min(len(all_imgs), 4)
        evidence.append({
            "kind": "images",
            "snippet": ", ".join(os.path.basename(p) for p in all_imgs[:6]),
            "note": f"{len(all_imgs)} image(s) present",
        })
    if captions:
        score += 8
        evidence.append({"kind": "figcaption", "snippet": "<figcaption>", "note": f"{captions} figure caption(s) (likely dated/credited images)"})
    if front:
        score += 5
        evidence.append({"kind": "front_image", "snippet": front[0], "note": "hero/parallax image in front matter"})

    # Categorise image types present (covers/portraits/maps/drawings/archives).
    lump = " ".join(all_imgs).lower()
    cats = []
    if any(k in lump for k in ("cover", "buchdeckel")):
        cats.append("book cover")
    if any(k in lump for k in ("portrait", "porträt", "masuzawa.jpg", "warburg-bank")):
        cats.append("portrait")
    if any(k in lump for k in ("map", "karte", "_map_")):
        cats.append("map")
    if any(k in lump for k in ("drawing", "zeichnung", "diagram", "stained-glass")):
        cats.append("drawing/diagram")
    if any(k in lump for k in ("archive", "archiv", "handschrift", "manuscript")):
        cats.append("archive/manuscript")
    detail["image_categories"] = cats
    if cats:
        score += 6 * len(cats)
        evidence.append({"kind": "image_categories", "snippet": ", ".join(cats),
                         "note": "recognised image types: " + ", ".join(cats)})

    return clip(score), evidence, detail


# --------------------------------------------------------------------------- #
# Area 4 — Mental hooks  (metaphors, comparisons, mnemonics, diagrams)
# --------------------------------------------------------------------------- #
ANALOGY_RE = re.compile(
    r"\b(wie ein|wie eine|als (?:wäre|sei|handelte)|vergleichbar|analog zu|analogie|metapher|"
    r"Bild für|bildlich|sozusagen|gleichsam|quasi|ähnlich wie|aehnlich wie|genau wie|"
    r"im übertragenen|übertragenen|uebertragenen)\b",
    re.IGNORECASE,
)
MNEMONIC_RE = re.compile(
    r"\b(Eselsbrücke|Eselsbruecke|Merkregel|Merk|einprägen|mnemotechnisch|akronym|"
    r"drei Ebenen|fünf (?:Punkte|Schritte|Merkmale)|4 ?Schritte|Schema)\b",
    re.IGNORECASE,
)
DIAGRAM_RE = re.compile(r"(mermaid|```mermaid|gruppen-.*\.png|.*diagram.*\.png|draw\.io|Diagramm|Schema,? )", re.IGNORECASE)
PARALLEL_RE = re.compile(r"^[-*]\s+\*\*[A-ZÄÖÜ][^:]{2,40}:\*\*", re.MULTILINE)  # bolded list parallels


def score_mental_hooks(body: str, fm: str) -> tuple[int, list[dict], dict]:
    evidence: list[dict] = []
    detail: dict[str, int] = {}

    analogies = list(dict.fromkeys(m.group(0).strip() for m in ANALOGY_RE.finditer(body)))
    mnemonics = list(dict.fromkeys(m.group(0).strip() for m in MNEMONIC_RE.finditer(body)))
    diagrams = list(dict.fromkeys(m.group(1).strip() for m in DIAGRAM_RE.finditer(body.lower())))
    parallel = len(PARALLEL_RE.findall(body))

    detail["analogies"] = len(analogies)
    detail["mnemonics"] = len(mnemonics)
    detail["diagrams"] = len(diagrams)
    detail["parallel_lists"] = parallel

    score = 25.0
    if analogies:
        score += 20
        evidence.append({
            "kind": "analogy",
            "snippet": analogies[0],
            "note": f"{len(analogies)} metaphor/comparison signal(s) (wie ein / analog zu / …)",
        })
    if mnemonics:
        score += 15
        evidence.append({"kind": "mnemonic", "snippet": mnemonics[0],
                         "note": f"{len(mnemonics)} mnemonic / memorable-structure signal(s)"})
    if diagrams:
        score += 15
        evidence.append({"kind": "diagram", "snippet": diagrams[0],
                         "note": f"{len(diagrams)} diagram signal(s) (mermaid / diagram image / schema)"})
    if parallel:
        score += 10
        evidence.append({"kind": "parallel_list", "snippet": "• **Termin:** …",
                         "note": f"{parallel} bolded parallel list item(s) (structuring mnemonic)"})

    return clip(score), evidence, detail


# --------------------------------------------------------------------------- #
# Area 5 — Thought-provoking  (comics + provocations)
# --------------------------------------------------------------------------- #
COMIC_RE = re.compile(
    r"\b(Calvin & ?Hobbes|Calvin and Hobbes|Vater & ?Sohn|Vater und Sohn|B\.C\.|"
    r"Comic|Cartoon|Karikatur|Karikaturen)\b",
    re.IGNORECASE,
)
PROVOCATION_RE = re.compile(
    r"\b(Würdest du|Wuerdest du|würdigst du|Stell dir vor|Stellen Sie sich vor|"
    r"Was wäre wenn|Was waere wenn|Hältst du|Haelst du|Herausforderung|Widerspruch|"
    r"provokant|Gegenfrage|Umkehrschluss|Was meint.*primitiv|Ist das.*wirklich)\b",
    re.IGNORECASE,
)
RHETORICAL_Q_RE = re.compile(r"(?:Warum|Inwieweit|Inwiefern|Welche|Wieso|Wie können|Wer oder was)\s+[^.?]*\?")


def score_thought_provoking(body: str, fm: str) -> tuple[int, list[dict], dict]:
    evidence: list[dict] = []
    detail: dict[str, int] = {}

    comics = list(dict.fromkeys(m.group(0) for m in COMIC_RE.finditer(body)))
    provocations = list(dict.fromkeys(m.group(0) for m in PROVOCATION_RE.finditer(body)))
    rhq = RHETORICAL_Q_RE.findall(body)

    detail["comics"] = len(comics)
    detail["provocations"] = len(provocations)
    detail["rhetorical_questions"] = len(rhq)

    score = 20.0
    if comics:
        score += 45
        evidence.append({"kind": "comic", "snippet": comics[0],
                         "note": "comic/cartoon present (Calvin & Hobbes / Vater & Sohn / B.C.)"})
    if provocations:
        score += 30
        evidence.append({"kind": "provocation", "snippet": provocations[0],
                         "note": f"{len(provocations)} explicit provocation(s) / devil's-advocate prompt(s)"})
    if rhq:
        score += 15
        evidence.append({"kind": "rhetorical_question", "snippet": rhq[0][:80],
                         "note": f"{len(rhq)} open/rhetorical reflection question(s)"})

    return clip(score), evidence, detail


# --------------------------------------------------------------------------- #
# Area 6 — Language  (German grammar + precise vocabulary)
# --------------------------------------------------------------------------- #
# Curated, high-precision German grammar / typo-flaw patterns (documented).
GRAMMAR_FLAWS = [
    (r"\bentschiedet\b", "entschiedet → entschieden (wrong past-participle form)"),
    (r"\balle Genders\b", "alle Genders → alle Gender (unidiomatic English-style plural)"),
    (r"\bMateriellen\b", "Materiellen → Materialien (word choice / form)"),
    (r"\bFortschitt\b", "Fortschitt → Fortschritt (typo)"),
    (r"\b(?:im|in) der Heilige Geist\b", "der Heilige Geist (article/case)"),
    (r"\bvor eine\b", "vor eine → vor einer/einem (case after preposition)"),
    (r"\bmit eine\b", "mit eine → mit einer/einem (case after preposition)"),
    (r"\bauf dies\b", "auf dies → auf diese/die (demonstrative)"),
    (r"\bder zentrale Rolle\b", "der zentrale Rolle → die zentrale Rolle (case)"),
]
# Precise-vocabulary signals: technical/Fachbegriffe with a gloss (italic + quote,
# or Latin/Greek term), or bracketed definition.
TECH_GLOSS_RE = re.compile(
    r"_[a-zäöüß]+_[, ]+(?:\"|„|‘)|(?:\"|„)[A-Z][^\"„]{0,60}[^\"„]*(?:\"|“)[ ,;]? *(?:\([^)]{1,60}\))?",
)
# German technical terms typical of the course (Wissenschaftssprache).
TECH_TERMS = re.compile(
    r"\b(Fachbegriff|außeralltäglich|ausseralltaeglich|Vergemeinschaftung|Erbcharisma|Amtscharisma|"
    r"Zuschreibung|veralltäglichen|Veralltaeglichung|Legitimation|Ikonographie|Philologie|"
    r"Etymologie|Hermeneutik|Exegese|Religionswissenschaft|Dispositiv|Genealogie|Intertextualität|"
    r"Intertextualitaet|Säkularisierung|Saekularisierung|Naturreligion|Weltreligion|Animismus|"
    r"Synkretismus|Esoterik|Sufismus|tariqa|istikhara|khalwah)\b",
    re.IGNORECASE,
)


def score_language(body: str, fm: str) -> tuple[int, list[dict], dict]:
    evidence: list[dict] = []
    detail: dict[str, int] = {}

    flaws: list[str] = []
    seen: set[str] = set()
    for pat, msg in GRAMMAR_FLAWS:
        for _m in re.finditer(pat, body, re.IGNORECASE):
            if msg in seen:
                continue  # count each distinct flaw kind once, not every occurrence
            seen.add(msg)
            flaws.append(msg)

    tech_gloss = len(TECH_GLOSS_RE.findall(body))
    tech_terms = list(dict.fromkeys(m.group(0) for m in TECH_TERMS.finditer(body)))

    detail["grammar_flaws"] = len(flaws)
    detail["glosses"] = tech_gloss
    detail["tech_terms"] = len(tech_terms)

    score = 52.0  # decent starting point; German decks are generally well-written
    if flaws:
        score -= 30 * min(len(flaws), 3)
        evidence.append({"kind": "grammar_flaw", "snippet": flaws[0],
                         "note": f"{len(flaws)} grammar/typo flaw(s) detected: {'; '.join(flaws[:3])}"})
    else:
        evidence.append({"kind": "grammar_ok", "snippet": "(no pattern hits)",
                         "note": "no curated grammar/typo flaw patterns matched"})
    if tech_terms:
        score += 20
        evidence.append({"kind": "tech_vocab", "snippet": ", ".join(tech_terms[:6]),
                         "note": f"{len(tech_terms)} precise technical term(s) used"})
    if tech_gloss:
        score += 8
        evidence.append({"kind": "gloss", "snippet": "(italic term + gloss)",
                         "note": f"{tech_gloss} term-with-gloss construction(s) (precise vocabulary)"})

    return clip(score), evidence, detail


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
SCORERS = {
    "flow": score_flow,
    "examples": score_examples,
    "images": score_images,
    "mental_hooks": score_mental_hooks,
    "thought_provoking": score_thought_provoking,
    "language": score_language,
}


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def analyze_class(cls: dict, threshold: int = UNDERDEVELOPED_THRESHOLD) -> dict:
    slides_path = cls.get("slides_path")
    notes_path = cls.get("notes_path")
    literature = cls.get("literature") or []

    body, fm = "", ""
    slides_src = None
    notes_body = ""
    if slides_path and os.path.exists(slides_path):
        slides_src = read_text(slides_path)
        fm, body = strip_front_matter(slides_src)
    if notes_path and os.path.exists(notes_path):
        _, notes_body = strip_front_matter(read_text(notes_path))

    # Combine slides body + notes body for scoring (notes rarely add body
    # content but may add example/grammar signals; slides carry the weight).
    combined = body + "\n" + notes_body

    scores: dict[str, int] = {}
    all_evidence: dict[str, list[dict]] = {}
    details: dict[str, dict] = {}
    for key in AREA_KEYS:
        fn = SCORERS[key]
        if key == "examples":
            sc, ev, dt = fn(combined, fm, literature)
        else:
            sc, ev, dt = fn(combined, fm)
        scores[key] = sc
        all_evidence[key] = ev
        details[key] = dt

    # Ranked list of underdeveloped areas (lowest score first).
    ranked = sorted(AREA_KEYS, key=lambda k: scores[k])
    underdeveloped = [(k, scores[k]) for k in ranked if scores[k] < threshold]

    return {
        "course_slug": cls.get("course_slug"),
        "class_id": cls.get("class_id"),
        "title": cls.get("title"),
        "date": cls.get("date"),
        "slides_url": cls.get("slides_url"),
        "slides_path": slides_path,
        "notes_path": notes_path,
        "slides_available": slides_src is not None,
        "sources": {
            "slides": os.path.basename(slides_path) if slides_path else None,
            "notes": os.path.basename(notes_path) if notes_path else None,
            "literature": [l.get("title") for l in literature],
        },
        "scores": scores,
        "evidence": all_evidence,
        "details": details,
        "underdeveloped_threshold": threshold,
        "ranked_underdeveloped": [
            {"area": k, "score": scores[k], "label": AREA_LABELS[k]} for k, _ in underdeveloped
        ],
        "ranked_all": [
            {"area": k, "score": scores[k], "label": AREA_LABELS[k]} for k in ranked
        ],
    }


def analyze(input_path: str, threshold: int = UNDERDEVELOPED_THRESHOLD) -> dict:
    with open(input_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    class_results = [analyze_class(c, threshold=threshold) for c in data.get("classes", [])]
    return {
        "analyzer_version": "1.0.0",
        "input_file": str(input_path),
        "generated_at": data.get("generated_at"),
        "as_of": data.get("as_of"),
        "window_start": data.get("window_start"),
        "window_end": data.get("window_end"),
        "count": len(class_results),
        "underdeveloped_threshold": threshold,
        "classes": class_results,
    }


def load_config(config_path: Path) -> dict:
    """Load config.yml. Returns {'input', 'outdir', 'threshold'}, falling back
    to defaults; missing config file is not an error (defaults apply)."""
    cfg = {"input": str(DEFAULT_INPUT),
           "outdir": str(DEFAULT_OUTPUT),
           "threshold": UNDERDEVELOPED_THRESHOLD}
    if config_path.exists():
        try:
            import yaml
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            cwd = config_path.resolve().parent
            if data.get("input_json"):
                cfg["input"] = str((cwd / data["input_json"]).resolve())
            if data.get("output_dir"):
                cfg["outdir"] = str((cwd / data["output_dir"]).resolve())
            if data.get("underdeveloped_threshold") is not None:
                cfg["threshold"] = int(data["underdeveloped_threshold"])
        except Exception as exc:  # noqa: BLE001
            print(f"warning: could not read {config_path}: {exc}", file=sys.stderr)
    return cfg


def main(argv=None) -> int:
    config_path = Path(__file__).resolve().parent / "config.yml"
    cfg = load_config(config_path)
    ap = argparse.ArgumentParser(description="Score course slides across six pedagogical areas.")
    ap.add_argument("--input", default=cfg["input"],
                    help="Path to fetcher JSON (default: config.yml input_json / fetcher latest.json)")
    ap.add_argument("--outdir", default=cfg["outdir"], help="Output directory for JSON")
    ap.add_argument("--threshold", type=int, default=cfg["threshold"],
                    help="Underdeveloped cutoff (default from config.yml)")
    ap.add_argument("--dry-run", action="store_true", help="Print to stdout, write nothing")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print score tables per class")
    args = ap.parse_args(argv)

    result = analyze(args.input, threshold=args.threshold)

    if args.pretty:
        for c in result["classes"]:
            print(f"\n=== {c['title']} ({c['date']}) [{c['class_id']}] ===")
            for r in c["ranked_all"]:
                print(f"  {r['label']:<18} {r['score']:>3}")
            if c["ranked_underdeveloped"]:
                print("  UNDERDEVELOPED: " + ", ".join(
                    f"{r['label']} ({r['score']})" for r in c["ranked_underdeveloped"]))
            else:
                print("  UNDERDEVELOPED: none")
    else:
        if args.dry_run:
            print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.dry_run:
        os.makedirs(args.outdir, exist_ok=True)
        out_path = Path(args.outdir) / "analysis.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
