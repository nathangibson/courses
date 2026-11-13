# Course Week Fetcher

Reads the consolidated courses website (the local Jekyll repo at
`/Users/nathan/git/Github/nathangibson/courses`, deployed at
`https://npgibson.com/courses`) and emits a **normalized JSON list of the
user's upcoming classes for the next N days** (default 7), one record per
upcoming class.

Created for kanban task `t_759e5f7e` (Tuesday cron + course-week fetcher). It
is the data-feed for the downstream Tuesday class-prep workflow: the
`story-expert` analyzer (`t_f2559172`) consumes this JSON to score each
class's slides across six areas, and the integration task (`t_fcd06286`) wires
it into a single Tuesday morning job.

## Why no credentials

The "courses website" is the user's own public static site. Its source of
truth is a **local git repo** the agent already has read access to. So the
fetcher reads the repo directly — no password, cookie, or session. **There is
no secret to store or leak.** If the configured source path is missing or a
course dir is unreadable, the run retries then fails with a clear log (see
Failure behaviour).

## What it extracts, per upcoming class

| Field          | Meaning                                                        |
|----------------|----------------------------------------------------------------|
| `course_slug`  | Jekyll collection slug, e.g. `26rw`                            |
| `class_id`     | `<slug>-<date>-<n>` (unique, deterministic)                    |
| `session_number` | `n` from the filename `YYYY-MM-DD-<n>`                        |
| `title`        | slide-deck `title` front matter, else session topic/long-topic |
| `date`         | ISO `YYYY-MM-DD`, taken from the filename                      |
| `time`         | `HH:MM` from `config.yml: course_times` (front matter stores no time); `null` if unknown |
| `slides_url`   | deployed URL to the reveal deck (from `base_url`)              |
| `slides_path`  | absolute path to the `-slides.md` deck in the repo             |
| `notes_path`   | absolute path to the session `YYYY-MM-DD-<n>.md` doc           |
| `unit` / `topic` / `objective` | session front-matter fields                        |
| `literature`   | list `{id,title,authors,path,url}` resolved from the course's `zotero.yaml` by the `zotero-readings` citation key |

## Semester guard

Two complementary guards:

1. **Configured windows** — `config.yml: semesters` (`[start, end]`, inclusive).
   Outside every window the job exits cleanly with a `status:
   "out_of_semester"` payload and **does not schedule or store anything**.
   Dates are edited once per semester.
2. **Absence of classes** — even inside a semester, if no session falls in the
   window, the run succeeds with `count: 0` and logs an `absence guard` note.
   This also covers weeks with no teaching (e.g. breaks).

## Usage

Requires the Hermes dependency venv's python (`3.13`, has `yaml` and
`requests`): `/Users/nathan/.hermes/hermes-agent/venv/bin/python3`.

```bash
cd /Users/nathan/git/Github/nathangibson/courses/scripts/course-week-fetcher

# Real run: writes data/classes_<start>--<end>.json and data/latest.json
$PY python3 course_week_fetcher.py

# Dry run: print JSON to stdout, write nothing
$PY python3 course_week_fetcher.py --dry-run

# Test a specific week (semester guard / window logic)
$PY python3 course_week_fetcher.py --dry-run --date 2026-11-10

# Missing-source / site-outage simulation
$PY python3 course_week_fetcher.py --config <bad-source-config.yml> --dry-run
```

where `$PY=/Users/nathan/.hermes/hermes-agent/venv/bin/python3`.

Exit codes: `0` success · `2` out-of-semester (graceful) · `3` config/source
failure.

Logs append to `logs/fetch.log` (configure via `log_file`).

## Retries, logging, failure behaviour

- **Retries** — the source read retries `retry.max_attempts` times with
  `retry.backoff_seconds` backoff before a run is reported failed. On final
  failure it logs `ERROR … run FAILED` and exits `3` with a clear stderr line
  (`ERROR: could not fetch courses from <path> after N attempts`).
- **Tolerant literature parsing** — a malformed record in any course's
  `zotero.yaml` does not lose the whole bibliography: the loader falls back to
  per-record YAML parsing and logs the dropped record. (Known: the `James,
  Varieties of Religious Experience (1902)` record in `course_26rw` contains an
  invalid YAML escape; it is skipped, everything else resolves.)
- **No secrets committed** — `data/` and `logs/` are `.gitignore`d in this
  directory; the generated JSON contains only course metadata.

## Scheduled job (Hermes cron)

A Hermes cron job runs the fetcher **every Tuesday 07:00 local**. Because
Hermes cron `script` jobs are validated to live inside the owning profile's
`scripts/` dir, a thin wrapper at
`~/.hermes/profiles/tech-support/scripts/course-week-fetcher.sh` invokes the
real fetcher here. The script (and the fetch) enforce the semester guard, so a
manual `crontab` invocation is equally safe.

Manage with:

```bash
hermes -p tech-support cron list
hermes -p tech-support cron run <id>     # fire now (see note)
```

> Note: `hermes cron run` fires on the next scheduler tick; to execute
> immediately run the wrapper (or the fetcher) directly as shown above.

## JSON schema contract (for downstream consumers)

```jsonc
{
  "generated_at": "ISO8601",
  "fetcher_version": "1.0.0",
  "as_of": "2026-11-10",
  "window_start": "2026-11-10",
  "window_end": "2026-11-16",
  "window_days": 7,
  "count": 3,
  "classes": [
    {
      "course_slug": "26rw",
      "class_id": "26rw-2026-11-16-6",
      "session_number": 6,
      "title": "…",
      "date": "2026-11-16",
      "time": "10:00",
      "slides_url": "https://npgibson.com/courses/26rw/2026-11-16-6-slides",
      "slides_path": "/…/courses/_course_26rw/2026-11-16-6-slides.md",
      "notes_path": "/…/courses/_course_26rw/2026-11-16-6.md",
      "unit": "…", "topic": "…", "objective": "…",
      "literature": [{ "id": "…", "title": "…", "authors": ["…"], "path": "…", "url": "…" }]
    }
  ]
}
```
