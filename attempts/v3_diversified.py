"""Kaggriculture agent.

The season is 720 turns and every unit you own acts on every one of them, so
the binding constraint is actions, not money. Farm hands cost
`1, 1, 2, 3, 5, 8, ...` coins and the counter resets each morning, which means a
full crew for a day costs less than a single wheat seed. Hiring is therefore the
first thing this agent does every day, and everything else is arranged around
having a lot of hands rather than a lot of capital.

The rest is a short crop loop kept deliberately near the shed: plant, water,
harvest, walk the produce to the shed, sell it in small batches so the price
does not collapse under its own supply.
"""

from __future__ import annotations

# --- tuning ---------------------------------------------------------------
# Melon, not wheat. Wheat cycles in 2 days and its price decays gently, which
# reads like the safe staple — but melon sells for ten times as much and still
# clears six units a plant, and the ablation puts it three times ahead even
# after its price collapses under the volume. See scripts/ablate.py.
# Not one crop but four. Each product has its own market inventory and its own
# price curve, so a farm that sells only melon is competing against itself:
# melon decays as `sq` with an above-target of 3.60, which puts it on the $1
# floor about 300 units past the start. Splitting production across four
# products means four separate curves to walk down instead of one to fall off.
CROPS = ["MELON", "STRAWBERRY", "CARROT", "WHEAT"]
SEED_COST = {"MELON": 80, "STRAWBERRY": 100, "CARROT": 20, "WHEAT": 10}

# Read off the price table: below these the market is saturated and a unit is
# worth more in the shed until the town's shops eat the glut and the price
# recovers. Selling into a floored price is giving produce away.
SELL_FLOOR = {"MELON": 70, "STRAWBERRY": 45, "CARROT": 16, "WHEAT": 14,
              "TOMATO": 24, "FERTILIZER": 40}
SHED_PRESSURE = 80          # past this the shed bins the overflow at 100
# Six, not twelve. Hands are nearly free, but every HIRE is a market order and
# only `maxMarketOrdersPerTurn` (10) are processed per turn — hiring twelve
# fills the queue at hour 0 and silently drops that turn's seed purchase and
# every sale behind it.
# Nine, not three. Three was the optimum only because all the hires went out in
# one turn and the tenth market order was dropped; dribbling them over several
# turns lifts the cap, and hands are 1, 1, 2, 3, 5, 8 ... resetting daily.
TARGET_HANDS = 9
HIRES_PER_TURN = 3
SEED_BUFFER = 10
LAND_COSTS = [1000, 2000, 4000]
CASH_BUFFER = 300

SHED_TILES = [(4, 4), (5, 4), (4, 5), (5, 5)]

MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}


FIRST_YIELD = {"WHEAT": 2, "CARROT": 2, "TOMATO": 8, "STRAWBERRY": 10, "MELON": 10}


def _first_yield_day(crop: str) -> int:
    return FIRST_YIELD.get(crop, 2)


def _crop_for(x: int, y: int) -> str:
    """A fixed spatial rotation. Deterministic, so a tile always grows the same
    thing and the four products come off the farm at a steady mix."""
    return CROPS[(x + 2 * y) % len(CROPS)]


def _step_toward(x: int, y: int, tx: int, ty: int) -> str:
    """One orthogonal step. Vertical first, arbitrarily but consistently."""
    if y != ty:
        return "SOUTH" if ty > y else "NORTH"
    if x != tx:
        return "EAST" if tx > x else "WEST"
    return "PASS"


def _tile_jobs(tiles, day: int) -> dict:
    """Every tile that wants an action, keyed by what it wants."""
    jobs = {"harvest": [], "water": [], "plant": [], "dig": []}
    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            if tile == "LOCKED":
                continue
            if tile is None:
                jobs["plant"].append((x, y))
            elif isinstance(tile, dict):
                kind = tile.get("kind")
                if kind == "WEED":
                    jobs["dig"].append((x, y))
                elif kind == "PLANT":
                    age = day - tile.get("planted_day", day)
                    ready = age >= _first_yield_day(tile.get("crop", "WHEAT"))
                    if ready and tile.get("yield_units", 0) > 0:
                        jobs["harvest"].append((x, y))
                    elif not tile.get("watered_today"):
                        jobs["water"].append((x, y))
    return jobs


def jobs_empty_tiles(tiles) -> bool:
    return any(t is None for row in tiles for t in row)


def _nearest(pos, options):
    x, y = pos
    return min(options, key=lambda p: abs(p[0] - x) + abs(p[1] - y))


def agent(obs, config=None):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    money = me["money"]
    day = obs["day"]
    hour = obs["hour"]

    units = [tuple(me["farmer"])] + [tuple(p) for p in me.get("hands", [])]
    seeds = private.get("seeds", {})
    shed = private.get("shed", {})

    market = []
    prices = (obs.get("market") or {}).get("prices") or {}
    shed_total = sum(v for v in shed.values() if v > 0)

    # --- crew, dribbled out: every HIRE is a market order and only ten are
    #     processed per turn, so issuing nine at hour 0 drops the rest of the
    #     queue behind them
    hired = me.get("hires_today", 0)
    if hired < TARGET_HANDS and money > 60:
        for _ in range(min(HIRES_PER_TURN, TARGET_HANDS - hired)):
            market.append(["HIRE"])

    # --- land, once the farm is genuinely full
    owned = len(me.get("unlocked_quadrants", ["NW"]))
    if owned <= len(LAND_COSTS) and not jobs_empty_tiles(me["tiles"]):
        if money > LAND_COSTS[owned - 1] + CASH_BUFFER * 4:
            market.append(["BUY_LAND"])

    # --- keep a little seed of every crop so a free unit is never idle
    for crop in CROPS:
        if seeds.get(crop, 0) < 3 and money > SEED_COST[crop] * 6 + CASH_BUFFER:
            market.append(["BUY_SEED", crop, 4])
        if len(market) >= 7:
            break

    # --- sell only into a price still worth taking
    pressure = shed_total >= SHED_PRESSURE
    for item, count in sorted(shed.items(), key=lambda kv: -kv[1]):
        if count <= 0 or len(market) >= 10:
            continue
        if prices.get(item, 0) >= SELL_FLOOR.get(item, 20) or pressure:
            market.append(["SELL", item, int(count)])

    jobs = _tile_jobs(me["tiles"], day)
    claimed: set = set()
    farmer_op = ["PASS"]
    hand_ops = []

    for i, (x, y) in enumerate(units):
        tile = me["tiles"][y][x] if 0 <= y < len(me["tiles"]) else None

        op = None

        if op is None and isinstance(tile, dict):
            kind = tile.get("kind")
            if kind == "WEED":
                op = ["DIG"]
            elif kind == "PLANT":
                age = day - tile.get("planted_day", day)
                if age >= _first_yield_day(tile.get("crop", "WHEAT")) and tile.get("yield_units", 0) > 0:
                    op = ["HARVEST"]
                elif not tile.get("watered_today"):
                    op = ["WATER"]

        if op is None and tile is None:
            crop = _crop_for(x, y)
            if seeds.get(crop, 0) > 0:
                op = ["PLANT", crop]
            else:
                stocked = [c for c in CROPS if seeds.get(c, 0) > 0]
                if stocked:
                    op = ["PLANT", stocked[0]]

        if op is None:
            # head for the most valuable unclaimed job on the board
            target = None
            for key in ("harvest", "water", "plant", "dig"):
                free = [p for p in jobs[key] if p not in claimed]
                if free:
                    target = _nearest((x, y), free)
                    claimed.add(target)
                    break
            op = [_step_toward(x, y, *target)] if target else ["PASS"]

        if i == 0:
            farmer_op = op
        else:
            hand_ops.append(op)

    return {"farmer": farmer_op, "hands": hand_ops, "market": market}
