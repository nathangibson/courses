#!/usr/bin/env python3
"""
Course Week Fetcher
===================
Scheduled tool that runs every Tuesday at 07:00 (Hermes cron) and, only while
the current date is inside an active semester, reads the user's consolidated
courses website (a local Jekyll repo) and produces a normalized JSON list of
upcoming classes for the next N days.

For each upcoming class it extracts:
  - class id, course slug, session number
  - title (from the slide deck front matter, else the session topic)
  - date (ISO, from the filename YYYY-MM-DD-<n>)
  - time (optional, from config — front matter stores no wall-clock time)
  - slide deck URL (deployed) and local path
  - session notes path
  - linked literature (resolved from the course's zotero.yaml by citation key)

Output is written to <source>/scripts/course-week-fetcher/data/ as
`classes_<YYYY-MM-DD>--<window_end>.json` plus a `latest.json` pointer, and a
status line is printed to stdout for logs / cron delivery.

Behaviours required by acceptance criteria:
  * Semester guard        -> no processing outside an active semester window;
                             missing classes in the window is also handled.
  * Safe credential use   -> none required (user's public static site / local
                             repo); config holds no secrets.
  * Retries               -> the source read retries with backoff before a run
                             is reported failed.
  * Logging               -> structured appends to <log_file>.
  * Dry run               -> --dry-run does the same work but outputs to stdout
                             and does NOT write data files.
  * No secrets committed  -> data/ and logs/ are gitignored; the script never
                             writes credentials.

Usage:
  python3 course_week_fetcher.py [--config PATH] [--date YYYY-MM-DD]
                                 [--dry-run] [--json]
  --date    override "today" (for testing a specific week; default = system date)
  --dry-run compute and print JSON to stdout without writing data files
  --json    always print the JSON to stdout (even when not --dry-run)
Exit codes: 0 success, 2 out-of-semester (graceful), 3 fetch/config failure.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

SCRIPT_VERSION = "1.0.0"

# Default relative layout when config omits paths.
DEFAULT_OUTPUT_DIR = "scripts/course-week-fetcher/data"
DEFAULT_LOG_FILE = "scripts/course-week-fetcher/logs/fetch.log"

# Matches a session doc name: 2026-11-16-6.md  or  2026-11-16-6-slides.md
_SESSION_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(\d+?)(?:-slides)?\.md$")


class FetcherError(Exception):
    """Raised for fatal, non-retryable configuration errors."""


class SourceUnavailable(Exception):
    """Raised when the source repo cannot be read (retried by the caller)."""


def _log_setup(log_path: Path, verbose: bool) -> logging.Logger:
    logger = logging.getLogger("course_week_fetcher")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%S%z"
    )
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.setLevel(logging.DEBUG)
        logger.addHandler(fh)
    except OSError as exc:  # log failure must not kill the run
        logger.warning("could not open log file %s: %s", log_path, exc)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.addHandler(sh)
    return logger


def _load_yaml(path: Path, logger: logging.Logger) -> Optional[Any]:
    """Load (optionally YAML-frontmatter) file. Returns None on parse/read error."""
    if yaml is None:
        raise FetcherError("PyYAML is required but not installed.")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    # Strip leading Jekyll frontmatter on the fly for .md files if present.
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[1]  # frontmatter block
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        logger.warning("YAML parse failed in %s: %s", path, exc)
        return None


def _load_zotero_map(data_dir: Path, logger: logging.Logger) -> dict[str, dict]:
    """Tolerant Zotero ref map: citation-key -> {id,title,authors,path,url}.

    Uses the course's zotero.yaml. A single malformed record must not lose the
    whole bibliography: if the full document fails to parse, fall back to
    per-record YAML parsing, dropping only the bad records (logged).
    """
    zpath = data_dir / "zotero.yaml"
    if not zpath.exists():
        return {}
    refs = _zotero_refs(zpath, logger)
    out: dict[str, dict] = {}
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        key = ref.get("id") or ref.get("citation-key")
        if not key:
            continue
        authors = []
        for a in ref.get("author", []) or []:
            if isinstance(a, dict):
                authors.append(
                    " ".join(x for x in (a.get("given"), a.get("family")) if x)
                )
        att = ref.get("attachments") or []
        att_path = att[0].get("path") if isinstance(att, list) and att else None
        att_url = att[0].get("url") if isinstance(att, list) and att else None
        out[key] = {
            "id": key,
            "title": ref.get("title"),
            "authors": authors,
            "path": att_path,
            "url": att_url,
        }
    return out


def _zotero_refs(zpath: Path, logger: logging.Logger) -> list:
    """Parse zotero.yaml into a list of reference dicts, tolerating bad records."""
    if yaml is None:
        return []
    try:
        text = zpath.read_text(encoding="utf-8")
    except OSError:
        return []
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[1]
    try:
        doc = yaml.safe_load(text)
        refs = doc.get("references", []) if isinstance(doc, dict) else []
        return refs if isinstance(refs, list) else []
    except yaml.YAMLError as exc:
        logger.warning("zotero.yaml full parse failed (%s); falling back to "
                       "per-record parse", exc)
    # Per-record fallback: records start at column-0 `- id:` lines.
    marker = "\n- id:"
    records: list[dict] = []
    segments = []
    start = 0
    while True:
        idx = text.find(marker, start)
        if idx == -1:
            segments.append(text[start:])
            break
        segments.append(text[start:idx + 1])
        start = idx + 1
    for seg in segments:
        seg = seg.strip()
        if not seg or seg == "-":
            continue
        head = "references:\n"
        try:
            rec = yaml.safe_load(head + seg)
        except yaml.YAMLError:
            logger.warning("dropping malformed zotero record: %s...",
                           seg[:60].replace("\n", " "))
            continue
        if not isinstance(rec, dict):
            continue
        refs = rec.get("references")
        if isinstance(refs, list) and refs and isinstance(refs[0], dict):
            records.append(refs[0])
    return records


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    """Extract Jekyll frontmatter (--- ... --- block) as a dict."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1]) if yaml else None
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def _discover_slugs(source: Path) -> list[str]:
    slugs = []
    if not source.is_dir():
        return slugs
    for child in sorted(source.iterdir()):
        if child.is_dir() and child.name.startswith("_course_"):
            slugs.append(child.name[len("_course_"):])
    return slugs


def _collection_dir(source: Path, slug: str) -> Path:
    return source / f"_course_{slug}"


def _collect_sessions(source: Path, slug: str, logger: logging.Logger) -> list[dict]:
    """Parse all YYYY-MM-DD-<n>[(-slides)].md files in a course collection."""
    coll = _collection_dir(source, slug)
    sessions: dict[tuple[dt.date, int], dict] = {}
    if not coll.is_dir():
        return list(sessions.values())
    for child in sorted(coll.iterdir()):
        m = _SESSION_RE.match(child.name)
        if not m:
            continue
        y, mo, d, n = m.groups()
        date = dt.date(int(y), int(mo), int(d))
        session_num = int(n)
        key = (date, session_num)
        rec = sessions.setdefault(
            key, {"date": date, "session_number": session_num, "is_slides": False}
        )
        if child.name.endswith("-slides.md"):
            rec["is_slides"] = True
            rec["slides_front"] = _parse_frontmatter(child)
            rec["slides_path"] = str(child)
            rec["slides_title"] = rec["slides_front"].get("title")
        else:
            rec["notes_path"] = str(child)
            rec["notes_front"] = _parse_frontmatter(child)
    return list(sessions.values())


def _title_of(rec: dict) -> str:
    t = rec.get("slides_title")
    if t:
        return str(t)
    front = rec.get("notes_front") or {}
    return str(front.get("long-topic") or front.get("topic") or front.get("unit") or "")


def _literature_for(rec: dict, zmap: dict[str, dict]) -> list[dict]:
    front = rec.get("notes_front") or {}
    keys_raw = front.get("zotero-readings") or front.get("readings") or ""
    if isinstance(keys_raw, str):
        keys = [k.strip() for k in re.split(r"[,\s]+", keys_raw) if k.strip()]
    else:
        keys = list(keys_raw)
    out = []
    for k in keys:
        if k in zmap:
            out.append(zmap[k])
        else:  # keep unresolved key as a stub (still useful downstream)
            out.append({"id": k, "title": None, "authors": [], "path": None, "url": None})
    return out


def build_payload(source: Path, cfg: dict, today: dt.date,
                  logger: logging.Logger) -> dict:
    """Compute the normalized JSON payload for the week window around `today`."""
    full_window = int(cfg.get("window_days", 7))
    window_start = today
    window_end = today + dt.timedelta(days=full_window - 1)

    slugs = cfg.get("include_courses") or _discover_slugs(source)
    cap = int(cfg.get("course_cap", 20))
    slugs = [s for s in slugs if isinstance(s, str)][:cap]

    times_cfg = cfg.get("course_times") or {}
    default_time = times_cfg.get("all")
    base_url = str(cfg.get("base_url", "")).rstrip("/")

    classes: list[dict] = []
    seen: set[str] = set()

    for slug in slugs:
        data_dir = source / "_data" / f"course_{slug}"
        zmap = _load_zotero_map(data_dir, logger)
        for rec in _collect_sessions(source, slug, logger):
            date = rec["date"]
            if not (window_start <= date <= window_end):
                continue
            cid = f"{slug}-{date.isoformat()}-{rec['session_number']}"
            if cid in seen:
                continue
            seen.add(cid)
            time_of_day = (
                times_cfg.get(slug, default_time) if isinstance(times_cfg, dict) else None
            )
            slides_url = None
            if base_url and rec.get("is_slides"):
                slides_url = (
                    f"{base_url}/{slug}/{date.isoformat()}-{rec['session_number']}-slides"
                )
            classes.append(
                {
                    "course_slug": slug,
                    "class_id": cid,
                    "session_number": rec["session_number"],
                    "title": _title_of(rec),
                    "date": date.isoformat(),
                    "time": time_of_day,
                    "slides_url": slides_url,
                    "slides_path": rec.get("slides_path"),
                    "notes_path": rec.get("notes_path"),
                    "unit": (rec.get("notes_front") or {}).get("unit"),
                    "topic": (rec.get("notes_front") or {}).get("topic"),
                    "objective": (rec.get("notes_front") or {}).get("objective"),
                    "literature": _literature_for(rec, zmap),
                }
            )

    classes.sort(key=lambda c: (c["date"], c["course_slug"], c["session_number"]))
    payload = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "fetcher_version": SCRIPT_VERSION,
        "as_of": today.isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "window_days": full_window,
        "count": len(classes),
        "classes": classes,
    }
    return payload


def _as_date(v: Any) -> Optional[dt.date]:
    """Accept a datetime.date, a datetime.datetime, or an ISO 'YYYY-MM-DD' string."""
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, str):
        try:
            return dt.date.fromisoformat(v)
        except ValueError:
            return None
    return None


def _in_semester(today: dt.date, semesters: list) -> bool:
    if not semesters:
        return True  # no configured windows => rely on per-course + absence fallback
    for sem in semesters:
        s = _as_date(sem.get("start"))
        e = _as_date(sem.get("end"))
        if s and e and s <= today <= e:
            return True
    return False


def run(cfg_path: str, today: dt.date, dry_run: bool, always_json: bool) -> int:
    if yaml is None:
        print("FATAL: PyYAML required but not installed", file=sys.stderr)
        return 3
    try:
        cfg = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8")) or {}
    except OSError as exc:
        print(f"FATAL: cannot read config {cfg_path}: {exc}", file=sys.stderr)
        return 3

    source_raw = cfg.get("source")
    if not source_raw:
        print("FATAL: config must set 'source' (the courses repo path)", file=sys.stderr)
        return 3
    source = Path(source_raw).expanduser()

    rel_out = cfg.get("output_dir", DEFAULT_OUTPUT_DIR)
    log_rel = cfg.get("log_file", DEFAULT_LOG_FILE)
    logger = _log_setup(source / log_rel, verbose=dry_run)
    logger.info("course-week-fetcher %s start (date=%s dry_run=%s)",
                SCRIPT_VERSION, today.isoformat(), dry_run)

    # --- Semester guard -----------------------------------------------------
    if not _in_semester(today, cfg.get("semesters") or []):
        logger.info("today %s is outside all configured semester windows; "
                    "skipping (out_of_semester)", today.isoformat())
        print(json.dumps({
            "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "fetcher_version": SCRIPT_VERSION,
            "status": "out_of_semester",
            "as_of": today.isoformat(),
            "count": 0,
            "classes": [],
        }, ensure_ascii=False, indent=2))
        return 2

    # --- Fetch with retries -------------------------------------------------
    attempts = int((cfg.get("retry") or {}).get("max_attempts", 3))
    backoff = float((cfg.get("retry") or {}).get("backoff_seconds", 5))
    payload = None
    for attempt in range(1, attempts + 1):
        try:
            if not source.is_dir():
                raise SourceUnavailable(f"source dir missing: {source}")
            payload = build_payload(source, cfg, today, logger)
            break
        except SourceUnavailable as exc:
            logger.warning("attempt %d/%d failed: %s", attempt, attempts, exc)
            if attempt < attempts:
                time.sleep(backoff)
    if payload is None:
        logger.error("source fetch failed after %d attempts; run FAILED", attempts)
        print(f"ERROR: could not fetch courses from {source} after {attempts} attempts",
              file=sys.stderr)
        return 3

    # --- Write output (unless dry-run) -------------------------------------
    out_text = json.dumps(payload, ensure_ascii=False, indent=2)
    if dry_run:
        print(out_text)
        logger.info("dry-run: %d class(es) in window %s..%s",
                    payload["count"], payload["window_start"], payload["window_end"])
        return 0

    out_dir = source / rel_out
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        fname = f"classes_{payload['window_start']}--{payload['window_end']}.json"
        (out_dir / fname).write_text(out_text, encoding="utf-8")
        (out_dir / "latest.json").write_text(out_text, encoding="utf-8")
    except OSError as exc:
        logger.error("could not write output: %s", exc)
        print(f"ERROR: could not write output: {exc}", file=sys.stderr)
        return 3

    logger.info("wrote %d class(es) to %s", payload["count"], out_dir)
    if payload["count"] == 0:
        logger.info("no classes found in window %s..%s (absence guard)",
                    payload["window_start"], payload["window_end"])
        if always_json:
            print(out_text)
        else:
            print(f"OK: 0 classes in window (absence guard); {out_dir / fname}")
        return 0
    if always_json:
        print(out_text)
    else:
        print(f"OK: {payload['count']} classes -> {out_dir / fname}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Course Week Fetcher")
    ap.add_argument("--config", default="config.yml",
                    help="path to config.yml (default ./config.yml)")
    ap.add_argument("--date", default=None,
                    help="override 'today' as YYYY-MM-DD (for testing)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute and print JSON to stdout; write nothing")
    ap.add_argument("--json", action="store_true",
                    help="always print JSON to stdout")
    args = ap.parse_args(argv)

    today = dt.date.today()
    if args.date:
        try:
            today = dt.date.fromisoformat(args.date)
        except ValueError:
            print(f"FATAL: bad --date {args.date!r}; expected YYYY-MM-DD", file=sys.stderr)
            return 3
    return run(args.config, today, args.dry_run, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
