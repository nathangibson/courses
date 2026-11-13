#!/usr/bin/env python3
"""Instantiate a new course for npgibson.com/courses.

Creates a Jekyll collection course in the consolidated courses repo:
  _course_<slug>/            session docs, paired reveal slide decks, static pages
  _data/course_<slug>/       settings.yml, zotero.yaml, glossary.csv
  _config.yml                course_<slug> collection entry

Three input modes (later modes fill only what earlier ones left missing):
  1. CLI flags            --slug 26ki --title "..." --n 12 --start 2026-10-19 ...
  2. --spec <file>.yaml   YAML file with the same keys (see new_course_spec.example.yaml)
  3. Interactive prompts  asks for whatever is still missing (manual use)

Also usable as the backbone of a CI job: pass --yes with flags or a spec file.

Examples:
  python3 scripts/new_course.py                       # fully interactive
  python3 scripts/new_course.py --spec my_course.yaml --commit
  python3 scripts/new_course.py --slug 26test --n 2 --start 2027-01-11 --yes

Default (no --commit): leaves everything uncommitted for review, and prints the
suggested commit command.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Set

DEFAULT_REPO = "/Users/nathan/git/Github/nathangibson/courses"

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "mär": 3, "mai": 5, "okt": 10, "dez": 12, "jän": 1,
}

# ---------------------------------------------------------------------------
# CourseSpec
# ---------------------------------------------------------------------------


class CourseSpec:
    """All answers needed to instantiate a course."""

    def __init__(self) -> None:
        self.slug: str = ""             # e.g. 26ki  (collection: course_26ki)
        self.title: str = ""            # e.g. Einführung in die Religionswissenschaft
        self.description: str = ""      # long description for the course card
        self.language: str = "de"       # en | de  (session-page headings)
        self.type: str = "lecture"      # lecture | seminar
        self.semester: str = "winter"   # winter | summer
        self.year: int = 0              # start year, e.g. 2026 => WS 2026/27
        self.hero: str = "candle.jpg"   # hero image from assets/img
        self.n_sessions: int = 0        # how many sessions the course has
        self.start: str = ""            # ISO date of the FIRST session
        self.freq: str = "weekly"       # weekly | biweekly
        self.holidays: str = ""         # free-form text (parsed by parse_holidays)
        self.first_deck_date: str = ""  # deck date if different from session date
        self.commit: bool = False       # git-commit the result
        self.force: bool = False        # overwrite existing course dirs
        self.yes: bool = False          # never prompt (CI / agent mode)

    REQUIRED = ("slug", "title", "n_sessions", "start")

    def missing_required(self) -> List[str]:
        out = []
        if not self.slug:
            out.append("slug (--slug)")
        if not self.title:
            out.append("title (--title)")
        if not self.n_sessions:
            out.append("number of sessions (--n)")
        if not self.start:
            out.append("start date (--start)")
        return out

    def parsed_start(self) -> dt.date:
        return dt.date.fromisoformat(self.start)

    def parsed_first_deck_date(self) -> Optional[dt.date]:
        if not self.first_deck_date:
            return None
        return dt.date.fromisoformat(self.first_deck_date)

    def collection_name(self) -> str:
        return f"course_{self.slug}"

    def course_dir(self, repo: Path) -> Path:
        return repo / f"_course_{self.slug}"

    def data_dir(self, repo: Path) -> Path:
        return repo / "_data" / self.collection_name()

    def year_str(self) -> str:
        return str(self.year) if self.year else str(self.parsed_start().year)

    def semester_hint(self) -> str:
        """Semester wording for the settings.yml description comment."""
        if self.semester == "summer":
            return f"summer semester {self.year_str()}"
        next_year = self.parsed_start().year + 1
        return f"winter semester {self.year_str()}/{str(next_year)[-2:]}"

    def validate(self) -> None:
        problems = []
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", self.slug):
            problems.append(
                f"slug '{self.slug}' must be lowercase letters/digits/hyphens "
                "(it becomes the Jekyll collection name course_<slug> and the URL path)"
            )
        try:
            self.parsed_start()
        except ValueError:
            problems.append(f"start date '{self.start}' is not an ISO date (YYYY-MM-DD)")
        if self.first_deck_date:
            try:
                self.parsed_first_deck_date()
            except ValueError:
                problems.append(f"first-deck-date '{self.first_deck_date}' is not an ISO date (YYYY-MM-DD)")
        if self.n_sessions and not 1 <= int(self.n_sessions) <= 60:
            problems.append("number of sessions must be between 1 and 60")
        if self.freq not in ("weekly", "biweekly"):
            problems.append(f"freq must be weekly|biweekly, not '{self.freq}'")
        if self.language not in ("en", "de"):
            problems.append(f"language must be en|de, not '{self.language}'")
        if self.type not in ("lecture", "seminar"):
            problems.append(f"type must be lecture|seminar, not '{self.type}'")
        if self.semester not in ("winter", "summer"):
            problems.append(f"semester must be winter|summer, not '{self.semester}'")
        if problems:
            raise SystemExit("Invalid course specification:\n  - " + "\n  - ".join(problems))


# ---------------------------------------------------------------------------
# Minimal YAML writing (stdlib only — no PyYAML in CI)
# ---------------------------------------------------------------------------

_YAML_RISKY = re.compile(r"[:#{}\[\],&*?|>'\"%@`]")


def yq(s: str) -> str:
    """Quote a string for YAML output when it contains anything risky."""
    if s == "":
        return '""'
    needs_quoting = (
        bool(_YAML_RISKY.search(s))
        or s != s.strip()
        or s.lower() in ("true", "false", "null", "yes", "no", "on", "off", "~")
        or re.fullmatch(r"[-?\d].*", s) is not None
    )
    if needs_quoting:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


def dump_inline(value) -> str:
    """YAML scalar, inline (for `key: value` lines)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return yq(value)
    if value is None:
        return '""'
    raise TypeError(f"cannot serialize inline {type(value)}")


# ---------------------------------------------------------------------------
# Holiday parsing
# ---------------------------------------------------------------------------

_ISO = r"\d{4}-\d{1,2}-\d{1,2}"
_DE = r"\d{1,2}\.\d{1,2}\.\d{4}"


def _parse_date_token(t: str, anchor: dt.date) -> Optional[dt.date]:
    """Parse one date token: ISO, German-style, or '21 Dec'/'Dec 21'/'6. Januar'."""
    t = t.strip().rstrip(".,;")
    if not t:
        return None
    m = re.fullmatch(_ISO, t)
    if m:
        try:
            return dt.date.fromisoformat(t)
        except ValueError:
            return None
    m = re.fullmatch(_DE, t)
    if m:
        d, mo, y = t.split(".")
        try:
            return dt.date(int(y), int(mo), int(d))
        except ValueError:
            return None
    # month-name forms: "21 Dec" / "21. Dezember" / "Dec 21"
    m = re.fullmatch(r"(?:(\d{1,2})\.?\s+)?([A-Za-zÄäÖöÜüäJjMmSsOoNnDd]+)\.?(?:\s+(\d{1,2}))?", t)
    if m:
        day = m[1] or m[3]
        mon = m[2].lower()[:3]
        if day and mon in MONTHS:
            month = MONTHS[mon]
            d_int = int(day)
            # no year given: choose the candidate year (anchor.year, +1, -1)
            # closest to the course start
            best = None
            for y in (anchor.year, anchor.year + 1, anchor.year - 1):
                try:
                    cand = dt.date(y, month, d_int)
                except ValueError:
                    continue
                if best is None or abs((cand - anchor).days) < abs((best - anchor).days):
                    best = cand
            return best
    return None


def parse_holidays(text: str, anchor: dt.date) -> List[str]:
    """Parse free-form holiday text into a sorted list of ISO date strings.

    Understands, line- or comma-separated, in any order:
      2026-12-18..2027-01-11      ISO range (.., to, until, bis, -)
      24.12.2026 - 06.01.2027     German-style range
      21 Dec - 6 Jan              month-name range (year inferred from --start)
      2026-12-18                  single date
      Christmas: 21.12.2026-6.1.2027   leading name labels are ignored
    """
    dates: Set[str] = set()
    text = (text or "").strip()
    if not text:
        return []

    def add_range(a: Optional[dt.date], b: Optional[dt.date]) -> None:
        if a and b:
            if b < a:
                a, b = b, a
            d = a
            while d <= b:
                dates.add(d.isoformat())
                d += dt.timedelta(days=1)
        else:
            for x in (a, b):
                if x:
                    dates.add(x.isoformat())

    for chunk in re.split(r"[,\n;]+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        # strip a leading name label like "Christmas:" or "Weihnachten:"
        chunk = re.sub(r"^[A-Za-zÄäÖöÜüß]+(?:\s[A-Za-zÄäÖöÜüß]+)*:\s*", "", chunk).strip()
        if not chunk:
            continue

        # ISO range
        m = re.search(rf"({_ISO})\s*(?:\.\.|to|until|bis|-|–)\s*({_ISO})", chunk)
        if m:
            add_range(_parse_date_token(m[1], anchor), _parse_date_token(m[2], anchor))
            continue
        # German-style range
        m = re.search(rf"({_DE})\s*(?:-|–|bis|to|until)\s*({_DE})", chunk)
        if m:
            add_range(_parse_date_token(m[1], anchor), _parse_date_token(m[2], anchor))
            continue
        # month-name range: 21 Dec - 6 Jan / 21. Dezember bis 6. Januar
        m = re.search(
            r"(\d{1,2}\.?\s+[A-Za-zÄäÖöÜüß]+|[A-Za-zÄäÖöÜüß]+\s+\d{1,2})"
            r"\s*(?:-|–|to|until|bis)\s*"
            r"(\d{1,2}\.?\s+[A-Za-zÄäÖöÜüß]+|[A-Za-zÄäÖöÜüß]+\s+\d{1,2})",
            chunk,
        )
        if m:
            add_range(_parse_date_token(m[1], anchor), _parse_date_token(m[2], anchor))
            continue
        # single token(s)
        for token in chunk.split():
            d = _parse_date_token(token, anchor)
            if d:
                dates.add(d.isoformat())

    return sorted(dates)


# ---------------------------------------------------------------------------
# Session scheduling
# ---------------------------------------------------------------------------


def schedule_sessions(spec: CourseSpec) -> List[dict]:
    """Return a list of session dicts: {n, date (date), iso, is_skipped}.

    Sessions fall on the cadence (weekly/biweekly) from the start date;
    holidays push the affected session to the next free cadence slot.
    """
    anchor = spec.parsed_start()
    holidays = set(parse_holidays(spec.holidays, anchor))
    step = 14 if spec.freq == "biweekly" else 7

    sessions = []
    n = 0
    d = anchor
    while n < spec.n_sessions:
        iso = d.isoformat()
        if iso in holidays:
            d += dt.timedelta(days=step)
            continue
        n += 1
        sessions.append({
            "n": n,
            "date": d,
            "iso": iso,
        })
        d += dt.timedelta(days=step)
    return sessions


# ---------------------------------------------------------------------------
# Templates (modeled on the 26geschichte / 26comm courses)
# ---------------------------------------------------------------------------

STATIC_PAGES = {
    # filename: (layout, title, extra front matter, body)
    "index.md": ("course-home", "__TITLE__", "", ""),
    "about.md": ("page", "About", "", ""),
    "glossary.md": (
        "glossary",
        "Glossary",
        "image_attribution: 'Image: Generated by Microsoft Designer from the prompt. \"Classic picture of a glossary.\"'\n",
        "{% include course-data.html %}\n"
        "{% for row in course_glossary %}\n"
        "| {{ row.term }} | {{ row.definition }} | {{ row.sessionname }} |\n"
        "{% endfor %}\n",
    ),
    "resources.md": ("category", "Learning Resources", "category: resources\n", ""),
    "documentation.md": ("category", "Documentation", "category: documentation\n", ""),
    "sample-posts.md": ("category", "Sample Posts", "category: sample\n", ""),
    "review.md": ("default", "Überblick", "", "## Überblick\n"),
    "podcast.md": (
        "default",
        "Podcast",
        "",
        '<div class="post-content">\n'
        "<h1>{{ page.title }}</h1>\n"
        "\n"
        "Podcast episodes will appear here.\n"
        "\n"
        'To subscribe to this podcast, go to your podcast player and choose "Subscribe with URL" (or similar). Then paste this URL there: {{ site.url }}{{ site.baseurl }}/podcast.xml\n'
        "\n"
        "{% for entry in site.podcasts %}\n"
        "  <article>\n"
        '    <h2><a href="{{ entry.url }}">{{ entry.title }}</a></h2>\n'
        "    <p>{{ entry.short_description }}</p>\n"
        "  </article>\n"
        "{% endfor %}\n"
        "</div>\n",
    ),
    # redirect pages (extra = the redirect target key)
    "olat.md": ("redirect", "OLAT", "redirect: https://olat-ce.server.uni-frankfurt.de/  # TODO set the OLAT repository entry\n", ""),
    "pad.md": ("redirect", "Etherpad", "redirect: https://etherpad.studiumdigitale.uni-frankfurt.de/p/__SLUG__\n", ""),
    "poll.md": ("redirect", "Polls", "redirect: https://partici.fi/  # TODO set the Particify poll ID\n", ""),
    "zotero.md": ("redirect", "Zotero", "redirect: https://zotero.org/groups/__SLUG__/library\n", ""),
    "chat.md": ("redirect", "Rocket Chat", "redirect: https://chat.studiumdigitale.uni-frankfurt.de/channel/__SLUG__  # TODO set the chat channel\n", ""),
    "files.md": ("redirect", "Files", "redirect: https://next.hessenbox.de/  # TODO set the files share link\n", ""),
}


def static_page_text(slug: str, title: str, filename: str) -> str:
    layout, page_title, extra, body = STATIC_PAGES[filename]
    extra = extra.replace("__SLUG__", slug)
    fm = [
        "---",
        f"layout: {layout}",
        f"title: {yq(page_title)}",
        f"permalink: /{slug}/{''.join(filename.split('.')[:-1])}",
    ]
    if extra:
        fm.append(extra.rstrip("\n"))
    fm.append("---")
    text = "\n".join(fm) + "\n"
    if body:
        text += "\n" + body
    return text


def session_doc_text(session: dict, spec: CourseSpec) -> str:
    """YYYY-MM-DD-N.md — layout: post, front matter mirrors 26geschichte/26comm."""
    n = session["n"]
    iso = session["iso"]
    lines = [
        "---",
        "layout: post",
        f"session: {n}",
        "tags:",
        f"  - {n}",
        "level: overview",
        "year:",
        "month:",
        f"date: {iso}",
        "unit: TODO unit",
        "topic: TODO topic",
        "long-topic: TODO long topic",
        "image:",
        "zotero-readings:",
        "objective:",
        "Leitfrage:",
        "concepts:",
        f"zotero-tag: {n}-TODO",
        "---",
    ]
    return "\n".join(lines) + "\n"


def slides_text(session: dict, spec: CourseSpec, deck_date: str) -> str:
    """YYYY-MM-DD-N-slides.md — layout: reveal, blank deck body."""
    n = session["n"]
    image = spec.hero
    lines = [
        "---",
        "layout: reveal",
        f"title: TODO title for session {n}",
        "author: Nathan Gibson",
        f"session: {n}",
        "tags:",
        f"category: slides",
        f"image: {image}",
        f"parallaxBackgroundImage: assets/img/{image}",
        f"date: {deck_date}",
        "---",
        "",
        f"# TODO slides for session {n}",
        "",
    ]
    return "\n".join(lines) + "\n"


def settings_yml_text(spec: CourseSpec) -> str:
    """Per-course data settings.yml — mirrors _data/course_26geschichte/settings.yml."""
    slug = spec.slug
    return f"""# Change 'comments' to true for Disqus comments
disqus:
  comments: false
  disqus_shortname: "millennial-3"

# Course identity (shown in the header/menu bar and footer)
title: {yq(spec.title)}
description: {yq(spec.description or spec.title + " (course website, " + spec.semester_hint() + ")")}

# Session-heading language + type. These select the wording of the session
# detail-page headings via the global config at _data/headings.yml.
language: {yq(spec.language)}            # en | de  (the language of the course's session pages)
type: {yq(spec.type)}           # lecture | seminar  (drives type-specific headings, e.g. readings)

# Semester listing for the courses index (feature/course-index)
semester: {yq(spec.semester)}          # winter | summer
year: {spec.year_str()}                # start year of the academic year (e.g. 2026 => WS 2026/27)
hero: {yq(spec.hero)}        # hero image for the courses index (from assets/img)

# If you are not using Google Analytics, please change 'google-ID' to an empty string
google-ID: ""

# To change the external link values for the below, do so in the pages directory, where their redirects live.

menu:
  - {{ name: "Files", url: "files" }}
  - {{ name: "Zotero", url: "zotero" }}
  - {{ name: "Etherpad", url: "pad" }}
  - {{ name: "Polls", url: "poll" }}
  - {{ name: "OLAT", url: "olat" }}
#  - {{ name: "Chat", url: "chat" }}
#  - {{ name: "Podcast", url: "podcast" }}
#  - {{ name: "Rückblick", url: "review" }}

# Available social icons are powered by Font Awesome, so you can use any icon that they offer
social:
# - {{fa-class: 'brands', icon: 'twitter', link:    'https://twitter.com/paululele'}}
# - {{fa-class: 'solid', icon: 'envelope', link:   'mailto:hello@paulle.ca'}}
# - {{icon: 'rss-square', link: 'feed.xml'}}

base-urls:
  pad: 'https://etherpad.studiumdigitale.uni-frankfurt.de/p/{slug}'
  polls: 'https://ars.particify.de/p/TODO/series'  # TODO set the Particify series ID
  zotero: 'https://www.zotero.org/groups/TODO/{slug}'  # TODO set the Zotero group ID

# Customize site text
pagination:
  next_page: "Newer"
  previous_page: "Older"

sharing_button_prompt: "Feel free to share!"

related_posts: 'Related'

post_date_prefix: 'Written on'

cover_image: {yq(spec.hero)}

reveal-slides:
  background-opacity: 0.3
"""


ZOTERO_YAML_STUB = """---
references: []
---
"""

GLOSSARY_CSV_STUB = "term,definition,session,sessionname\n"


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate_course(spec: CourseSpec, repo: Path) -> List[str]:
    """Write all course files; return the list of created paths (as strings)."""
    created: List[str] = []

    course_dir = spec.course_dir(repo)
    data_dir = spec.data_dir(repo)

    if course_dir.exists() or data_dir.exists():
        if not spec.force:
            raise SystemExit(
                f"Course '{spec.slug}' already exists ({course_dir}); "
                "use --force to overwrite."
            )

    course_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # 1. static pages
    for filename in STATIC_PAGES:
        text = static_page_text(spec.slug, spec.title, filename)
        path = course_dir / filename
        path.write_text(text, encoding="utf-8")
        created.append(str(path))

    # 2. session docs + paired slide decks
    sessions = schedule_sessions(spec)
    first_deck = spec.parsed_first_deck_date()
    for session in sessions:
        deck_date = session["iso"]
        if first_deck is not None and session["n"] == 1:
            deck_date = first_deck.isoformat()
        doc_path = course_dir / f"{session['iso']}-{session['n']}.md"
        doc_path.write_text(session_doc_text(session, spec), encoding="utf-8")
        created.append(str(doc_path))
        slides_path = course_dir / f"{deck_date}-{session['n']}-slides.md"
        slides_path.write_text(slides_text(session, spec, deck_date), encoding="utf-8")
        created.append(str(slides_path))

    # 3. per-course data
    settings_path = data_dir / "settings.yml"
    settings_path.write_text(settings_yml_text(spec), encoding="utf-8")
    created.append(str(settings_path))
    zotero_path = data_dir / "zotero.yaml"
    zotero_path.write_text(ZOTERO_YAML_STUB, encoding="utf-8")
    created.append(str(zotero_path))
    glossary_path = data_dir / "glossary.csv"
    glossary_path.write_text(GLOSSARY_CSV_STUB, encoding="utf-8")
    created.append(str(glossary_path))

    return created


def register_collection(spec: CourseSpec, repo: Path) -> bool:
    """Insert the course_<slug> collection into _config.yml. Returns True if changed."""
    config_path = repo / "_config.yml"
    text = config_path.read_text(encoding="utf-8")
    key = spec.collection_name()
    if re.search(rf"^\s+{re.escape(key)}:", text, re.MULTILINE):
        print(f"  _config.yml already registers {key} — skipped")
        return False
    entry = (
        f"  {key}:\n"
        f"    output: true\n"
        f"    permalink: /{spec.slug}/:title\n"
    )
    # insert right after the collections: line (or its comment block)
    pattern = re.compile(r"(?m)^(collections:\n)")
    if pattern.search(text):
        new_text = pattern.sub(lambda m: m.group(1) + entry, text, count=1)
    else:
        raise SystemExit(f"Could not find 'collections:' in {config_path}")
    config_path.write_text(new_text, encoding="utf-8")
    return True


def git_commit(spec: CourseSpec, repo: Path, created: List[str], config_changed: bool) -> Optional[str]:
    """Stage the generated files and commit. Returns the commit sha or None."""
    paths = created + (["_config.yml"] if config_changed else [])
    subprocess.run(["git", "add", *paths], cwd=repo, check=True)
    msg = f"Initialized {spec.slug}"
    res = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr, file=sys.stderr)
        return None
    sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    return sha


# ---------------------------------------------------------------------------
# Input resolution: spec file → CLI flags → interactive prompts
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Instantiate a new course for npgibson.com/courses.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples:")[1] if "Examples:" in __doc__ else None,
    )
    p.add_argument("--slug", help="course slug, e.g. 26ki (collection course_26ki, URL /courses/26ki/)")
    p.add_argument("--title", help="course title, e.g. 'Einführung in die Religionswissenschaft'")
    p.add_argument("--description", help="long description for the course card (optional)")
    p.add_argument("--language", default=None, help="en | de (default: de)")
    p.add_argument("--type", dest="type_", default=None, help="lecture | seminar (default: lecture)")
    p.add_argument("--semester", default=None, help="winter | summer (default: winter)")
    p.add_argument("--year", type=int, default=None, help="start year, e.g. 2026 => WS 2026/27 (default: start-date year)")
    p.add_argument("--hero", default=None, help="hero image from assets/img (default: candle.jpg)")
    p.add_argument("--n", type=int, default=None, help="number of sessions")
    p.add_argument("--start", help="ISO date of the FIRST session, YYYY-MM-DD")
    p.add_argument("--freq", default=None, help="weekly | biweekly (default: weekly)")
    p.add_argument("--holidays", help="holidays, free-form: '2026-12-18..2027-01-11, 24.03.2027' etc.")
    p.add_argument("--first-deck-date", help="date for the FIRST slide deck if different from the session date")
    p.add_argument("--commit", action="store_true", help="git-commit the generated course (default: leave uncommitted)")
    p.add_argument("--repo", default=None,
                   help="courses repo root (default: the git repo containing the current directory, falling back to %s)" % DEFAULT_REPO)
    p.add_argument("--spec", help="YAML spec file with any of the above keys (see new_course_spec.example.yaml)")
    p.add_argument("--force", action="store_true", help="overwrite an existing course directory")
    p.add_argument("--yes", action="store_true", help="never prompt; fail if required answers are missing (CI/agent mode)")
    return p


def load_spec_file(path: str) -> dict:
    """Minimal YAML subset reader for the spec file (flat key: value pairs)."""
    values = {}
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not m:
            continue
        key, raw = m[1], m[2].strip()
        # strip surrounding quotes
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1]
        values[key] = raw
    return values


SPEC_KEY_MAP = {
    "slug": "slug", "title": "title", "description": "description",
    "language": "language", "type": "type_", "semester": "semester",
    "year": "year", "hero": "hero", "n": "n_sessions", "n_sessions": "n_sessions",
    "start": "start", "freq": "freq", "holidays": "holidays",
    "first-deck-date": "first_deck_date", "first_deck_date": "first_deck_date",
    "commit": "commit", "force": "force", "yes": "yes",
}


def apply_value(spec: CourseSpec, key: str, raw) -> None:
    if key in ("commit", "force", "yes"):
        setattr(spec, key, bool(raw) or str(raw).lower() in ("true", "yes", "1"))
        return
    if key == "year" or key == "n_sessions":
        setattr(spec, key, int(raw))
        return
    if key == "n":
        spec.n_sessions = int(raw)
        return
    if key == "type_":
        spec.type = str(raw)
        return
    setattr(spec, key, str(raw))


def resolve_inputs(spec: CourseSpec, args) -> None:
    """Fill the spec: CLI flags → spec file → interactive prompts."""
    # 1. spec file first (CLI wins later)
    if args.spec:
        for key, raw in load_spec_file(args.spec).items():
            mapped = SPEC_KEY_MAP.get(key)
            if mapped is None:
                print(f"  (spec file: ignoring unknown key '{key}')")
                continue
            apply_value(spec, mapped, raw)

    # 2. CLI flags override
    for key, mapped in SPEC_KEY_MAP.items():
        if mapped == "n_sessions":
            val = getattr(args, "n", None)
        else:
            val = getattr(args, mapped, None)
        if val is not None and val != "" and not (mapped in ("commit", "force", "yes") and val is False):
            apply_value(spec, mapped, val)
    # store_true flags
    if args.commit:
        spec.commit = True
    if args.force:
        spec.force = True
    if args.yes:
        spec.yes = True

    # 3. interactive prompts for anything still missing
    if not spec.yes:
        if not spec.slug:
            spec.slug = input("Course slug (e.g. 26ki — becomes collection course_26ki and URL /courses/26ki/): ").strip().lower()
        if not spec.title:
            spec.title = input("Course title: ").strip()
        if not spec.description:
            spec.description = input("Short description for the course card (optional, Enter to skip): ").strip()
        if not spec.n_sessions:
            spec.n_sessions = int(input("How many sessions? ").strip())
        if not spec.start:
            spec.start = input("Date of the FIRST session (YYYY-MM-DD): ").strip()
        if not spec.holidays and not _prompted_yes("Holiday breaks to skip? Enter dates/ranges, or Enter for none"):
            spec.holidays = input("  (e.g. 2026-12-18..2027-01-11, 24.03.2027): ").strip()
        if not spec.first_deck_date:
            spec.first_deck_date = input(
                "Date for the FIRST slide deck if different from the session date (Enter = same day): "
            ).strip()
        if args.freq is None and not spec.yes:
            spec.freq = _prompt_choice("Frequency", ["weekly", "biweekly"], "weekly")
        if args.language is None:
            spec.language = _prompt_choice("Language of the session pages", ["de", "en"], "de")
        if args.type_ is None:
            spec.type = _prompt_choice("Course type", ["lecture", "seminar"], "lecture")
        if args.semester is None:
            spec.semester = _prompt_choice("Semester", ["winter", "summer"], "winter")
        if args.hero is None:
            spec.hero = input(f"Hero image from assets/img (Enter = candle.jpg): ").strip() or "candle.jpg"


def _prompted_yes(question: str) -> bool:
    ans = input(f"{question} [y/N]: ").strip().lower()
    return ans in ("y", "yes")


def _prompt_choice(label: str, options: List[str], default: str) -> str:
    opts = "/".join(o if o != default else o.upper() for o in options)
    ans = input(f"{label} [{opts}]: ").strip().lower()
    return ans if ans in options else default


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    args = build_argparser().parse_args(argv)
    spec = CourseSpec()
    resolve_inputs(spec, args)

    missing = spec.missing_required()
    if missing:
        raise SystemExit(
            "Missing required answers: " + ", ".join(missing)
            + "\nProvide them via flags, --spec file, or run interactively (without --yes)."
        )
    # default year from the start date
    if not spec.year:
        spec.year = spec.parsed_start().year
    spec.validate()

    if args.repo:
        repo = Path(args.repo).expanduser().resolve()
    else:
        # default: the git repo containing the current directory (so running
        # from a worktree writes into that worktree, not the main repo),
        # falling back to the historical hardcoded path.
        try:
            top = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"], cwd=".",
                capture_output=True, text=True, check=True).stdout.strip()
            repo = Path(top).resolve()
        except (subprocess.CalledProcessError, FileNotFoundError):
            repo = Path(DEFAULT_REPO).expanduser().resolve()
    if not (repo / "_config.yml").exists():
        raise SystemExit(f"'{repo}' does not look like the courses repo (no _config.yml).")

    # anchor for month-name holiday dates
    global _anchor
    _anchor = spec.parsed_start()

    print(f"\nInstantiating course '{spec.slug}':")
    print(f"  title      : {spec.title}")
    print(f"  sessions   : {spec.n_sessions} ({spec.freq}, from {spec.start})")
    sessions = schedule_sessions(spec)
    print(f"  schedule   : {sessions[0]['iso']} … {sessions[-1]['iso']}")
    if spec.holidays:
        skipped = parse_holidays(spec.holidays, spec.parsed_start())
        print(f"  holidays   : {len(skipped)} date(s) parsed → sessions pushed to the next free slot")
    print(f"  language   : {spec.language} / {spec.type} / {spec.semester} {spec.year_str()}")
    print()

    created = generate_course(spec, repo)
    for p in created:
        print(f"  + {p}")

    config_changed = register_collection(spec, repo)
    if config_changed:
        print(f"  + _config.yml (collection {spec.collection_name()} registered)")

    if spec.commit:
        sha = git_commit(spec, repo, created, config_changed)
        if sha:
            print(f"\nCommitted: {sha} Initialized {spec.slug}")
        else:
            print("\nCommit failed — files are staged for a manual commit.", file=sys.stderr)
    else:
        paths = created + (["_config.yml"] if config_changed else [])
        print(
            "\nLeft uncommitted for review. To commit:\n"
            f"  git add {' '.join(paths)}\n"
            f'  git commit -m "Initialized {spec.slug}"'
        )

    print(
        "\nNext steps:\n"
        f"  1. Fill the TODO fields in _course_{spec.slug}/ (units, topics, objectives)\n"
        f"  2. Fill the TODO base-urls in _data/{spec.collection_name()}/settings.yml (polls, zotero) and the redirect pages\n"
        f"  3. Add a hero image to assets/img/{spec.hero} if not present\n"
        f"  4. jekyll build + site checks: ruby scripts/site_checks/lint.rb"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
