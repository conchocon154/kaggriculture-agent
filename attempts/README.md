# Attempts that did not make it

Kept because the measurements are the useful part, and because two of these
looked better than the agent that shipped right up until they were measured
against a real opponent instead of against the built-in `starter`.

| File | Idea | vs `starter` | vs the shipped agent |
|---|---|---:|---|
| `v1_melon.py` | melon monoculture, 3 hands | 27,332 | loses 0/10 |
| `v2_geese.py` | all-in on geese: eggs and fertiliser | 17–400 | never got off the ground |
| `v3_diversified.py` | four crops, price floors, 9 hands, land | 29,161 | loses 1/6 |
| `v4_crops_plus_geese.py` | v3 plus a few coops beside the shed | 3,000 | broken |

## v2 and v4 — the geese

The price table says this should win. Melon decays as `sq` with an above-target
of 3.60, so about 300 units past the start it is worth $1. Egg decays as `log`
at 0.20: still about $40 after six hundred are sold. Fertiliser is similar, and
animals drop one a day for free. A goose costs 300, lays daily for the rest of
the season, and pays for itself in roughly three days.

It never worked, and the reason is logistics rather than economics. `FEED` takes
the wheat out of **the acting unit's own inventory** — not the shed, which is
what the rules read like:

```python
if op == "FEED":
    ...
    if not _inv_take(inv, "WHEAT", 1):
        return
```

So every goose, every day, needs a unit that is both standing on it *and*
carrying wheat. That is a walk to the shed, a `PICKUP`, and a walk back, against
an animal that escapes permanently after two missed feeds. Three versions of the
supply chain all leaked: the flock oscillated 6 → 4 → 5 → 3 while the money sat
at the cash buffer, because every coin earned went into replacing the geese that
had just starved.

Worth another attempt with a dedicated keeper unit and coops adjacent to the
shed. It is not worth guessing at — the whole thing turns on how many actions a
feed round costs, which is measurable.

## v3 — diversifying

Four crops instead of one, each sold only above a price floor. Against the
`starter` it is the best agent here: **29,161 against the shipped agent's
26,458**. Head-to-head against the melon monoculture it loses.

Both reasons are the same reason. Spreading production over four crops means
producing fewer melons, and melon is where the money is; against a melon
specialist you have simply handed them the high half of the price curve. And a
price floor is a promise not to sell — which an opponent can enforce on you by
keeping the price under it. Every variant tried (no floors, floors halved, shed
pressure from 80 down to 12) still lost.

This is the one worth remembering: it scores better and plays worse.

---

## Round two: reading the public meta

The competition rules permit public code sharing and license anything shared
that way under an OSI licence (§3.6.b), so the public notebooks are fair
reading. Four were pulled and read; nothing was copied. The top agents turn out
to be largely **distilled 720-turn tapes** replayed from leader replays rather
than reactive logic, which is neither transferable nor mine to take.

Sources read:

| Notebook | What it established |
|---|---|
| [Rayk Kretzschmar — Findings from Zero to Top Meta](https://www.kaggle.com/code/raykkretzschmar/kaggriculture-findings-from-zero-to-top-meta) | The meta converges on ~8 cows, 6 sheep, 3 quadrants, 12 hands; the live edge is sale *timing*, not herd composition |
| [Ryo Hasegawa — Submission Strategy](https://www.kaggle.com/competitions/kaggriculture/discussion/736219) | The ladder is Elo on wins and losses only; never re-submit an unchanged bot |
| [SIDHAARTH SHREE — Documentation vs Engine Discrepancies](https://www.kaggle.com/competitions/kaggriculture/discussion/732450) | Fertiliser *is* sellable; a seed unwatered on its planting day is a weed by morning; DIG fails on occupied structures |
| tetsu2131 — Shape the Shop, Work the Pasture | Mostly replay visualisation |

Four things the meta says, each tested head-to-head against the shipped agent
with seats alternated, six games apiece:

| Meta advice | Result |
|---|---|
| hire ~10–12 hands, the fib region is cheap | 7, 9, 10, 12 and 14 hands all **lose 0–6** |
| take three quadrants (NE + SW) | **loses 0–6** at every crew size tried |
| bank produce earlier, since `SELL` only sees the shed | drop threshold 1, 2, 3, 4 and 12 all **lose**; 8 ties |
| liquidate the shed in the closing turns | **ties** at steps 600, 660, 690 and 710 |

None of it transfers, and the reason is coherent: twelve hands and three
quadrants are one system with an eight-cow herd, which is what gives that many
units something to do. Grafting the labour and the land onto a twenty-five-tile
melon monoculture buys wage bills and land costs against work that does not
exist. The terminal liquidation ties because the shed is already empty — this
agent's sales keep pace with its harvest, so there was nothing left to dump.

## v7 — the herd, a fourth time

`v7_herd_on_melon.py`. Pastures on eight tiles beside the shed, cows bought from
day 6 out of melon income, and — the fix for the failure in v2 — a **single
pickup of twenty-five wheat** so one unit can service the whole herd for a day
instead of walking back to the shed after every four.

647 against `starter`. It also carried a plain ordering bug for a while
(`jobs` used in the market block before it was computed, which killed the
episode at day 6 with an `UnboundLocalError`); fixing that moved it from 208 to
647, which is to say from broken to still broken. The melon pipeline collapses
whenever the herd code is present and four attempts have not isolated why.

## Where this leaves it

Roughly thirty variants have now been measured head-to-head. The shipped agent
wins every one of them. It is a local optimum for a melon monoculture, and the
route past it is the herd architecture — which is worth another attempt with a
dedicated keeper unit and a clean rewrite rather than a bolt-on, but not worth
another bolt-on.

Per Ryo Hasegawa's post, an unchanged agent should not be re-submitted: it
retires a converged rating for a fresh one at 600 and changes nothing about the
final Bradley-Terry ranking. So nothing was submitted this round.

## v8 — the scheduler, and the ceiling nobody noticed

`v8_scheduler_base.py`, `v8_scheduler_crops.py`, `v8_scheduler_animals.py`. The
clean rewrite the last entry called for: jobs priced in coins, units matched by
greedy assignment, sell sizes computed off the published curve. It beat v7
10–0 and scored 34,118 against `starter`.

On the ladder it finished **6,505th of 8,221** at 428.9, against a top score of
2,933 and a median of 793.

The round ended by concluding that animals are dominated — measured in coins per
*tile*-day on a 25-tile farm, where melon comes out at 74.5 against a cow's
48.1. The arithmetic was right and the question was wrong twice over. The farm
is 100 tiles, not 25, because `BUY_LAND` exists and no version had ever called
it. And tiles were never the scarce thing: turns are, and market depth is.
Integrating the engine's price curve says melon pays about 26,000 coins for a
whole season and then nothing, while eggs and fertiliser never crash. An agent
whose plan is melon has a ceiling, and v8 was sitting on it.

## v9 — the whole board

`main.py`. Land, a flock, and every decision priced at the margin and per
action. 80,232 against `starter`; 12–0 against both v8 submissions, at roughly
64,000 coins to 28,000.

Four bugs in it were found by watching a game day by day rather than by reading
the source, and every one of them looked correct on the page: the feed order was
re-bought on all twenty-four turns of the day, livestock was bought ahead of
feed, coops and pastures were counted as one pool, and animals waiting in the
shed did not count as supply. Details in the top-level README.

## Where this leaves it

The habit that produced the ceiling is worth naming, because it survived seven
versions: every round was measured against `starter`, and `starter` cannot test
the decisions that matter. It does not grow melon, so it cannot say whether to
flood the melon market — the single most valuable call in the agent, worth 10–0
in a mirror match. It does not buy land, so a farm playing a quarter of the
board still beat it comfortably enough to look healthy.
