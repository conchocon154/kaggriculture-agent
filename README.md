# Kaggriculture agent

[![CI](https://github.com/conchocon154/kaggriculture-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/conchocon154/kaggriculture-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An entry for [Kaggriculture](https://www.kaggle.com/competitions/kaggriculture),
a two-player farming sim: 30 days, 24 turns a day, most coins wins.

A scheduler rather than a rulebook. Every tile that wants work is priced in
coins per action, every (unit, job) pair is discounted by the walk, and the
pairs are matched against that score.

| | vs `starter`, 8 seeds | vs the previous agent, seats alternated |
|---|---:|---|
| previous agent (on the ladder at rank 6,505) | 34,866 | — |
| **this one** | **80,232** | **12 wins, 0 losses** |

## What the previous agent got wrong

It was a decent scheduler that had never read the price table. Integrating the
engine's own curve gives the total a season can pay for each good:

| units sold | 30 | 100 | 250 | 400 | price of the 400th |
|---|---:|---:|---:|---:|---:|
| **MELON** | 7,416 | 21,721 | 26,577 | 26,727 | $1 |
| **EGG** | 1,371 | 4,371 | 10,559 | 16,559 | **$40** |
| **FERTILIZER** | 2,913 | 9,010 | 18,775 | 24,040 | $20 |
| **WHEAT** | 687 | 2,193 | 5,313 | 8,313 | $20 |
| **TOMATO** | 1,529 | 4,318 | 8,315 | 10,453 | $9 |
| **WOOL** | 5,503 | 7,969 | 8,119 | 8,269 | $1 |
| **MILK** | 3,888 | 6,205 | 6,355 | 6,505 | $1 |
| **STRAWBERRY** | 2,764 | 3,847 | 3,997 | 4,147 | $1 |

Melon is the best thing on the board and it is worth about 26,000 coins for the
entire season — shared with the opponent. An agent whose plan is melon has a
ceiling, and the old one was sitting on it. Everything past that has to come
from the two curves that never crash: eggs, and the fertiliser that arrives free
with the bird laying them. Wool and milk are traps that look rich at 30 units.

So the season is: melon while melon is deep, then a flock funded by melon, on
land bought with melon money.

Three engine facts the old agent never used.

* **`BUY_LAND`** turns 25 tiles into 100 for 7,000 coins — cheaper than three
  geese. It never called it, and played a quarter of the game.
* **A hand costs `fib(n)`** for the day, so the twelfth hand of the day costs
  144 coins for twenty-four actions.
* **End of day empties every pack into the shed anyway**, so walking back to
  bank a single item bought nothing but steps.

## Coins per action

The one idea the rest hangs on. Two of them, really, and both are the same
mistake in different clothes: comparing numbers measured over different things.

**Price each successive tile, not the crop.** Valuing a crop at a flat share of
its base price says every empty tile wants the same crop, so the farm
monocrops and drowns its own market. `Econ` prices the *next* unit against
everything the farm has already committed to producing — standing crops,
placed animals, animals still in the shed — so the tenth melon is valued at
what the tenth melon will actually fetch. The farm then diversifies on its own:
melon until melon stops paying, then coops, then wheat. No rule says so.

**Price each job by the turn it costs.** A pen's whole-season total against a
single watering is not a comparison. Priced that way the farm covered itself in
pens worth thousands apiece and let every crop on it die of thirst. A planting
is worth its cycle divided by the actions in the cycle; an animal is worth its
season divided by the feeding, caring and collecting it will need. Then a
watering can be compared with a coop.

## What measurement overturned

Four things I would have got wrong by reasoning alone.

**More hands is worse.** Sixteen hands scored 32,800 where ten scored 55,200 on
the same seeds. The wage bill accelerates as `fib(n)` and the work a marginal
hand finds is the cheap end of the board — planting wheat, digging weeds. The
farm runs out of jobs worth a turn long before it runs out of coins to hire
with.

**Do not hedge against the opponent's melon.** We cannot see their shed and on
this ladder they are growing melon too, so pricing our supply as if we were the
only seller looks reckless. Measured in a mirror match where both farms flood
the same market, the reckless version won **10–0**, 60,046 coins to 44,385.
Melon is a common pool that only the town drains, about one unit a day. Holding
back does not protect the price; it hands the pool to whoever does not hold
back.

**Bank at three items, not six.** End of day banks everything anyway, so
banking early is only ever about selling sooner — and the shed holds a hundred
items, past which the overflow is discarded. Three beat six 8–4 head to head.

**When the matcher refuses a job, fix the till, not the matcher.** Games were
ending with twenty-four animals in the shed — 8,700 coins that earned nothing —
behind fourteen empty coops. Housing a bird was priced at its lifetime rate,
about 27 coins an action, against feeding jobs worth several hundred, so the
matcher never chose it. Repricing housing at what those two turns unlock made
it worse: 53,500 against 76,900. The turns really were better spent. The farm
now stops buying while four animals are waiting on a pen, and that went
**12–0**.

## Four bugs that all looked right in the source

Each was found by watching a game day by day rather than by reading.

* **The feed order was sized off the shed alone.** The units had just carried
  the wheat out of it, so the farm re-bought the whole day's feed on all
  twenty-four turns. The bank hit zero by day thirteen of every game.
* **Livestock was bought before feed.** Nine geese became three.
* **Empty pens were counted together.** A goose needs a coop and a cow a
  pasture; counting them as one number bought ten cows against six empty coops.
* **Animals waiting in the shed were not counted as supply.** Every purchase
  looked like the first one. One game bought fifteen sheep into a wool price
  that floors after thirty units.

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -U kaggle-environments pytest

# coins against a fixed opponent — shows whether a change moved the economy
.venv/bin/python scripts/bench.py --games 8

# the measurement that decides things: wins, with seats alternated
.venv/bin/python scripts/head2head.py main.py attempts/v8_scheduler_animals.py --games 12

.venv/bin/python -m pytest tests/ -q      # 63 tests
```

Seats are alternated because the two players are not symmetric in a shared
market. A four-game round robin between three variants once came out
non-transitive; it only resolved at eight games with alternating seats.

`bench.py` is the shortlist and `head2head.py` is the verdict — and the gap
between them is not academic. Every knob swept alone against `starter` looked
like a gain; combining the six winners gained nothing, because five of them were
noise on eight games. Worse, the single most valuable decision in the agent —
flooding the melon market — is one `starter` cannot test at all, because it does
not grow melon.

## Submitting

```bash
kaggle competitions submit kaggriculture -f main.py -m "..."
```

The ladder is Elo on **wins and losses only** — the coin margin never enters it,
and opponents are drawn from near your own rating. An earlier version of this
agent scored *higher* against `starter` than the one that replaced it and lost
every head-to-head game, which is why nothing here is decided on coins alone.

## What did not work

[`attempts/`](attempts/) keeps the earlier versions with their numbers, and
[`attempts/README.md`](attempts/README.md) says why each failed. The short list:
four attempts at an animal herd, all of which collapsed on the fact that `FEED`
takes wheat from the acting unit's own inventory rather than the shed; a
four-crop diversified farm that scores highest against `starter` and loses head
to head; and — the expensive one — a whole round spent concluding that animals
are dominated, measured in coins per *tile*-day on a 25-tile farm. Tiles were
never the scarce thing. Turns and market depth were.

## Licence

MIT.
