# Kaggriculture agent

[![CI](https://github.com/conchocon154/kaggriculture-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/conchocon154/kaggriculture-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An entry for [Kaggriculture](https://www.kaggle.com/competitions/kaggriculture),
a two-player farming sim: 30 days, 24 turns a day, most coins wins.

A scheduler rather than a rulebook. Every tile that wants work is priced in
coins, every (unit, job) pair is discounted by the walk, and the pairs are
matched against that score. Selling is priced the same way — the engine's price
curve is published, so the order size is computed from it instead of guessed at.

| | vs `starter` | vs the previous agent, seats alternated | mirror match |
|---|---:|---|---:|
| previous agent | 26,458 | — | 11,061 each |
| **this one** | **34,118** | **10 wins, 0 losses** | **21,020 each** |

The mirror-match number is the one that matters most. The old agent lost 60% of
its bank when it met a copy of itself; this one loses about a third, because it
no longer depends on being the only melon seller.

## Why a scheduler

The previous versions were priority lists — water before harvest, harvest before
plant, walk to the nearest job in whichever category came first. That throws
information away twice over. It cannot say that watering a melon on day 9 is
worth more than harvesting a wheat, and it cannot say that a rich job three
tiles away beats a dull one underfoot.

Pricing the jobs fixes both. A watering that saves a plant from becoming a weed
is worth the whole plant; a watering inside the bonus window is worth one more
melon; a watering outside it is worth almost nothing. Those are three different
numbers, and a category ranking can only give them one.

## The three pieces

**The price curve, reimplemented.** `price_at()` is the engine's published
formula, so the agent can ask "what will the next melon fetch" rather than
consulting a hand-set floor. `sell_quantity()` walks that curve forward and
stops where the marginal unit drops below a reservation price. A test checks the
reimplementation against the nine `P(I0−T)`, `P(I0+T)` and `P(I0+2T)` values the
competition documents — if it ever drifts, every plan built on it is wrong.

**A planner that knows the season ends.** A melon needs ten days to first yield,
so one planted on day 20 is eighty coins set on fire. Every earlier version
planted the same crop until the final turn. `crop_value()` returns `None` for a
crop that cannot finish, and the planner falls back to wheat or carrot — two
days to yield — for the tail of the season.

**Greedy maximum-weight matching.** Every (unit, job) pair is scored once,
sorted, and taken in order while both sides are free. It is the assignment
problem solved greedily, which lands within a few percent of optimal and costs
nothing — and that matters when it runs 720 times a game.

## What the tuning found

Each parameter swept alone, judged head-to-head against the untuned scheduler
with seats alternated, six games apiece:

| Change | Result |
|---|---|
| sell reserve 0.42 → **0.25** of base | 6–0 |
| travel cost 0.14 → **0.05** | 6–0 |
| bank a load at 6 items → **at 1** | 6–0 |
| sell reserve 0.60, 0.80 | 0–6 |
| travel cost 0.30 | 0–6 |
| travel cost **0.0** | **0–6, and a score of zero** |
| 3, 7, 9, 11, 13 hands | all lose to 5 |

Two of those are worth stating plainly.

**Bank produce immediately.** `SELL` spends from the shed and `HARVEST` fills a
unit's pack, so produce sitting in a pack is not money yet. Walking it in after
a single item beats hoarding six — the walk costs less than the delay.

**Zero travel cost scores zero.** With no distance discount every unit sets off
across the board for the single richest job, nobody arrives, and the farm
produces nothing. It is a good reminder that the discount is not a tie-breaker,
it is what makes the matching local enough to act on.

Hiring stays at five. The wage bill is `1, 1, 2, 3, 5, 8, 13, …` reset daily, so
it is trivial at five and steep by nine, and every `HIRE` competes with sales
for the ten market orders a turn.

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -U kaggle-environments pytest

# the measurement that decides things: wins, with seats alternated
.venv/bin/python scripts/head2head.py main.py attempts/v6_melon_tuned.py --games 10

.venv/bin/python -m pytest tests/ -q      # 33 tests
```

Seats are alternated because the two players are not symmetric in a shared
market. A four-game round robin between three variants once came out
non-transitive; it only resolved at eight games with alternating seats.

## Submitting

```bash
kaggle competitions submit kaggriculture -f main.py -m "..."
```

The ladder is Elo on **wins and losses only** — the coin margin never enters it,
and opponents are drawn from near your own rating. An earlier version of this
agent scored *higher* against `starter` than the one that replaced it and lost
every head-to-head game, which is the whole reason the tuning above is measured
the way it is.

## What did not work

[`attempts/`](attempts/) keeps seven earlier versions with their numbers, and
[`attempts/README.md`](attempts/README.md) says why each failed. The short list:
four attempts at an animal herd, all of which collapsed on the fact that `FEED`
takes wheat from the acting unit's own inventory rather than the shed; and a
four-crop diversified farm that scores highest against `starter` and loses
head-to-head, because spreading production hands the top of the melon price
curve to a specialist.

## Licence

MIT.
