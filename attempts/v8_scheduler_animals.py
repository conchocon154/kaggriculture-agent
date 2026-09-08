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
ANIMALS = {
    "GOOSE": {"cost": 300, "pen": "COOP",    "first": 4, "interval": 1, "product": "EGG"},
    "COW":   {"cost": 400, "pen": "PASTURE", "first": 8, "interval": 2, "product": "MILK"},
    "SHEEP": {"cost": 500, "pen": "PASTURE", "first": 6, "interval": 3, "product": "WOOL"},
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


def animal_value(kind, day, prices):
    """Coins an animal bought today returns over the rest of the season.

    Two income streams, and the second is the one that is easy to miss: the
    product, whose price collapses under volume for milk and wool, and one
    fertiliser a day per animal, which arrives whether or not the animal was
    fed and whose price barely moves. Against that, the purchase and a wheat a
    day in feed.
    """
    a = ANIMALS.get(kind)
    if not a:
        return None
    producing_days = LAST_DAY - day - a["first"]
    if producing_days <= 0:
        return None
    alive_days = LAST_DAY - day

    product_price = prices.get(a["product"]) or MARKET[a["product"]][0]
    fert_price = prices.get("FERTILIZER") or MARKET["FERTILIZER"][0]
    wheat_price = prices.get("WHEAT") or MARKET["WHEAT"][0]

    product = (producing_days / a["interval"]) * product_price * GLUT_HAIRCUT
    fertiliser = alive_days * fert_price * GLUT_HAIRCUT
    feed = alive_days * wheat_price
    return product + fertiliser - a["cost"] - feed


def per_tile_day(total, days):
    """Totals over different horizons are not comparable.

    A melon returns its coins over ten days and a cow over the rest of the
    season, so comparing the raw totals says a cow is worth twice a melon when
    per tile-day the melon is ahead. Getting this wrong once cost 25,000 coins
    a game: the farm covered itself in pens it could not afford to stock.
    """
    return total / max(1.0, days)


def choose_animal(day, prices, money):
    """The best animal still worth buying, or None."""
    best, best_rate = None, 0.0
    for kind, a in ANIMALS.items():
        if a["cost"] + CASH_FLOOR > money:
            continue
        v = animal_value(kind, day, prices)
        if v is None:
            continue
        rate = per_tile_day(v, LAST_DAY - day)
        if rate > best_rate:
            best, best_rate = kind, rate
    return best


def animal_rate(kind, day, prices):
    v = animal_value(kind, day, prices)
    return per_tile_day(v, LAST_DAY - day) if v is not None else None


def choose_crop(day, prices):
    """The best coins per tile per day still able to finish."""
    best, best_rate = None, 0.0
    for crop in CROPS:
        v = crop_value(crop, day, prices.get(crop) or MARKET[crop][0])
        if v is None or v <= 0:
            continue
        rate = per_tile_day(v, CROPS[crop]["first"])
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


def build_tasks(tiles, day, prices, seeds, plant_crop, animal=None,
                shed=None, hungry_value=0.0):
    """(x, y, op, coins, need) for every tile worth an action this turn.

    `need` is a precondition the acting unit must satisfy — feeding costs a
    wheat out of the unit's own pack, and placing an animal means carrying one.
    """
    shed = shed or {}
    tasks = []
    animal_v = animal_value(animal, day, prices) if animal else None
    animal_r = animal_rate(animal, day, prices) if animal else None
    plant_v = crop_value(plant_crop, day, prices.get(plant_crop) or
                         (MARKET[plant_crop][0] if plant_crop else 0)) if plant_crop else None
    plant_r = per_tile_day(plant_v, CROPS[plant_crop]["first"]) \
        if (plant_crop and plant_v) else 0.0

    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            if tile == "LOCKED":
                continue

            if tile is None:
                # an empty tile is worth whichever of a crop or a pen pays more
                if animal and animal_r and animal_r > plant_r * ANIMAL_MARGIN:
                    tasks.append((x, y, ["BUILD_" + ANIMALS[animal]["pen"]],
                                  animal_v, None))
                elif plant_crop and seeds.get(plant_crop, 0) > 0 and plant_v and plant_v > 0:
                    tasks.append((x, y, ["PLANT", plant_crop], plant_v, None))
                continue

            if not isinstance(tile, dict):
                continue
            kind = tile.get("kind")

            if kind == "WEED":
                tasks.append((x, y, ["DIG"], max(5.0, (plant_v or 0) * 0.5), None))
                continue

            if kind in ("COOP", "PASTURE"):
                tasks.extend(_animal_tasks(x, y, tile, day, prices, animal,
                                           animal_v, shed, hungry_value))
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
                tasks.append((x, y, ["HARVEST"], units * price * GLUT_HAIRCUT, None))

            if not tile.get("watered_today"):
                lo, hi = bonus_window(crop)
                if tile.get("consecutive_unwatered", 0) >= 1:
                    # one more dry day and the whole plant is a weed
                    tasks.append((x, y, ["WATER"],
                                  max(units, 1) * price * GLUT_HAIRCUT + 20.0, None))
                elif lo <= age <= hi:
                    tasks.append((x, y, ["WATER"], price * GLUT_HAIRCUT, None))
                else:
                    tasks.append((x, y, ["WATER"], 3.0, None))

    # the shed: collecting feed, and fetching a bought animal out to a pen
    for sx, sy in SHED_TILES:
        if shed.get("WHEAT", 0) > 0 and hungry_value > 0:
            tasks.append((sx, sy, ["PICKUP", "WHEAT", CARRY_WHEAT],
                          hungry_value, None))
        for kind in ANIMALS:
            if shed.get(kind, 0) > 0:
                v = animal_value(kind, day, prices) or 0.0
                if v > 0:
                    tasks.append((sx, sy, ["PICKUP", kind, 1], v, None))
    return tasks


def _animal_tasks(x, y, tile, day, prices, animal, animal_v, shed, hungry_value):
    """A pen, empty or occupied."""
    out = []
    kind = tile.get("animal")
    if not kind:
        for k in ANIMALS:
            if shed.get(k, 0) > 0 and ANIMALS[k]["pen"] == tile.get("kind"):
                v = animal_value(k, day, prices) or 0.0
                out.append((x, y, ["PLACE", k], v, k))
        return out

    a = ANIMALS.get(kind, ANIMALS["COW"])
    price = prices.get(a["product"]) or MARKET[a["product"]][0]
    fert = prices.get("FERTILIZER") or MARKET["FERTILIZER"][0]
    units = tile.get("yield_units", 0)

    if not tile.get("fed_today"):
        # two unfed days and the animal escapes for good, taking its purchase
        # price and every remaining day of income with it
        at_risk = (animal_value(kind, day, prices) or 0.0) + a["cost"] * 0.5
        if tile.get("consecutive_unfed", 0) >= 1:
            at_risk *= 2.0
        out.append((x, y, ["FEED"], max(at_risk, 30.0), "WHEAT"))
    if units > 0:
        out.append((x, y, ["HARVEST"], units * price * GLUT_HAIRCUT, None))
    if tile.get("fertilizer_available"):
        out.append((x, y, ["COLLECT_FERTILIZER"], fert * GLUT_HAIRCUT, None))
    if tile.get("fed_today") and not tile.get("cared_today"):
        out.append((x, y, ["CARE"], price * GLUT_HAIRCUT * 0.8, None))
    return out


# --------------------------------------------------------------------------
# assignment: units to tasks, discounted by the walk
# --------------------------------------------------------------------------

# A step costs this share of a job's value. Tuned, not chosen: at 0.30 units
# ignore distant work that is worth the walk; at 0.0 every unit sets off across
# the board for the single richest job and the farm collapses to nothing.
TRAVEL_COST = 0.05


def step_toward(x, y, tx, ty):
    if y != ty:
        return "SOUTH" if ty > y else "NORTH"
    if x != tx:
        return "EAST" if tx > x else "WEST"
    return "PASS"


def assign(units, tasks, carrying=None):
    """Greedy maximum-weight matching of units to jobs.

    The assignment problem, solved greedily: score every pair once, sort, take
    them in order while both sides are free. With a dozen units and a few dozen
    jobs that lands within a few percent of optimal and costs nothing, which
    matters when it runs 720 times a game.
    """
    carrying = carrying or [{} for _ in units]
    pairs = []
    for ui, (ux, uy) in enumerate(units):
        held = carrying[ui] if ui < len(carrying) else {}
        for ti, task in enumerate(tasks):
            tx, ty, _op, value = task[0], task[1], task[2], task[3]
            need = task[4] if len(task) > 4 else None
            if need and held.get(need, 0) <= 0:
                continue          # cannot feed without wheat, cannot place
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
DROP_AT = 1              # banked produce is the only produce that can be sold
SEED_BUFFER = 8
CASH_FLOOR = 120
# Sell down to this share of base. Low on purpose: holding stock for a better
# price only pays if nobody else is supplying the same market, and on a ladder
# of farmers somebody always is.
RESERVE_FRACTION = 0.25
# FEED spends a wheat from the acting unit's own pack, not the shed. One pickup
# of this many lets a unit work the whole herd for a day instead of walking
# back after every animal — the mistake that sank four earlier attempts.
CARRY_WHEAT = 12
# An animal has to beat the crop by this much before a tile is converted. A
# melon price dip is usually our own supply landing and it recovers as the town
# eats the glut; without a margin the farm rebuilds itself every time that
# happens and never finishes anything.
ANIMAL_MARGIN = 1.35
FEED_ITEMS = ("WHEAT",) + tuple(ANIMALS)


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
    animal = choose_animal(day, prices, money)

    pens = {"empty": 0, "hungry": 0, "stock": 0}
    for row in tiles:
        for t in row:
            if isinstance(t, dict) and t.get("kind") in ("COOP", "PASTURE"):
                if t.get("animal"):
                    pens["stock"] += 1
                    if not t.get("fed_today"):
                        pens["hungry"] += 1
                else:
                    pens["empty"] += 1
    hungry_value = pens["hungry"] * 40.0

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

    # an animal for every empty pen, once one is worth buying
    if animal:
        waiting = sum(shed.get(k, 0) for k in ANIMALS)
        room = pens["empty"] - waiting
        if room > 0 and money > ANIMALS[animal]["cost"] + CASH_FLOOR * 2:
            n = min(room, int((money - CASH_FLOOR) // ANIMALS[animal]["cost"]), 2)
            if n > 0:
                market.append(["BUY_ANIMAL", animal, n])

    # feed, bought rather than grown: a wheat a head a day plus a pack to carry
    feed_needed = (pens["stock"] + CARRY_WHEAT) if pens["stock"] else 0
    if pens["stock"] and shed.get("WHEAT", 0) < feed_needed and money > CASH_FLOOR * 3:
        market.append(["BUY_PRODUCT", "WHEAT",
                       int(feed_needed - shed.get("WHEAT", 0))])

    for item, count in sorted(shed.items(), key=lambda kv: -kv[1]):
        if count <= 0 or item not in MARKET or len(market) >= MAX_ORDERS:
            continue
        if item == "WHEAT":
            count -= feed_needed          # that is the herd's dinner
            if count <= 0:
                continue
        reserve = MARKET[item][0] * RESERVE_FRACTION
        n = sell_quantity(item, inventory.get(item, I0), count, reserve)
        if day >= LAST_DAY:
            n = count          # unsold stock scores nothing
        if n > 0:
            market.append(["SELL", item, int(n)])

    # ---- field -----------------------------------------------------------
    tasks = build_tasks(tiles, day, prices, seeds, plant_crop, animal,
                        shed, hungry_value)

    held = [invs[i] if i < len(invs) else {} for i in range(len(units))]

    # A unit is only "loaded" for produce it cannot use. An animal it is
    # carrying is going to a pen, and wheat is feed — but only while there is a
    # herd. With no animals, wheat is the late-season crop, and treating it as
    # feed left it sitting in packs, never banked and never sold.
    reserved = tuple(ANIMALS) + (("WHEAT",) if pens["stock"] else ())
    carriers = set()
    for i, inv in enumerate(held):
        sellable = sum(v for k, v in inv.items() if v and k not in reserved)
        if sellable >= DROP_AT:
            carriers.add(i)

    chosen = assign(units, tasks, held)
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
        tx, ty, op = tasks[ti][0], tasks[ti][1], tasks[ti][2]
        ops.append(op if (tx, ty) == (x, y) else [step_toward(x, y, tx, ty)])

    return {"farmer": ops[0] if ops else ["PASS"],
            "hands": ops[1:],
            "market": market[:MAX_ORDERS]}
