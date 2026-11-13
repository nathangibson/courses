#!/usr/bin/env python3
"""
Tuesday class-prep pipeline — end-to-end orchestrator.

Chains the four verified stage components into one Tuesday-morning job:

    fetch     ->  analyze   ->  generate  ->  send
  (weekly     (course-        (top-3 area   (Buzz alert,
   classes)   slide-analyzer)  questions)    idempotent by run_date)

This is the integration layer for kanban t_fcd06286. It reads ONE config
(config.yml) that owns the operational knobs (semester dates, courses-repo
path, alert channel, question limits) and drives each stage via subprocess,
running each stage in its own directory so their own relative config paths
resolve.

Properties
----------
* Semester guard   — outside an active semester the run is a graceful no-op
                     (fetcher exits 2 → we log and exit 0, sending nothing).
* Idempotency      — a successful send for today's run_date is recorded in
                     state/runs.jsonl; a second run on the same day short-
                     circuits at the top and does NOT re-fetch/re-send.
                     The alert stage's own send is ALSO idempotent by
                     run_date (backstop).
* Failure reporting — any non-zero stage is logged, recorded in the ledger,
                     and a de-duplicated failure alert is sent to the same
                     Buzz channel. The cron exit code is then non-zero so
                     Hermes cron notices.

CLI
---
  pipeline.py [--config config.yml] [--date YYYY-MM-DD]
              [--send | --no-send] [--notify | --no-notify] [--dry-run]

  --date      Override "today" (the run date / idempotency key). Default:
              system date. Mainly for testing a specific Tuesday.
  --no-send   Run fetch→analyze→generate but do NOT deliver to Buzz.
  --no-notify Disable the failure-notification message (still logs + records).
  --dry-run   Print what each stage would run, execute fetch/analyze/generate
              in dry-run mode, and never touch Buzz or the ledger.

Exit codes: 0 = done (or out-of-semester, or already sent) · 3 = a stage failed.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

try:
    import yaml
except ImportError:  # pragmatic: config can also be read via the JSON fallback
    yaml = None

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# tiny YAML loader (stdlib-only: handle both pyyaml present and absent)
# ---------------------------------------------------------------------------

def load_config(config_path):
    config_path = os.path.abspath(config_path)
    if yaml is not None:
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
    else:
        # minimal dotted-key YAML fallback for the keys we need — real configs
        # should be read with pyyaml; this is only a safety net.
        cfg = _minimal_yaml(config_path)
    return cfg or {}


def _minimal_yaml(path):
    """Very small YAML-subset reader (plain scalars, lists, nested 2-level
    dicts without deep nesting). Used only when pyyaml is unavailable."""
    import re
    out = {}
    cur = out
    stack = []
    with open(path, "r", encoding="utf-8") as fh:
        lines = [l for l in fh.read().splitlines() if l.strip() and not l.strip().startswith("#")]
    for line in lines:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if stripped.startswith("- "):
            cur.setdefault("__list__", []).append(stripped[2:])
            continue
        m = re.match(r"([A-Za-z0-9_.-]+):\s*(.*)$", stripped)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "":
            nxt = {}
            cur[key] = nxt
            stack.append((indent, cur))
            cur = nxt
        else:
            cur[key] = val
    # collapse __list__ sentinels
    def fix(o):
        if isinstance(o, dict):
            r = {k: fix(v) for k, v in o.items() if k != "__list__"}
            if "__list__" in o:
                r["__list__"] = o["__list__"]
            return r
        return o
    return fix(out)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def sub_abs(*parts):
    return os.path.abspath(os.path.join(*parts))


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _log_path(cfg):
    return sub_abs(HERE, cfg.get("log_file", "logs/pipeline.log"))


def log(cfg, level, msg):
    line = f"{now_iso()} [{level}] {msg}"
    try:
        with open(_log_path(cfg), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    print(line, file=sys.stderr if level == "ERROR" else sys.stdout)
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# ledger (idempotency + failure record)
# ---------------------------------------------------------------------------

def _ledger_path(cfg):
    return sub_abs(HERE, cfg.get("state_dir", "state"), "runs.jsonl")


def load_ledger(cfg):
    path = _ledger_path(cfg)
    rows = []
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def append_ledger(cfg, row):
    os.makedirs(os.path.dirname(_ledger_path(cfg)), exist_ok=True)
    with open(_ledger_path(cfg), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def already_completed(cfg, run_date):
    """True if a prior run for run_date reached a terminal SENT state (a real
    delivery to Buzz, not a --no-send staging). 'sent'/'already_sent' both mean
    the alert was genuinely delivered, so a re-run is a no-op. 'skipped'
    (--no-send) does NOT count as completed."""
    for r in load_ledger(cfg):
        if r.get("run_date") == run_date and r.get("status") in ("sent", "completed"):
            if r.get("send_status") in ("sent", "already_sent"):
                return True
    return False


def failure_already_notified(cfg, run_date):
    for r in load_ledger(cfg):
        if r.get("run_date") == run_date and r.get("kind") == "failure":
            return True
    return False


def in_semester(cfg, date_iso):
    """Inclusive [start, end] semester check from the integrated config."""
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
    except ValueError:
        return True  # malformed date — let downstream stages decide
    for s in (cfg.get("semesters") or []):
        try:
            st = datetime.strptime(s["start"], "%Y-%m-%d").date()
            en = datetime.strptime(s["end"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue
        if st <= d <= en:
            return True
    return False


# ---------------------------------------------------------------------------
# stage runner
# ---------------------------------------------------------------------------

def run_stage(cfg, stage_name, args_list, cwd, dry_run=False):
    """Run a stage script; return (exit_code, combined_output)."""
    py = cfg["python"]
    cmd = [py] + args_list
    log(cfg, "INFO", f"stage {stage_name}: {' '.join(cmd)} (cwd={cwd})")
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=600)
        tail = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            log(cfg, "ERROR", f"stage {stage_name} FAILED rc={proc.returncode}\n{tail.strip()[-2000:]}")
        else:
            log(cfg, "INFO", f"stage {stage_name} OK rc=0")
        return proc.returncode, tail
    except FileNotFoundError as exc:
        log(cfg, "ERROR", f"stage {stage_name}: python not found: {exc}")
        return 3, str(exc)
    except subprocess.TimeoutExpired:
        log(cfg, "ERROR", f"stage {stage_name}: timed out after 600s")
        return 3, "timeout"


# ---------------------------------------------------------------------------
# failure notification (de-duplicated Buzz message)
# ---------------------------------------------------------------------------

def notify_failure(cfg, run_date, stage, detail):
    """Send a de-duplicated failure alert to the Buzz home channel and record it.

    Uses the same identity/roster and buzz CLI as the tuesday_alert module, but
    posts a distinct FAILED message that is NOT gated by the question run_date
    delivery dedupe (there is no payload to deliver). We dedupe in our own
    ledger (kind=failure) so a re-run on the same day doesn't spam.
    """
    if failure_already_notified(cfg, run_date):
        log(cfg, "INFO", f"failure already notified for {run_date}; not re-sending")
        return 0

    keys_path = os.path.expanduser("~/git/git-local/buzz/deploy/.nostr-keys")
    if not os.path.exists(keys_path):
        log(cfg, "ERROR", "cannot notify failure: .nostr-keys missing")
        append_ledger(cfg, {"kind": "failure", "run_date": run_date, "stage": stage,
                            "status": "failed", "notified": False, "at": now_iso(),
                            "error": detail, "reason": "no keys"})
        return 1

    keys = {}
    for line in open(keys_path):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            keys[k] = v
    ident = cfg.get("alert", {}).get("identity", "AGENT")
    nsec = keys.get(f"{ident}_NSEC")
    if not nsec:
        log(cfg, "ERROR", f"cannot notify failure: no {ident}_NSEC in .nostr-keys")
        append_ledger(cfg, {"kind": "failure", "run_date": run_date, "stage": stage,
                            "status": "failed", "notified": False, "at": now_iso(),
                            "error": detail, "reason": f"no {ident}_NSEC"})
        return 1

    alert = cfg.get("alert", {})
    channel = alert.get("home_channel")
    relay = alert.get("relay")
    buzz = "/Users/nathan/bin/buzz"
    rel_date = datetime.strptime(run_date, "%Y-%m-%d").strftime("%a %d %b %Y") if _is_date(run_date) else run_date
    content = (
        f"⚠️ Tuesday class-prep FAILED — {rel_date}\n"
        f"Stage failed: {stage}\n"
        f"{detail[:600]}\n"
        f"See the pipeline log: {_log_path(cfg)}"
    )
    env = dict(os.environ)
    env["BUZZ_RELAY_URL"] = relay
    env["BUZZ_PRIVATE_KEY"] = nsec
    try:
        r = subprocess.run(
            [buzz, "messages", "send", "--channel", channel, "--content", content],
            env=env, capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(cfg, "ERROR", f"failure-notify send errored: {exc}")
        append_ledger(cfg, {"kind": "failure", "run_date": run_date, "stage": stage,
                            "status": "failed", "notified": False, "at": now_iso(),
                            "error": detail, "notify_error": str(exc)})
        return 1

    if r.returncode == 0:
        log(cfg, "INFO", f"failure notification sent for {run_date}")
        append_ledger(cfg, {"kind": "failure", "run_date": run_date, "stage": stage,
                            "status": "notified", "notified": True, "at": now_iso(),
                            "error": detail})
        return 0
    log(cfg, "ERROR", f"failure-notify send failed rc={r.returncode}: {(r.stderr or r.stdout)[:400]}")
    append_ledger(cfg, {"kind": "failure", "run_date": run_date, "stage": stage,
                        "status": "failed", "notified": False, "at": now_iso(),
                        "error": detail, "notify_error": (r.stderr or r.stdout)[:400]})
    return 1


def _is_date(s):
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Tuesday class-prep end-to-end pipeline")
    ap.add_argument("--config", default=os.path.join(HERE, "config.yml"))
    ap.add_argument("--date", default=None, help="run date / idempotency key (default: today)")
    ap.add_argument("--send", dest="send", action="store_true", default=None,
                    help="deliver to Buzz (default)")
    ap.add_argument("--no-send", dest="send", action="store_false", default=None)
    ap.add_argument("--notify", dest="notify", action="store_true", default=None,
                    help="send failure notification (default)")
    ap.add_argument("--no-notify", dest="notify", action="store_false", default=None)
    ap.add_argument("--dry-run", action="store_true", help="print plan, no side effects")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    send = True if args.send is None else args.send
    notify = True if args.notify is None else args.notify

    run_date = args.date or datetime.now().strftime("%Y-%m-%d")
    os.makedirs(os.path.dirname(_log_path(cfg)), exist_ok=True)
    log(cfg, "INFO", f"=== pipeline start run_date={run_date} send={send} dry={args.dry_run} ===")

    # ---- size the stages from config ----
    stages = cfg.get("stages", {})
    fetcher_dir = stages["fetcher"]
    analyzer_dir = stages["analyzer"]
    generator_dir = stages["generator"]
    alert_dir = stages["alert"]
    q_limit = int(cfg.get("questions", {}).get("max_per_class", 3))
    threshold = int(cfg.get("questions", {}).get("underdeveloped_threshold", 60))

    def fail(stage, detail):
        log(cfg, "ERROR", f"PIPELINE FAILED at stage={stage}: {detail}")
        notified = False
        if notify and not args.dry_run:
            notified = (notify_failure(cfg, run_date, stage, detail) == 0)
        if not (notify and not args.dry_run):
            # record the failure outright when we're not notifying (dry/no-notify)
            append_ledger(cfg, {"kind": "failure", "run_date": run_date, "stage": stage,
                                "status": "failed", "at": now_iso(), "error": detail,
                                "notified": notified})
        else:
            # notify_failure already wrote the canonical kind=failure row
            log(cfg, "INFO", f"failure recorded by notify_failure (notified={notified})")
        return 3

    # ---- semester guard (pre-check from integrated config, then fetcher) ----
    if args.dry_run:
        if not in_semester(cfg, run_date):
            log(cfg, "INFO", "[dry-run] out of semester — would exit gracefully, no work")
            return 0

    # ---- idempotency: same-Tuesday guard at the top ----
    if send and not args.dry_run and already_completed(cfg, run_date):
        log(cfg, "INFO", f"run_date {run_date} already completed; skipping (idempotent)")
        print(json.dumps({"status": "already_sent", "run_date": run_date}))
        return 0

    # ---- STAGE 1: fetch ----
    fetch_args = ["course_week_fetcher.py", "--date", run_date]
    if args.dry_run:
        fetch_args.append("--dry-run")
    rc, out = run_stage(cfg, "fetch", fetch_args, fetcher_dir, dry_run=args.dry_run)
    if rc == 2:
        # out of semester — graceful no-op
        log(cfg, "INFO", f"out of semester for {run_date}; nothing to do (exit 0)")
        append_ledger(cfg, {"kind": "run", "run_date": run_date, "status": "out_of_semester",
                            "at": now_iso(), "stage": "fetch"})
        return 0
    if rc != 0:
        return fail("fetch", f"exit {rc}")

    if args.dry_run:
        log(cfg, "INFO", "[dry-run] fetch OK; would proceed to analyze/generate/send")
        return 0

    # ---- STAGE 2: analyze ----
    rc, _out = run_stage(cfg, "analyze",
                         ["course_slide_analyzer.py", "--threshold", str(threshold)],
                         analyzer_dir, dry_run=False)
    if rc != 0:
        return fail("analyze", f"exit {rc}")

    # ---- STAGE 3: generate ----
    rc, _out = run_stage(cfg, "generate",
                         ["question_generator.py", "--run-date", run_date,
                          "--notes", f"Tuesday prep for week of {run_date}"],
                         generator_dir, dry_run=False)
    if rc != 0:
        return fail("generate", f"exit {rc}")

    qpath = sub_abs(generator_dir, "data", "questions.json")
    if not os.path.exists(qpath):
        return fail("generate", f"output not found: {qpath}")

    # ---- STAGE 4: send (idempotent by run_date inside tuesday_alert) ----
    send_status = "skipped"
    if send:
        rc, out = run_stage(cfg, "send",
                            ["tuesday_alert.py", "send", qpath,
                             "--retries", str(cfg.get("alert", {}).get("send_retries", 3))],
                            alert_dir, dry_run=False)
        if rc != 0:
            # send itself already retried inside the module; report and notify
            return fail("send", f"exit {rc}")
        # parse tuesday_alert stdout for the status line
        status = None
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{") and '"status"' in line:
                try:
                    d = json.loads(line)
                    status = d.get("status")
                    if d.get("status") == "skipped_duplicate":
                        send_status = "already_sent"
                    elif d.get("status") == "sent":
                        send_status = "sent"
                    break
                except json.JSONDecodeError:
                    continue
        if status == "failed":
            return fail("send", "tuesday_alert reported failed")
        # rc==0 but no parseable status line => assume delivered
        if status != "skipped_duplicate":
            send_status = "sent"
        log(cfg, "INFO", f"send status={status or 'sent'} for {run_date}")
    else:
        log(cfg, "INFO", f"--no-send given; skipping delivery (payload staged at {qpath})")

    # ---- record completion ----
    append_ledger(cfg, {"run_date": run_date, "status": "completed",
                        "questions_file": qpath, "at": now_iso(),
                        "questions": "count_from_generator",
                        "send_status": send_status})
    print(json.dumps({"status": "completed", "run_date": run_date,
                      "send_status": send_status, "questions_file": qpath}))
    log(cfg, "INFO", f"=== pipeline done run_date={run_date} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
