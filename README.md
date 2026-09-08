# Kaggriculture agent

[![CI](https://github.com/conchocon154/kaggriculture-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/conchocon154/kaggriculture-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An entry for [Kaggriculture](https://www.kaggle.com/competitions/kaggriculture),
a two-player farming sim: 30 days, 24 turns a day, and whoever has the most
money at the end wins.

**27,332 coins against the built-in `starter`'s ~3,500, from a starting bank of
3,000.** What follows is which decisions earned that, measured one at a time,
and the one condition under which most of it disappears.

## What each decision is worth

`scripts/ablate.py` reruns the agent with a single knob changed:

| Variant | Final money | vs baseline |
|---|---:|---:|
| **baseline** (melon, 3 hands) | **27,332** | — |
| no hired hands | 16,034 | **−11,298** |
| 1 hand | 25,161 | −2,171 |
| 6 hands | 26,161 | −1,171 |
| 12 hands | 24,234 | −3,098 |
| sell one unit at a time | 27,669 | +337 |
| sell the whole shed at once | 27,244 | −88 |
| wheat instead of melon | 8,012 | **−19,320** |
| carrot instead of melon | 6,932 | **−20,400** |

Two decisions carry almost the entire result, and one that looks important
carries nothing.

**Melon, and it is not close.** Wheat cycles in two days against melon's ten and
its price decays gently under volume, which reads like the sensible staple.
Melon is worth three times more. It sells for 250 against wheat's 25 and still
clears six units a plant, and even after its own supply drives the price down —
premium goods are the ones the price function punishes hardest — the gap is
19,000 coins.

**Hiring, which is nearly free.** Hands cost `1, 1, 2, 3, 5, 8, …` and the
counter resets every morning, so a crew for a whole day costs less than one
melon seed. Not hiring costs 11,298 coins. The season is 720 turns and every
unit acts on every turn, so the binding constraint is actions, not money.

**Selling in batches, which I put in to protect the price, does nothing.**
Dumping the whole shed at once costs 88 coins and selling one unit at a time
*gains* 337. Both are inside the noise of a decision that mattered. The batching
logic stays because it is harmless, but it is not why this works, and the README
would be wrong to imply otherwise.

## Three hands, not twelve

More hands is better up to three and worse after:

```
hands   0      1      2      3      4      5      6      7      8      9
money  16554  25161  26081  27332  26398  26491  26161  26243  26419  25462
```

The fall past three is not the wage bill — the wage bill is trivial. Every
`HIRE` is a market order and only `maxMarketOrdersPerTurn` (10) are processed
per player per turn. Twelve hires at hour 0 fill the queue and **silently drop
that turn's seed purchase and every sale queued behind them**. The cost of
over-hiring is paid in lost trades, not in wages. There is a test that keeps the
order list inside the cap for exactly this reason.

## The limitation, which is large

The score is *identical* against `starter`, `random` and `pass` — 27,332 every
time. The opponent cannot touch it, because the only market this agent trades in
is melon and none of those opponents sell melon.

Put it against itself:

| Match | Final money |
|---|---:|
| vs `starter` / `random` / `pass` | 27,332 |
| **vs a copy of itself** | **11,061** |

**A 60% collapse.** The edge is not really "melon is the best crop" — it is
"melon is the best crop while nobody else is selling one". Against a field that
has also worked this out, the melon price craters and most of the advantage goes
with it. It still beats the starter at 11,061, so the floor is not bad, but the
headline number is a measurement taken in an empty market and should be read
that way.

## Why the numbers have no error bars

Every figure above is a single game, because with melon the result is exactly
reproducible: 27,332 in every run, against every opponent. Melon occupies a tile
for ten of the thirty days, so the board is almost never empty, and the only
stochastic element that touches this strategy — weeds spawning on empty tiles —
has nearly no surface to land on. The wheat variant is *not* deterministic
(6,466–9,559 across runs) for the same reason in reverse: a two-day cycle leaves
tiles bare constantly.

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -U kaggle-environments pytest
.venv/bin/python scripts/ablate.py --games 2
.venv/bin/python -m pytest tests/ -q      # 22 tests
```

A game takes about a second and a half.

## Submitting

The submission is `main.py` with an `agent` function at the root:

```bash
kaggle competitions submit kaggriculture -f main.py -m "melon loop, 3 hands"
```

## Tests

The game is slow to simulate, so the tests drive the agent with hand-built
observations instead. What they pin down is the shape of the action dict — a
malformed one is a silent no-op for a whole turn, which is expensive and
invisible — and the rules the ablation showed actually matter: that hiring
happens at hour 0 and not again, that the market list stays inside the ten-order
cap, that a full unit walks to the shed and drops there, and that two idle units
do not walk to the same tile.

## Licence

MIT.
