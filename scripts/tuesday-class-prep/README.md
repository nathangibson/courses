# Tuesday Class-Prep Pipeline — end-to-end orchestrator

Chains the four verified stage components into a single Tuesday-morning job:

```
fetch ──▶ analyze ──▶ generate ──▶ send
(weekly   (score 6   (top-3 area   (Buzz alert,
 classes)  areas)     questions)    idempotent)
```

This is the integration layer for kanban **t_fcd06286** ("Integrate Tuesday
class-prep workflow end-to-end"). It is the *only* thing a cron job / human
needs to call each Tuesday.

The four stages live in their own sibling dirs and are **not** modified here:

| Stage                | Script                                      | Output                     |
|----------------------|---------------------------------------------|----------------------------|
| 1. Fetch next week   | `../course-week-fetcher/course_week_fetcher.py`  | `../course-week-fetcher/data/latest.json` |
| 2. Analyze slides    | `../course-slide-analyzer/course_slide_analyzer.py` | `../course-slide-analyzer/data/analysis.json` |
| 3. Generate questions| `../course-question-generator/question_generator.py` | `../course-question-generator/data/questions.json` |
| 4. Send the alert    | `~/git/git-local/buzz/deploy/tuesday_alert/tuesday_alert.py send <questions.json>` | Buzz home channel |

## Single config file

`config.yml` here is the ONE integration config and owns the four operational
knobs the task requires:

* **semester dates** — `semesters:` (inclusive `[start,end]`); outside every
  window the pipeline logs a graceful note and sends nothing.
* **courses-website access** — `courses:` (source repo + base URL). The site is
  the user's own public static repo, so **no credentials are needed**; this is
  where credentials would be added if it ever moved behind auth.
* **alert channel** — `alert:` (home channel, relay, sender identity, retries).
* **question limits** — `questions:` (`max_per_class`, `underdeveloped_threshold`).

The stage dirs also keep their own directory-local `config.yml` for internal
defaults; keep this integration config's `semesters` / `questions` in sync when
you change them.

## Usage

```bash
PY=/Users/nathan/.hermes/hermes-agent/venv/bin/python3
cd scripts/tuesday-class-prep

# Real Tuesday run (what the cron does) — fetch→analyze→generate→send
$PY pipeline.py --config config.yml

# Same-day re-run is a no-op (idempotent): already_sent, exit 0, no resend
$PY pipeline.py --config config.yml

# Test with an explicit date / different Tuesday
$PY pipeline.py --config config.yml --date 2026-11-17

# Never touch Buzz (stage the payload only); still fetch/analyze/generate
$PY pipeline.py --config config.yml --date 2026-11-17 --no-send

# Print the plan, execute fetch in dry-run; no side effects at all
$PY pipeline.py --config config.yml --date 2026-11-17 --dry-run

# Suppress the failure-notification message (still logs + records)
$PY pipeline.py --config config.yml --no-notify
```

Exit codes: `0` done / out-of-semester / already-sent · `3` a stage failed.

## Idempotency (two layers)

1. **Top-level day guard** — a successful send for today's `run_date` is
   recorded in `state/runs.jsonl`; a later run the same Tuesday short-circuits
   *before any stage work* (`{"status":"already_sent"}`, exit 0).
2. **Send-level dedupe** — `tuesday_alert.py send` is itself idempotent by
   `run_date`; even a double-fire on the same Tuesday posts exactly one alert
   (the second is `skipped_duplicate`).

Both were demonstrated live: one alert delivered for `2026-11-10`, a re-run the
same day skipped (no second message), and a third run was a top-level no-op.

## Failure reporting

If any stage fails the pipeline:

1. logs an `ERROR` line (stage name + rc + tail) to `logs/pipeline.log`,
2. writes a `{"kind":"failure",...}` row to `state/runs.jsonl`,
3. sends a **de-duplicated failure alert** (`⚠️ Tuesday class-prep FAILED — …`)
   to the same Buzz home channel (keyed by run_date; a re-run of the same
   failing day does not spam), and
4. exits `3` so Hermes cron notices the failure.

## Scheduling / cron

A Hermes cron job (`86fd2110687f`, tech-support profile) fires the wrapper
`~/.hermes/profiles/tech-support/scripts/tuesday-class-prep.sh` every Tuesday
**07:00** local (cron expr `0 7 * * 2`), `no_agent` script mode. The wrapper
just `exec`s `pipeline.py --config config.yml`. The pipeline's own semester
guard means the same cron can run year-round — off-semester Tuesdays exit 0
with nothing sent.

After a send, `tuesday_alert.py capture --run-id <date>` can be run later in the
week to harvest Nathan's replies (the delivery channel's own idempotent capture;
it is not part of this pipeline, which is send-only).

## Failures / edge cases handled

* Off-semester run → graceful no-op (fetcher exits 2 → pipeline exits 0, nothing
  sent, ledger records `out_of_semester`).
* Missing/corrupt stage source → stage fails → logged + reported + exit 3.
* Same-day re-run → skipped (no resend), exit 0.
* Send-layer network/auth failure → tuesday_alert retries (3x) then reports
  failed → pipeline reports + exits 3.

## Files

```
config.yml       the single integration config
pipeline.py      the orchestrator (stdlib-only; pyyaml optional)
README.md
.gitignore       ignores data/ logs/ state/ __pycache__/
data/            (runtime copies kept out of git)
logs/pipeline.log   structured run log
state/runs.jsonl    idempotency + failure ledger (gitignored)
```
