#!/usr/bin/env python3
"""Compare two agents the way the ladder does: on wins, with seats alternated.

The ladder is Elo-like and counts wins and losses only, so a change that raises
the coin total against a weak opponent can still be a loss on the ladder. This
is the measurement that decides things here; scripts/ablate.py measures coins
against a fixed opponent and is kept for what it is good for.

Seats are alternated because the two players are not symmetric in a shared
market — the same pair run four games one way came out non-transitive against a
third agent, and only resolved at eight games with alternating seats.

    python3 scripts/head2head.py main.py attempts/v1_melon.py --games 10
"""
from __future__ import annotations

import argparse
import importlib.util
import statistics as st
import sys
from pathlib import Path

from kaggle_environments import make

ROOT = Path(__file__).resolve().parent.parent


def load(path: str, tag: str):
    p = (ROOT / path).resolve()
    spec = importlib.util.spec_from_file_location(f"agent_{tag}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--games", type=int, default=10)
    args = ap.parse_args()

    a, b = load(args.a, "a"), load(args.b, "b")
    aw = bw = ties = 0
    coins_a, coins_b = [], []

    for i in range(args.games):
        swap = i % 2 == 1
        first, second = (b, a) if swap else (a, b)
        env = make("kaggriculture", configuration={"episodeSteps": 720})
        env.run([first.agent, second.agent])
        f = env.steps[-1]
        r0, r1 = f[0]["reward"] or 0, f[1]["reward"] or 0
        ra, rb = (r1, r0) if swap else (r0, r1)
        coins_a.append(ra)
        coins_b.append(rb)
        aw += ra > rb
        bw += rb > ra
        ties += ra == rb

    print(f"{args.a}  vs  {args.b}   ({args.games} games, seats alternated)\n")
    print(f"  {args.a:34} {aw} wins   mean {st.mean(coins_a):8.0f}")
    print(f"  {args.b:34} {bw} wins   mean {st.mean(coins_b):8.0f}")
    if ties:
        print(f"  ties: {ties}")
    if abs(aw - bw) <= 1 and args.games < 10:
        print("\n  too close and too few games to call — run more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
