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

# A few geese, and only on tiles next to the shed. Eggs and fertiliser barely
# move on price no matter how many are sold, which makes them the one income
# stream a farm cannot glut. The catch is FEED takes wheat out of the unit's own
# pack, so every goose is a walk to the shed and back — putting the coops next
# to the shed is what makes that affordable.
GOOSE_COST = 300
COOP_TILES = [(3, 3), (4, 3), (3, 4), (2, 3), (3, 2), (2, 2)]
CARRY_WHEAT = 10

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
    jobs = {"harvest": [], "water": [], "plant": [], "dig": [],
            "animal": [], "empty_coop": [], "unfed": [], "geese": 0}
    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            if tile == "LOCKED":
                continue
            if tile is None:
                jobs["plant"].append((x, y))
            elif isinstance(tile, dict):
                kind = tile.get("kind")
                if kind in ("COOP", "PASTURE"):
                    if tile.get("animal"):
                        jobs["geese"] += 1
                        jobs["animal"].append((x, y))
                        if not tile.get("fed_today"):
                            jobs["unfed"].append((x, y))
                    else:
                        jobs["empty_coop"].append((x, y))
                elif kind == "WEED":
                    jobs["dig"].append((x, y))
                elif kind == "PLANT":
                    age = day - tile.get("planted_day", day)
                    ready = age >= _first_yield_day(tile.get("crop", "WHEAT"))
                    if ready and tile.get("yield_units", 0) > 0:
                        jobs["harvest"].append((x, y))
                    elif not tile.get("watered_today"):
                        jobs["water"].append((x, y))
    return jobs


def _animal_job(tile, carried_wheat):
    if not tile.get("fed_today"):
        return ["FEED"] if carried_wheat > 0 else None
    if tile.get("yield_units", 0) > 0:
        return ["HARVEST"]
    if tile.get("fertilizer_available"):
        return ["COLLECT_FERTILIZER"]
    if not tile.get("cared_today"):
        return ["CARE"]
    return None


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
    inventories = private.get("inventories", [])
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

    # --- geese to fill any empty coop
    geese_in_shed = shed.get("GOOSE", 0)
    room = len(jobs["empty_coop"]) - geese_in_shed
    if room > 0 and money > GOOSE_COST + CASH_BUFFER * 3:
        market.append(["BUY_ANIMAL", "GOOSE", min(room, 2)])
    # feed stock: a goose that misses two days is gone, and 300 coins with it
    if jobs["geese"] and shed.get("WHEAT", 0) < jobs["geese"] * 3 + 8:
        market.append(["BUY_PRODUCT", "WHEAT", int(jobs["geese"] * 3 + 8)])

    # --- sell only into a price still worth taking
    pressure = shed_total >= SHED_PRESSURE
    for item, count in sorted(shed.items(), key=lambda kv: -kv[1]):
        if count <= 0 or len(market) >= 10:
            continue
        if item == "GOOSE":
            continue
        if item == "WHEAT":
            count -= jobs["geese"] * 3 + 8
            if count <= 0:
                continue
        if prices.get(item, 0) >= SELL_FLOOR.get(item, 20) or pressure:
            market.append(["SELL", item, int(count)])

    jobs = _tile_jobs(me["tiles"], day)
    claimed: set = set()
    farmer_op = ["PASS"]
    hand_ops = []

    for i, (x, y) in enumerate(units):
        tile = me["tiles"][y][x] if 0 <= y < len(me["tiles"]) else None
        inv = inventories[i] if i < len(inventories) else {}
        op = None

        if isinstance(tile, dict) and tile.get("kind") in ("COOP", "PASTURE"):
            if tile.get("animal"):
                op = _animal_job(tile, inv.get("WHEAT", 0))
            elif inv.get("GOOSE", 0) > 0:
                op = ["PLACE", "GOOSE"]

        if op is None and (x, y) in SHED_TILES:
            if geese_in_shed > 0 and not inv.get("GOOSE"):
                op = ["PICKUP", "GOOSE", 1]
            elif jobs["geese"] and inv.get("WHEAT", 0) < CARRY_WHEAT \
                    and shed.get("WHEAT", 0) > 0:
                op = ["PICKUP", "WHEAT", CARRY_WHEAT]

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

        if op is None and tile is None and (x, y) in COOP_TILES:
            op = ["BUILD_COOP"]

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
            if inv.get("GOOSE", 0) > 0 and jobs["empty_coop"]:
                free = [p for p in jobs["empty_coop"] if p not in claimed]
                if free:
                    target = _nearest((x, y), free)
            if target is None and inv.get("WHEAT", 0) > 0 and jobs["unfed"]:
                free = [p for p in jobs["unfed"] if p not in claimed]
                if free:
                    target = _nearest((x, y), free)
            if target is None and (geese_in_shed > 0 or
                                   (jobs["unfed"] and inv.get("WHEAT", 0) == 0
                                    and shed.get("WHEAT", 0) > 0)):
                target = _nearest((x, y), SHED_TILES)
            if target is None:
                for key in ("animal", "harvest", "water", "plant", "dig"):
                    free = [p for p in jobs[key] if p not in claimed]
                    if free:
                        target = _nearest((x, y), free)
                        break
            if target:
                claimed.add(target)
            op = [_step_toward(x, y, *target)] if target else ["PASS"]

        if i == 0:
            farmer_op = op
        else:
            hand_ops.append(op)

    return {"farmer": farmer_op, "hands": hand_ops, "market": market}
