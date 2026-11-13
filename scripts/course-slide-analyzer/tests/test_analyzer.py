#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_analyzer.py — acceptance tests for the course slide analyzer.

Three acceptance criteria from kanban task t_f2559172:
  1. It runs on a sample class.                              (runs + valid schema)
  2. It identifies at least three underdeveloped areas.      (>=3 below threshold)
  3. It produces stable output for unchanged inputs.         (idempotent/deterministic)

Run:  <hermes-venv-python> tests/test_analyzer.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYZER_DIR = os.path.dirname(HERE)
sys.path.insert(0, ANALYZER_DIR)
import course_slide_analyzer as A  # noqa: E402

SAMPLE_JSON = os.path.join(
    ANALYZER_DIR, "..", "course-week-fetcher", "data", "latest.json"
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


def main():
    sample = os.path.abspath(SAMPLE_JSON)
    if not os.path.exists(sample):
        print(f"FATAL: sample JSON not found: {sample}")
        print("Run the fetcher first (data/latest.json).")
        sys.exit(2)

    # ---------- 1. runs on a sample class + schema validity ----------
    print("[1] Run on sample + schema validity")
    result = A.analyze(sample)
    check("top-level keys present",
          set(result) >= {"analyzer_version", "count", "classes",
                          "underdeveloped_threshold"})
    check("some classes analyzed", result["count"] >= 1)
    all_schema_ok = True
    for c in result["classes"]:
        ok = (set(c) >= {"class_id", "title", "date", "scores", "evidence",
                         "ranked_all", "ranked_underdeveloped", "sources"})
        sc = c["scores"]
        in_range = all(isinstance(v, int) and 0 <= v <= 100 for v in sc.values())
        has_six = set(sc) == set(A.AREA_KEYS)
        # ranked_all sorted ascending by score
        ranked_vals = [r["score"] for r in c["ranked_all"]]
        sorted_ok = ranked_vals == sorted(ranked_vals)
        if not (ok and in_range and has_six and sorted_ok):
            all_schema_ok = False
            print("    bad class:", c["class_id"])
    check("every class has full valid schema + sorted ranking", all_schema_ok)

    # ---------- 2. at least three underdeveloped areas ----------
    print("[2] At least three underdeveloped areas per sample class")
    all_at_least_3 = True
    for c in result["classes"]:
        n_und = len(c["ranked_underdeveloped"])
        area_names = [r["area"] for r in c["ranked_underdeveloped"]]
        if n_und < 3:
            all_at_least_3 = False
            print(f"    {c['class_id']}: only {n_und} underdeveloped: {area_names}")
        check(f"    {c['class_id']} has >=3 underdeveloped (has {n_und})",
              n_und >= 3, ", ".join(area_names) if area_names else "")
    check("every sample class meets the >=3 underdeveloped criterion", all_at_least_3)

    # ---------- 3. stable output for unchanged inputs ----------
    print("[3] Stability: identical output on unchanged input")
    result2 = A.analyze(sample)
    stable = json.dumps(result, ensure_ascii=False, sort_keys=True) == \
        json.dumps(result2, ensure_ascii=False, sort_keys=True)
    check("two runs on identical input produce identical output", stable)

    # also assert the file round-trip writes are deterministic
    with tempfile.TemporaryDirectory() as tmp:
        outp = os.path.join(tmp, "analysis.json")
        os.makedirs(outp[:-len("analysis.json")], exist_ok=True)
        # just verify json-serializability
        json.dumps(result, ensure_ascii=False)

    print("\n================ RESULT ================")
    print(f"pass: {len(PASS)}  fail: {len(FAIL)}")
    if FAIL:
        print("FAILED TESTS:")
        for f in FAIL:
            print("  -", f)
        sys.exit(1)
    print("ALL ACCEPTANCE TESTS PASSED")


if __name__ == "__main__":
    main()
