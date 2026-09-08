#!/usr/bin/env python3
"""Coins against a fixed opponent, over seeded games.

Not the ladder's measure — that counts wins — but the one that shows whether a
change moved the economy at all. `head2head.py` is what decides.
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
    spec = importlib.util.spec_from_file_location(f"agent_{tag}", (ROOT / path).resolve())
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"agent_{tag}"] = mod
    spec.loader.exec_module(mod)
    return mod.agent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", nargs="?", default="main.py")
    ap.add_argument("--games", type=int, default=6)
    ap.add_argument("--opponent", default="starter")
    args = ap.parse_args()

    fn = load(args.agent, "a")
    mine, theirs = [], []
    for i in range(args.games):
        env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": 1000 + i})
        env.run([fn, args.opponent])
        f = env.steps[-1]
        mine.append(f[0]["reward"] or 0)
        theirs.append(f[1]["reward"] or 0)
        print(f"  seed {1000+i}: {mine[-1]:>9,.0f}  vs {theirs[-1]:>8,.0f}")
    print(f"{args.agent} vs {args.opponent}: mean {st.mean(mine):,.0f} "
          f"median {st.median(mine):,.0f} min {min(mine):,.0f} max {max(mine):,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
