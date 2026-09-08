"""Kaggriculture agent — a scheduler, not a rulebook.

Every earlier version was a priority list: water before harvest, harvest before
plant, walk to the nearest job in whichever category came first. That throws
information away twice. It cannot say that watering a melon on day 9 is worth
more than harvesting a wheat, and it cannot say that a rich job three tiles away
beats a dull one underfoot.

So this one prices things. Every tile that wants work is scored in coins, every
(unit, job) pair is discounted by the walk, and the pairs are matched against
that score. Selling is priced the same way: the engine's price curve is
published, so the order size is computed from it rather than guessed at with a
hand-set floor.

Three engine facts shape the rest:

  * `SELL` spends from the shed, `HARVEST` fills a unit's pack. Produce that
    never reaches the shed is never money — end-of-day banking gets it there, a
    day late.
  * A seed unwatered on its planting day is a weed by morning, and two dry days
    kill a mature plant.
  * Unsold stock scores nothing, and a crop that cannot reach its first yield
    before the season closes is a seed set on fire.
"""

from __future__ import annotations

import math

# --------------------------------------------------------------------------
# the engine's own economics, so the agent can do arithmetic instead of guess
# --------------------------------------------------------------------------

CROPS = {
    "WHEAT":  {"seed": 10, "first": 2,  "max_day": 4,  "max_yield": 6},
    "CARROT": {"seed": 20, "first": 2,  "max_day": 3,  "max_yield": 4},
    "MELON":  {"seed": 80, "first": 10, "max_day": 12, "max_yield": 6},
}

# base, T, below shape, below target, above shape, above target
MARKET = {
    "WHEAT":      (25,  400, "sqrt",   0.80, "log",    0.20),
    "CARROT":     (35,  450, "hinge",  1.00, "sqrt",   0.70),
    "TOMATO":     (60,  200, "hinge",  0.40, "sqrt",   0.60),
    "STRAWBERRY": (120, 100, "sqrt",   0.70, "linear", 1.60),
    "MELON":      (250, 300, "log",    0.20, "sq",     3.60),
    "EGG":        (50,  332, "hinge",  0.40, "log",    0.20),
    "MILK":       (160, 122, "sqrt",   0.60, "linear", 1.60),
    "WOOL":       (200, 105, "log",    0.20, "sq",     3.20),
    "FERTILIZER": (100, 200, "linear", 0.40, "linear", 0.40),
}
I0 = 10000
HINGE_GAIN = 8.0
LAST_DAY = 29
SHED_TILES = ((4, 4), (5, 4), (4, 5), (5, 5))
MAX_ORDERS = 10


def _shape(func, x, T):
    x = max(0.0, x)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1.0 + x)
    if func == "hinge":
        u = x / T
        return u + HINGE_GAIN * max(0.0, u - 1.0) ** 2
    return x


def price_at(item, inventory):
    """The engine's published curve, reimplemented so the agent can plan.

    A sale is quoted at the inventory *before* the unit lands, so this answers
    "what does the next one fetch" and can be walked forward to size an order.
    """
    p = MARKET.get(item)
    if not p:
        return 0
    base, T, below_f, below_t, above_f, above_t = p
    if inventory < I0:
        amp = below_t * base / _shape(below_f, T, T)
        val = base + amp * _shape(below_f, I0 - inventory, T)
    else:
        amp = above_t * base / _shape(above_f, T, T)
        val = base - amp * _shape(above_f, inventory - I0, T)
    return max(1, int(round(val)))


def sell_quantity(item, inventory, have, reserve):
    """How many to sell before the marginal unit stops being worth selling.

    The price falls as the order fills, so this walks it forward and stops at
    the reservation price — rather than dumping the shed onto the floor or
    holding out for a number the market may never come back to.
    """
    n = 0
    while n < have and price_at(item, inventory + n) >= reserve:
        n += 1
    return n


# --------------------------------------------------------------------------
# planning: what is worth planting, given how much season is left
# --------------------------------------------------------------------------

GLUT_HAIRCUT = 0.55     # what a unit really fetches once our own supply lands


def crop_value(crop, day, price_now):
    """Coins a fresh planting is worth, or None if it cannot finish in time.

    A melon needs ten days to first yield; planted on day 20 it is eighty coins
    set on fire. Every earlier version kept planting the same crop to the last
    turn, which is the most expensive habit any of them had.
    """
    c = CROPS.get(crop)
    if not c or day + c["first"] > LAST_DAY:
        return None
    return c["max_yield"] * price_now * GLUT_HAIRCUT - c["seed"]


def choose_crop(day, prices):
    """The best coins per tile per day still able to finish."""
    best, best_rate = None, 0.0
    for crop in CROPS:
        v = crop_value(crop, day, prices.get(crop) or MARKET[crop][0])
        if v is None or v <= 0:
            continue
        rate = v / max(1, CROPS[crop]["first"])
        if rate > best_rate:
            best, best_rate = crop, rate
    return best


# --------------------------------------------------------------------------
# tasks: everything the farm wants doing, priced in coins
# --------------------------------------------------------------------------

def bonus_window(crop):
    """Watering inside this window adds a unit a day to the harvest."""
    c = CROPS.get(crop)
    return (math.ceil(c["max_day"] / 2), c["max_day"]) if c else (99, -1)


def build_tasks(tiles, day, prices, seeds, plant_crop):
    """(x, y, op, coins) for every tile worth an action this turn."""
    tasks = []
    plant_v = crop_value(plant_crop, day, prices.get(plant_crop) or
                         (MARKET[plant_crop][0] if plant_crop else 0)) if plant_crop else None

    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            if tile == "LOCKED":
                continue

            if tile is None:
                if plant_crop and seeds.get(plant_crop, 0) > 0 and plant_v and plant_v > 0:
                    tasks.append((x, y, ["PLANT", plant_crop], plant_v))
                continue

            if not isinstance(tile, dict):
                continue
            kind = tile.get("kind")

            if kind == "WEED":
                tasks.append((x, y, ["DIG"], max(5.0, (plant_v or 0) * 0.5)))
                continue
            if kind != "PLANT":
                continue

            crop = tile.get("crop", "WHEAT")
            c = CROPS.get(crop)
            if not c:
                continue
            age = day - tile.get("planted_day", day)
            units = tile.get("yield_units", 0)
            price = prices.get(crop) or MARKET.get(crop, (0,))[0]

            if age >= c["first"] and units > 0:
                tasks.append((x, y, ["HARVEST"], units * price * GLUT_HAIRCUT))

            if not tile.get("watered_today"):
                lo, hi = bonus_window(crop)
                if tile.get("consecutive_unwatered", 0) >= 1:
                    # one more dry day and the whole plant is a weed
                    tasks.append((x, y, ["WATER"],
                                  max(units, 1) * price * GLUT_HAIRCUT + 20.0))
                elif lo <= age <= hi:
                    tasks.append((x, y, ["WATER"], price * GLUT_HAIRCUT))
                else:
                    tasks.append((x, y, ["WATER"], 3.0))
    return tasks


# --------------------------------------------------------------------------
# assignment: units to tasks, discounted by the walk
# --------------------------------------------------------------------------

TRAVEL_COST = 0.14      # a step costs this share of a job's value


def step_toward(x, y, tx, ty):
    if y != ty:
        return "SOUTH" if ty > y else "NORTH"
    if x != tx:
        return "EAST" if tx > x else "WEST"
    return "PASS"


def assign(units, tasks):
    """Greedy maximum-weight matching of units to jobs.

    The assignment problem, solved greedily: score every pair once, sort, take
    them in order while both sides are free. With a dozen units and a few dozen
    jobs that lands within a few percent of optimal and costs nothing, which
    matters when it runs 720 times a game.
    """
    pairs = []
    for ui, (ux, uy) in enumerate(units):
        for ti, (tx, ty, _op, value) in enumerate(tasks):
            dist = abs(tx - ux) + abs(ty - uy)
            pairs.append((value / (1.0 + TRAVEL_COST * dist), ui, ti))
    pairs.sort(key=lambda p: -p[0])

    taken_u, taken_t, out = set(), set(), {}
    for _, ui, ti in pairs:
        if ui in taken_u or ti in taken_t:
            continue
        taken_u.add(ui)
        taken_t.add(ti)
        out[ui] = ti
    return out


# --------------------------------------------------------------------------
# the agent
# --------------------------------------------------------------------------

HANDS_PER_DAY = 5
DROP_AT = 6
SEED_BUFFER = 8
CASH_FLOOR = 120
RESERVE_FRACTION = 0.42   # sell down to this share of the base price


def agent(obs, config=None):
    me = obs["farms"][obs["player"]]
    private = obs["private"]
    tiles = me["tiles"]
    money = me["money"]
    day, hour = obs["day"], obs["hour"]
    prices = (obs.get("market") or {}).get("prices") or {}
    inventory = (obs.get("market") or {}).get("inventory") or {}
    shed = private.get("shed", {})
    seeds = private.get("seeds", {})
    invs = private.get("inventories", [])
    units = [tuple(me["farmer"])] + [tuple(p) for p in me.get("hands", [])]

    plant_crop = choose_crop(day, prices)

    # ---- market ----------------------------------------------------------
    market = []
    if hour == 0:
        for _ in range(HANDS_PER_DAY):
            market.append(["HIRE"])

    if plant_crop:
        want = SEED_BUFFER + len(units)
        have = seeds.get(plant_crop, 0)
        cost = CROPS[plant_crop]["seed"]
        if have < want and money > cost * 3 + CASH_FLOOR:
            n = min(want - have, int((money - CASH_FLOOR) // cost))
            if n > 0:
                market.append(["BUY_SEED", plant_crop, n])

    for item, count in sorted(shed.items(), key=lambda kv: -kv[1]):
        if count <= 0 or item not in MARKET or len(market) >= MAX_ORDERS:
            continue
        reserve = MARKET[item][0] * RESERVE_FRACTION
        n = sell_quantity(item, inventory.get(item, I0), count, reserve)
        if day >= LAST_DAY:
            n = count          # unsold stock scores nothing
        if n > 0:
            market.append(["SELL", item, int(n)])

    # ---- field -----------------------------------------------------------
    tasks = build_tasks(tiles, day, prices, seeds, plant_crop)

    carriers = set()
    for i in range(len(units)):
        inv = invs[i] if i < len(invs) else {}
        if sum(v for v in inv.values() if v) >= DROP_AT:
            carriers.add(i)

    chosen = assign(units, tasks)
    ops = []
    for i, (x, y) in enumerate(units):
        if i in carriers:
            if (x, y) in SHED_TILES:
                ops.append(["DROP"])
            else:
                tx, ty = min(SHED_TILES,
                             key=lambda p: abs(p[0] - x) + abs(p[1] - y))
                ops.append([step_toward(x, y, tx, ty)])
            continue

        ti = chosen.get(i)
        if ti is None:
            ops.append(["PASS"])
            continue
        tx, ty, op, _ = tasks[ti]
        ops.append(op if (tx, ty) == (x, y) else [step_toward(x, y, tx, ty)])

    return {"farmer": ops[0] if ops else ["PASS"],
            "hands": ops[1:],
            "market": market[:MAX_ORDERS]}
