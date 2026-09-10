#!/usr/bin/env python3
"""Compare filter stability: binary (current) vs scored selection.

Runs each strategy N times against the same catalog and topic, then reports:
- per-article selection frequency (binary) or score distribution (scored)
- cross-run agreement metrics
- the "flip zone": articles that change between runs

Usage:
    cd py && ../.venv/bin/python3 ../scripts/test_filter_stability.py [--runs 5]

Requires LLM_BASE_URL and OPENAI_API_KEY in the environment (or kaas-dev.toml).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import time

# ── Bootstrap ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py", "src"))
os.environ.setdefault("LLM_BASE_URL", "https://litellm-de.yijin.io/v1")
os.environ.setdefault("OPENAI_API_KEY", "sk-VP9NEQauNYdnNIJXazu27g")

from kb_ai.derive._filter import build_prompt, pack_batches, _SAFETY_MARGIN
from kb_ai.derive._types import MODE_RECALL
from kb_ai.llm import MAX_PROMPT_CHARS, completion, completion_json
from kb_ai.storage.store import KBStore, render_catalog_line

# ── Scored prompt ──────────────────────────────────────────────────────

def build_scored_prompt(topic: str, listing: str) -> str:
    return (
        "You are selecting which knowledge-base articles belong to a topic. "
        "Below is the article catalog (path — title: summary).\n\n"
        f"{listing}\n\n"
        f"Topic: {topic}\n\n"
        "Rate every article's relevance to the topic on a 0–10 integer scale:\n"
        "  10  = article is primarily about this topic\n"
        "  7-9 = the topic's subject plays a significant role\n"
        "  4-6 = the topic's subject participates or is mentioned\n"
        "  1-3 = only indirect or minimal connection\n"
        "  0   = no connection\n\n"
        'Return ONLY a JSON object: {"scores": [{"path": "...", "score": N}, ...]}\n'
        "Cover every article in the catalog. Do not output anything before the JSON."
    )


# ── Run one binary filter ──────────────────────────────────────────────

def run_binary(catalog, topic: str, model: str) -> list[str]:
    """Current binary filter logic — returns selected paths."""
    listing = "\n".join(render_catalog_line(a) for a in catalog)
    prompt = build_prompt(topic, MODE_RECALL, listing)
    result = completion_json(model=model,
                             messages=[{"role": "user", "content": prompt}])
    valid = {a.path for a in catalog}
    raw = result.get("paths") if isinstance(result, dict) else []
    if not isinstance(raw, list):
        raw = []
    return [p for p in raw if isinstance(p, str) and p in valid]


# ── Run one scored filter ──────────────────────────────────────────────

def run_scored(catalog, topic: str, model: str) -> dict[str, int]:
    """Scored filter — returns {path: score} for every catalog entry."""
    listing = "\n".join(render_catalog_line(a) for a in catalog)
    prompt = build_scored_prompt(topic, listing)
    result = completion_json(model=model,
                             messages=[{"role": "user", "content": prompt}],
                             max_tokens=8192)
    scores_list = result.get("scores", []) if isinstance(result, dict) else []
    valid = {a.path for a in catalog}
    out: dict[str, int] = {}
    for item in scores_list:
        p = item.get("path", "")
        s = item.get("score", 0)
        if p in valid:
            out[p] = int(s)
    return out


# ── Analysis helpers ───────────────────────────────────────────────────

def short(path: str) -> str:
    return path.split("/")[-1].replace(".md", "")


def analyze_binary(runs: list[list[str]], catalog):
    all_paths = {a.path for a in catalog}
    freq: dict[str, int] = {p: 0 for p in all_paths}
    for r in runs:
        for p in r:
            freq[p] = freq.get(p, 0) + 1

    n = len(runs)
    always = {p for p, c in freq.items() if c == n}
    never = {p for p, c in freq.items() if c == 0}
    flips = {p for p, c in freq.items() if 0 < c < n}

    counts = [len(r) for r in runs]
    print(f"\n{'='*70}")
    print(f"BINARY (current) — {n} runs")
    print(f"{'='*70}")
    print(f"  Selected per run: {counts}")
    print(f"  Range: {min(counts)}–{max(counts)}  (Δ{max(counts)-min(counts)})")
    if len(counts) > 1:
        print(f"  StdDev: {statistics.stdev(counts):.1f}")
    print(f"  Always selected:  {len(always)}")
    print(f"  Never selected:   {len(never)}")
    print(f"  Flipped (unstable): {len(flips)}")
    print(f"  Stability: {len(always)}/{len(always)+len(flips)} = "
          f"{len(always)/(len(always)+len(flips)):.0%}")

    if flips:
        print(f"\n  Flipped articles ({len(flips)}):")
        for p in sorted(flips, key=lambda x: -freq[x]):
            print(f"    {freq[p]}/{n}  {short(p)}")

    return always, flips


def analyze_scored(runs: list[dict[str, int]], catalog):
    all_paths = {a.path for a in catalog}
    n = len(runs)

    # Collect per-path scores across runs
    scores: dict[str, list[int]] = {p: [] for p in all_paths}
    for r in runs:
        for p in all_paths:
            scores[p].append(r.get(p, -1))  # -1 = missing

    # Stability metrics
    ranges = []
    identical = 0
    for p, ss in scores.items():
        present = [s for s in ss if s >= 0]
        if len(present) >= 2:
            r = max(present) - min(present)
            ranges.append(r)
            if r == 0:
                identical += 1

    print(f"\n{'='*70}")
    print(f"SCORED — {n} runs")
    print(f"{'='*70}")
    if ranges:
        print(f"  Score range across runs:")
        print(f"    Range=0 (identical):  {identical}/{len(ranges)}")
        print(f"    Range≤1:              {sum(1 for r in ranges if r<=1)}/{len(ranges)}")
        print(f"    Range≤2:              {sum(1 for r in ranges if r<=2)}/{len(ranges)}")
        print(f"    Range≥3:              {sum(1 for r in ranges if r>=3)}/{len(ranges)}")
        print(f"    Mean range:           {statistics.mean(ranges):.2f}")

    # Show threshold stability
    print(f"\n  Threshold analysis (simulated binary cut):")
    for threshold in [4, 5, 6]:
        selections = []
        for r in runs:
            selected = {p for p, s in r.items() if s >= threshold}
            selections.append(selected)
        union = set.union(*selections)
        inter = set.intersection(*selections)
        counts_t = [len(s) for s in selections]
        flips_t = union - inter

        print(f"\n    ≥{threshold}: selected {counts_t}, "
              f"range {min(counts_t)}–{max(counts_t)} (Δ{max(counts_t)-min(counts_t)}), "
              f"stable={len(inter)}, flips={len(flips_t)}, "
              f"stability={len(inter)/(len(inter)+len(flips_t)):.0%}")
        if flips_t:
            for p in sorted(flips_t, key=lambda x: -statistics.mean(
                    [r.get(x, 0) for r in runs])):
                ss = [r.get(p, -1) for r in runs]
                print(f"      scores={ss}  {short(p)}")

    # Show full score table for articles with avg >= 3
    print(f"\n  Per-article scores (avg ≥ 3):")
    by_avg = sorted(
        [(p, ss) for p, ss in scores.items()
         if all(s >= 0 for s in ss)],
        key=lambda x: -statistics.mean(x[1])
    )
    header_runs = "  ".join(f"R{i+1}" for i in range(n))
    print(f"    {'Article':<55} {header_runs}   Avg  Rng")
    print(f"    {'-'*55} {'---  '*n}  ---  ---")
    for p, ss in by_avg:
        avg = statistics.mean(ss)
        if avg < 3:
            continue
        rng = max(ss) - min(ss)
        scores_str = "  ".join(f"{s:>3}" for s in ss)
        print(f"    {short(p):<55} {scores_str}  {avg:>4.1f}  {rng:>3}")


# ── Main ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3,
                        help="number of repetitions per strategy (default: 3)")
    parser.add_argument("--kb", default="./data/backup-2026-09-05",
                        help="source knowledge-base directory")
    parser.add_argument("--topic", default=(
        "猪八戒在西游记中的角色解析，分析猪八戒这个角色的前世今生、"
        "性格特点、取经路上的关键事件、与其他师徒成员的关系，"
        "以及他最终的结局和意义。"))
    parser.add_argument("--model", default="claude-sonnet-4-6")
    parser.add_argument("--only", choices=["binary", "scored"],
                        help="run only one strategy")
    args = parser.parse_args()

    store = KBStore(args.kb, read_only=True)
    catalog = store.existing_articles()
    print(f"Catalog: {len(catalog)} articles")
    print(f"Topic: {args.topic[:60]}...")
    print(f"Model: {args.model}")
    print(f"Runs: {args.runs}")

    if args.only != "scored":
        print(f"\n--- Running binary filter {args.runs}x ---")
        binary_runs = []
        for i in range(args.runs):
            t0 = time.time()
            paths = run_binary(catalog, args.topic, args.model)
            elapsed = time.time() - t0
            binary_runs.append(paths)
            print(f"  binary run {i+1}: {len(paths)} selected ({elapsed:.1f}s)")
        analyze_binary(binary_runs, catalog)

    if args.only != "binary":
        print(f"\n--- Running scored filter {args.runs}x ---")
        scored_runs = []
        for i in range(args.runs):
            t0 = time.time()
            scores = run_scored(catalog, args.topic, args.model)
            elapsed = time.time() - t0
            scored_runs.append(scores)
            print(f"  scored run {i+1}: {len(scores)} articles scored ({elapsed:.1f}s)")
        analyze_scored(scored_runs, catalog)

    # Head-to-head if both ran
    if args.only is None and binary_runs and scored_runs:
        print(f"\n{'='*70}")
        print(f"HEAD-TO-HEAD COMPARISON")
        print(f"{'='*70}")
        b_counts = [len(r) for r in binary_runs]
        s5_counts = [len([p for p, s in r.items() if s >= 5]) for r in scored_runs]
        s4_counts = [len([p for p, s in r.items() if s >= 4]) for r in scored_runs]
        print(f"  Binary:      range {min(b_counts)}–{max(b_counts)} (Δ{max(b_counts)-min(b_counts)})")
        print(f"  Scored ≥5:   range {min(s5_counts)}–{max(s5_counts)} (Δ{max(s5_counts)-min(s5_counts)})")
        print(f"  Scored ≥4:   range {min(s4_counts)}–{max(s4_counts)} (Δ{max(s4_counts)-min(s4_counts)})")


if __name__ == "__main__":
    main()
