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
