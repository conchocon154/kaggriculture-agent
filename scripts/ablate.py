#!/usr/bin/env python3
"""Turn each decision off in turn and measure what it was worth.

The agent beats the built-in starter comfortably, which says nothing about
which of its choices did the work. This runs the same agent with one knob
changed at a time, against the same opponent, over several seeded games.
"""
from __future__ import annotations

import argparse
import importlib.util
import statistics as st
import sys
from pathlib import Path

from kaggle_environments import make

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location("kagagent", ROOT / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def play(agent_fn, opponent: str, games: int) -> tuple[list[float], list[float]]:
    mine, theirs = [], []
    for _ in range(games):
        env = make("kaggriculture", configuration={"episodeSteps": 720})
        env.run([agent_fn, opponent])
        final = env.steps[-1]
        mine.append(final[0]["reward"] or 0)
        theirs.append(final[1]["reward"] or 0)
    return mine, theirs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=5)
    ap.add_argument("--opponent", default="starter")
    args = ap.parse_args()

    mod = load()
    base = {k: getattr(mod, k) for k in
            ("HANDS_PER_DAY", "SELL_BATCH", "CROP", "SEED_BUFFER")}

    variants = [
        ("baseline", {}),
        ("no hired hands", {"HANDS_PER_DAY": 0}),
        ("1 hand", {"HANDS_PER_DAY": 1}),
        ("6 hands", {"HANDS_PER_DAY": 6}),
        ("12 hands", {"HANDS_PER_DAY": 12}),
        ("sell everything at once", {"SELL_BATCH": 999}),
        ("sell one at a time", {"SELL_BATCH": 1}),
        ("carrot instead of melon", {"CROP": "CARROT", "SEED_COST": 20}),
        ("wheat instead of melon", {"CROP": "WHEAT", "SEED_COST": 10}),
    ]

    print(f"{args.games} games each against '{args.opponent}'\n")
    print(f"{'variant':28} {'mean':>8} {'median':>8} {'wins':>6}   spread")
    results = {}
    for name, overrides in variants:
        for k, v in base.items():
            setattr(mod, k, v)
        for k, v in overrides.items():
            setattr(mod, k, v)
        mine, theirs = play(mod.agent, args.opponent, args.games)
        wins = sum(a > b for a, b in zip(mine, theirs))
        results[name] = mine
        print(f"{name:28} {st.mean(mine):8.0f} {st.median(mine):8.0f} "
              f"{wins:3}/{args.games}   {min(mine):.0f}-{max(mine):.0f}")

    b = results["baseline"]
    print("\nagainst the baseline:")
    for name, vals in results.items():
        if name == "baseline":
            continue
        delta = st.mean(vals) - st.mean(b)
        overlap = min(vals) <= max(b) and min(b) <= max(vals)
        note = "  (ranges overlap — not a clean difference)" if overlap else ""
        print(f"  {name:28} {delta:+8.0f}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
