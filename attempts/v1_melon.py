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
CROP = "MELON"
SEED_COST = 80
# Six, not twelve. Hands are nearly free, but every HIRE is a market order and
# only `maxMarketOrdersPerTurn` (10) are processed per turn — hiring twelve
# fills the queue at hour 0 and silently drops that turn's seed purchase and
# every sale behind it.
HANDS_PER_DAY = 3
SELL_BATCH = 6          # selling the whole shed at once craters the price
SEED_BUFFER = 8

SHED_TILES = [(4, 4), (5, 4), (4, 5), (5, 5)]

MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}


def _first_yield_day(crop: str) -> int:
    return {"WHEAT": 2, "CARROT": 2, "TOMATO": 8, "STRAWBERRY": 10, "MELON": 10}.get(crop, 2)


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
                    ready = age >= _first_yield_day(tile.get("crop", CROP))
                    if ready and tile.get("yield_units", 0) > 0:
                        jobs["harvest"].append((x, y))
                    elif not tile.get("watered_today"):
                        jobs["water"].append((x, y))
    return jobs


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

    # --- crew first: cheap, and it multiplies every later action -----------
    if hour == 0:
        for _ in range(HANDS_PER_DAY):
            market.append(["HIRE"])

    # --- keep enough seed that a free unit is never idle -------------------
    have = seeds.get(CROP, 0)
    want = SEED_BUFFER + len(units)
    if have < want and money > SEED_COST * 4:
        affordable = min(want - have, max(0, (money - 200) // SEED_COST))
        if affordable > 0:
            market.append(["BUY_SEED", CROP, int(affordable)])

    # --- sell in batches: a glut prices itself to the floor ----------------
    for item, count in sorted(shed.items()):
        if item == "FERTILIZER" or count <= 0:
            continue
        market.append(["SELL", item, min(count, SELL_BATCH)])

    jobs = _tile_jobs(me["tiles"], day)
    claimed: set = set()
    farmer_op = ["PASS"]
    hand_ops = []

    for i, (x, y) in enumerate(units):
        inv = inventories[i] if i < len(inventories) else {}
        carrying = sum(v for k, v in inv.items() if v)
        tile = me["tiles"][y][x] if 0 <= y < len(me["tiles"]) else None

        op = None

        # full hands go to the shed, otherwise the produce never becomes money
        if carrying >= 6:
            if (x, y) in SHED_TILES:
                op = ["DROP"]
            else:
                op = [_step_toward(x, y, *_nearest((x, y), SHED_TILES))]

        if op is None and isinstance(tile, dict):
            kind = tile.get("kind")
            if kind == "WEED":
                op = ["DIG"]
            elif kind == "PLANT":
                age = day - tile.get("planted_day", day)
                if age >= _first_yield_day(tile.get("crop", CROP)) and tile.get("yield_units", 0) > 0:
                    op = ["HARVEST"]
                elif not tile.get("watered_today"):
                    op = ["WATER"]

        if op is None and tile is None and seeds.get(CROP, 0) > 0:
            op = ["PLANT", CROP]

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
