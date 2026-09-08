# Kaggriculture agent

[![CI](https://github.com/conchocon154/kaggriculture-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/conchocon154/kaggriculture-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An entry for [Kaggriculture](https://www.kaggle.com/competitions/kaggriculture),
a two-player farming sim: 30 days, 24 turns a day, and whoever has the most
money at the end wins.

This started as "make the most coins". That was the wrong objective, and finding
out why is most of what happened here.

## The objective was wrong

The ladder is Elo-like and scores **wins and losses only** — the coin margin
does not enter it, and opponents are drawn from near your own rating. So the
question is never "how much money does this make against the built-in
`starter`", it is "does this beat the agent it will actually be drawn against".

Those two questions have different answers. Measured head-to-head with seats
alternated:

| Agent | Coins vs `starter` | Record vs the previous version |
|---|---:|---|
| previous submission | **27,332** | — |
| four-crop version | **29,161** | loses 1 of 6 |
| **shipped** | 26,458 | **wins 10 of 10** |

The shipped agent makes *less money against a weak opponent* than either of the
others and beats both of them every single game. Optimising the coin total was
optimising the wrong number, and the version that looked best on it — four
crops, price floors, land purchases, nine hands — is the one that loses.

## What actually changed

Two parameters, each swept on its own and judged head-to-head against the
previous submission rather than against `starter`:

| Change | Record vs previous version |
|---|---|
| control (unchanged) | 6 ties |
| **hands 3 → 5** | **6 wins, 0 losses** |
| hands 6 | 6 wins, 0 losses |
| hands 7 | 0 wins — falls off a cliff |
| **sell batch 6 → 12** | **6 wins, 0 losses** |
| sell batch 3 | 0 wins |
| seed buffer 8 → 16 | 0 wins |

Five hands and a sell batch of twelve. Combined and run with alternating seats,
that beats the previous agent 10–0 and beats the six-hand variant 8–0.

**Selling faster wins, which is the opposite of what the batching was for.** The
batch size went in to protect the melon price. An earlier ablation showed it did
nothing to coin totals; head-to-head it turns out that in a contested market the
price is going to the floor regardless, and the first seller gets the good half
of the curve. Holding stock to protect a price only works if you are the only
one selling.

**Seven hands falls off a cliff.** The wage bill is `1, 1, 2, 3, 5, 8, 13, …`
and reset daily, so it is trivial at five and steep by nine; on top of that
every `HIRE` is a market order against a ten-per-turn cap, so a long hiring
queue starts dropping that turn's sales.

## What was tried and did not work

Kept in [`attempts/`](attempts/) with the numbers, because two of them looked
like improvements right up until they were measured properly.

**Geese.** The price table makes this look obvious: melon decays as `sq` with an
above-target of 3.60 and hits the $1 floor about 300 units past the start, while
eggs decay as `log` at 0.20 and are still worth about $40 after six hundred
sales. A goose lays daily forever and drops free fertiliser. Three versions of
it, and none got off the ground — because `FEED` takes wheat out of **the acting
unit's own inventory**, not the shed. Every goose needs a unit standing on it
*carrying wheat*, every day, against an animal that escapes permanently after
two missed feeds. The flock oscillated 6 → 4 → 5 → 3 while every coin earned
went into replacing what had just starved.

**Diversifying into four crops.** Scores highest against `starter` and loses
head-to-head. Spreading production means producing fewer melons, which hands the
high half of the melon curve to a specialist; and a price floor is a promise not
to sell, which an opponent enforces on you by keeping the price beneath it.

## The old measurement, and why it misled

The first version of this README reported an ablation against `starter` — melon
over wheat worth +19,320, hiring worth +11,298, batching worth nothing. Those
numbers are still right about coins, and the crop and hiring findings still
hold. The batching one was the tell: a change worth nothing in coins turned out
to be worth every game head-to-head once it was pointed the other way.

The old hand sweep, for the record:

```
hands   0      1      2      3      4      5      6      7      8      9
money  16554  25161  26081  27332  26398  26491  26161  26243  26419  25462
```

The fall past three there is the ten-order-per-turn market cap: twelve hires at
hour 0 fill the queue and **silently drop that turn's seed purchase and every
sale behind them**. A test keeps the order list inside the cap for this reason.
Note that the head-to-head sweep puts the optimum at five, not three — the coin
curve and the win curve peak in different places.

## The limitation, which is still large

Against `starter`, `random` and `pass` the score barely moves, because none of
them sell melon and so none of them can touch this agent's market. Against a
copy of itself it roughly halves. The edge is not "melon is the best crop", it
is "melon is the best crop while few others are selling one", and on a ladder
full of melon farmers most of it goes away.

What the head-to-head work changed is that the agent is now tuned *for* the
contested case rather than the empty one — selling faster rather than holding
for a price is exactly the adjustment that matters when someone else is
supplying the same market.

## On error bars

Coin totals against a fixed opponent are exactly reproducible here: melon
occupies a tile for ten of the thirty days, so the board is almost never empty
and the one stochastic element that touches this strategy — weeds spawning on
empty tiles — has nearly nothing to land on. The wheat variant is *not*
deterministic (6,466–9,559 across runs) for the same reason in reverse.

Head-to-head records are not reproducible in that way, so those are run with
**seats alternated**, because the two seats are not symmetric in a shared
market. A round-robin at four games a pair came out non-transitive; at eight
games with alternating seats it resolved cleanly. Four games was not enough,
which is worth knowing before reading anything into a short series.

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -U kaggle-environments pytest

# the measurement that decides things: wins, with seats alternated
.venv/bin/python scripts/head2head.py main.py attempts/v1_melon.py --games 10

# coins against a fixed opponent — useful, but not what the ladder scores
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
