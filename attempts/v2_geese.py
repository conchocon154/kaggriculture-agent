"""Kaggriculture agent — geese, because eggs and manure do not crash.

The first version of this farmed melon and made 27k. Melon sells for 250, which
is the trap: its price curve is `sq` with an above-target of 3.60, so roughly
300 units past the starting inventory takes it to the $1 floor. A melon farm
sells its first few dozen fruit well and the rest for a dollar.

Eggs and fertiliser are the opposite. Both decay as `log` / `linear` with small
targets — an egg is still worth about $40 after six hundred have been sold. A
goose costs 300, lays every day for the rest of the season, and drops one
fertiliser a day whether or not it was fed. It repays itself in about three days
and then never stops.

So the farm is coops, the crop is wheat — which is what the geese eat, and which
is itself glut-proof — and produce is sold continuously rather than hoarded.

Two engine details this is built around, neither of them obvious from the rules:
  * Inventory is banked to the shed automatically at end of day, so walking to
    the shed mid-day is a wasted action. Only the 100-item shed cap matters.
  * A seed not watered on the day it is planted is a weed by morning.
"""

from __future__ import annotations

# --- economics ------------------------------------------------------------
FEED_CROP = "WHEAT"

# Sell floors read off the price table. Below these the market is saturated and
# a unit is worth more sitting in the shed until the town eats the glut.
SELL_FLOOR = {"EGG": 30, "FERTILIZER": 40, "WHEAT": 15, "MELON": 60,
              "CARROT": 18, "MILK": 60, "WOOL": 80, "STRAWBERRY": 60,
              "TOMATO": 25}
SHED_PRESSURE = 78          # past this, sell anyway — overflow is binned at 100

# --- crew -----------------------------------------------------------------
# Hands cost 1, 1, 2, 3, 5, 8, 13, 21 ... and the counter resets each morning.
# They are dribbled out over several turns because every HIRE is a market order
# and only `maxMarketOrdersPerTurn` (10) are processed per turn — issuing them
# all at hour 0 silently drops that turn's purchases and sales.
TARGET_HANDS = 9
HIRES_PER_TURN = 3
CARRY_WHEAT = 12            # feed comes out of the unit's own inventory

# --- capital --------------------------------------------------------------
GOOSE_COST = 300
CASH_BUFFER = 150           # low: feed is cheap and a stall here starves the flock
LAND_COSTS = [1000, 2000, 4000]

SHED_TILES = [(4, 4), (5, 4), (4, 5), (5, 5)]
MOVES = {"NORTH": (0, -1), "SOUTH": (0, 1), "EAST": (1, 0), "WEST": (-1, 0)}


def _step_toward(x, y, tx, ty):
    if y != ty:
        return "SOUTH" if ty > y else "NORTH"
    if x != tx:
        return "EAST" if tx > x else "WEST"
    return "PASS"


def _nearest(pos, options):
    x, y = pos
    return min(options, key=lambda p: abs(p[0] - x) + abs(p[1] - y))


def _survey(tiles, day):
    """Every tile that wants something, grouped by what it wants."""
    s = {"animal": [], "unfed": [], "empty_coop": [], "empty": [], "weed": [],
         "water": [], "harvest_crop": [], "coops": 0, "geese": 0, "all_fed": True}
    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            if tile == "LOCKED":
                continue
            if tile is None:
                s["empty"].append((x, y))
            elif isinstance(tile, dict):
                kind = tile.get("kind")
                if kind == "WEED":
                    s["weed"].append((x, y))
                elif kind in ("COOP", "PASTURE"):
                    s["coops"] += 1
                    if tile.get("animal"):
                        s["geese"] += 1
                        s["animal"].append((x, y))
                        if not tile.get("fed_today"):
                            s["unfed"].append((x, y))
                        if tile.get("consecutive_unfed", 0) > 0:
                            s["all_fed"] = False
                    else:
                        s["empty_coop"].append((x, y))
                elif kind == "PLANT":
                    age = day - tile.get("planted_day", day)
                    if age >= 2 and tile.get("yield_units", 0) > 0:
                        s["harvest_crop"].append((x, y))
                    elif not tile.get("watered_today"):
                        s["water"].append((x, y))
    return s


def _animal_job(tile, carried_wheat):
    """What this animal needs most, or None if it is fully serviced.

    Order matters: an unfed animal drops its banked care bonus and escapes after
    two days, so feeding outranks everything.
    """
    if not tile.get("fed_today"):
        # FEED takes the wheat out of this unit's pack, not out of the shed
        return ["FEED"] if carried_wheat > 0 else None
    if tile.get("yield_units", 0) > 0:
        return ["HARVEST"]
    if tile.get("fertilizer_available"):
        return ["COLLECT_FERTILIZER"]
    if not tile.get("cared_today") and tile.get("fed_today"):
        return ["CARE"]
    return None


def agent(obs, config=None):
    player = obs["player"]
    me = obs["farms"][player]
    private = obs["private"]
    tiles = me["tiles"]
    money = me["money"]
    day = obs["day"]
    prices = (obs.get("market") or {}).get("prices") or {}
    shed = private.get("shed", {})
    seeds = private.get("seeds", {})
    inventories = private.get("inventories", [])
    units = [tuple(me["farmer"])] + [tuple(p) for p in me.get("hands", [])]

    s = _survey(tiles, day)
    # one coop per goose we could plausibly buy, plus a little headroom
    coop_target = s["geese"] + 4
    shed_total = sum(v for k, v in shed.items() if v > 0)
    shed_wheat = shed.get(FEED_CROP, 0)
    geese_in_shed = shed.get("GOOSE", 0)
    need_wheat = s["geese"] * 3 + 6

    market = []

    # --- crew, dribbled out so the order queue is never full ---------------
    hired = me.get("hires_today", 0)
    if hired < TARGET_HANDS and money > 60:
        for _ in range(min(HIRES_PER_TURN, TARGET_HANDS - hired)):
            market.append(["HIRE"])

    # --- land, once the farm is genuinely full -----------------------------
    owned = len(me.get("unlocked_quadrants", ["NW"]))
    if owned <= len(LAND_COSTS) and not s["empty"] and s["coops"] > 0:
        if money > LAND_COSTS[owned - 1] + CASH_BUFFER * 3:
            market.append(["BUY_LAND"])

    # --- geese, as fast as coops and cash allow ----------------------------
    room = len(s["empty_coop"]) - geese_in_shed
    if room > 0 and s["all_fed"] and money > GOOSE_COST + CASH_BUFFER * 2:
        want = min(room, int((money - CASH_BUFFER) // GOOSE_COST), 3)
        if want > 0:
            market.append(["BUY_ANIMAL", "GOOSE", want])

    # --- feed: one wheat per goose per day ---------------------------------
    if shed_wheat < need_wheat and money > CASH_BUFFER * 2:
        market.append(["BUY_PRODUCT", FEED_CROP, int(need_wheat - shed_wheat)])
    if seeds.get(FEED_CROP, 0) < 4 and money > CASH_BUFFER:
        market.append(["BUY_SEED", FEED_CROP, 6])

    # --- sell, but only into a price still worth taking --------------------
    pressure = shed_total >= SHED_PRESSURE
    for item, count in sorted(shed.items(), key=lambda kv: -kv[1]):
        if count <= 0 or item == "GOOSE":
            continue
        if item == FEED_CROP:
            count -= need_wheat          # never sell the geese's dinner
            if count <= 0:
                continue
        if prices.get(item, 0) >= SELL_FLOOR.get(item, 20) or pressure:
            market.append(["SELL", item, int(count)])
        if len(market) >= 9:
            break

    # --- unit assignment ---------------------------------------------------
    claimed: set = set()
    ops = []

    for i, (x, y) in enumerate(units):
        inv = inventories[i] if i < len(inventories) else {}
        in_bounds = 0 <= y < len(tiles) and 0 <= x < len(tiles[0])
        tile = tiles[y][x] if in_bounds else "LOCKED"
        op = None

        if isinstance(tile, dict):
            kind = tile.get("kind")
            if kind in ("COOP", "PASTURE") and tile.get("animal"):
                op = _animal_job(tile, inv.get(FEED_CROP, 0))
            elif kind in ("COOP", "PASTURE") and inv.get("GOOSE", 0) > 0:
                op = ["PLACE", "GOOSE"]
            elif kind == "WEED":
                op = ["DIG"]
            elif kind == "PLANT":
                if not tile.get("watered_today"):
                    op = ["WATER"]
                elif (tile.get("yield_units", 0) > 0
                      and day - tile.get("planted_day", day) >= 2):
                    op = ["HARVEST"]

        needs_feed_run = bool(s["unfed"]) and inv.get(FEED_CROP, 0) == 0 and shed_wheat > 0

        if op is None and (x, y) in SHED_TILES:
            if geese_in_shed > 0 and not inv.get("GOOSE"):
                op = ["PICKUP", "GOOSE", 1]          # a goose in the shed earns nothing
            elif (inv.get(FEED_CROP, 0) < CARRY_WHEAT and shed_wheat > 0
                  and s["geese"]):
                op = ["PICKUP", FEED_CROP, CARRY_WHEAT]

        if op is None and tile is None:
            if s["coops"] < coop_target:
                op = ["BUILD_COOP"]
            elif seeds.get(FEED_CROP, 0) > 0:
                op = ["PLANT", FEED_CROP]

        if op is None:
            target = None
            # carrying a goose? only a coop is worth walking to
            if inv.get("GOOSE", 0) > 0 and s["empty_coop"]:
                free = [p for p in s["empty_coop"] if p not in claimed]
                if free:
                    target = _nearest((x, y), free)
            if target is None and needs_feed_run:
                target = _nearest((x, y), SHED_TILES)
            if target is None and inv.get(FEED_CROP, 0) > 0 and s["unfed"]:
                free = [p for p in s["unfed"] if p not in claimed]
                if free:
                    target = _nearest((x, y), free)
            if target is None:
                for key in ("animal", "water", "harvest_crop", "empty_coop",
                            "empty", "weed"):
                    free = [p for p in s[key] if p not in claimed]
                    if free:
                        target = _nearest((x, y), free)
                        break
            if target is None and geese_in_shed > 0:
                target = _nearest((x, y), SHED_TILES)
            if target:
                claimed.add(target)
                op = [_step_toward(x, y, *target)]

        ops.append(op or ["PASS"])

    return {"farmer": ops[0] if ops else ["PASS"],
            "hands": ops[1:],
            "market": market[:10]}
