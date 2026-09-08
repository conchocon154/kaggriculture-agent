"""Kaggriculture agent — priced at the margin, played on the whole board.

The version this replaces scored 34,000 coins against the built-in starter and
sat at rank 6,505 on the ladder. Reading the engine's own price table explains
the gap, and it is not a tuning gap:

    units sold      30      100      250      400   price of the 400th
    MELON        7,416   21,721   26,577   26,727      $1
    EGG          1,371    4,371   10,559   16,559     $40
    FERTILIZER   2,913    9,010   18,775   24,040     $20
    WHEAT          687    2,193    5,313    8,313     $20

Melon is the best thing on the board and it is worth about 26,000 coins for the
entire season, shared with the opponent. Everything past that has to come from
the curves that never crash — eggs and the fertiliser that comes free with the
bird producing them. So the season is: melon while melon is deep, then a flock,
funded by melon, on land bought with melon money.

Three engine facts the old version did not use:

  * `BUY_LAND` turns 25 tiles into 100 for 7,000 coins — cheaper than three
    geese. The old agent never called it and played a quarter of the game.
  * A hand costs `fib(n)` coins for the day, so the twelfth hand of the day
    costs 144 for twenty-four actions. Hands are the cheapest thing in the game
    and the old agent bought five of them.
  * End of day empties every pack into the shed anyway, so walking back to bank
    a single item — which is what `DROP_AT = 1` did — buys nothing but steps.

And one arithmetic fact. Pricing a crop at a flat fraction of base says every
empty tile wants the same crop, so the farm monocrops and drowns its own
market. Pricing each *successive* tile at the price the market will be showing
once the tiles before it have sold makes the farm diversify on its own: melon
until melon stops paying, then coops, then wheat.
"""

from __future__ import annotations

import math

# --------------------------------------------------------------------------
# the engine's own economics, so the agent can do arithmetic instead of guess
# --------------------------------------------------------------------------

# `peak_age` is the age with the best coins per tile-day without fertiliser,
# and `peak_yield` what a harvest then returns. Wheat and carrot list 6 and 4
# in the rules; those are fertilised numbers. Watering alone reaches 4 and 3.
# `actions` is the whole cycle: plant, the waterings that keep it alive and
# earn the bonus, and the harvest. It is the denominator that lets a planting
# be compared with a watering.
CROPS = {
    "WHEAT":  {"seed": 10, "first": 2,  "max_day": 4,  "peak_age": 4,
               "peak_yield": 4, "actions": 6},
    "CARROT": {"seed": 20, "first": 2,  "max_day": 3,  "peak_age": 3,
               "peak_yield": 3, "actions": 5},
    "MELON":  {"seed": 80, "first": 10, "max_day": 12, "peak_age": 10,
               "peak_yield": 6, "actions": 12},
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
    "GOOSE": {"cost": 300, "pen": "COOP",    "first": 4, "interval": 1,
              "held": 4, "product": "EGG"},
    "COW":   {"cost": 400, "pen": "PASTURE", "first": 8, "interval": 2,
              "held": 6, "product": "MILK"},
    "SHEEP": {"cost": 500, "pen": "PASTURE", "first": 6, "interval": 3,
              "held": 6, "product": "WOOL"},
}

I0 = 10000
HINGE_GAIN = 8.0
LAST_DAY = 29
SHED_TILES = ((4, 4), (5, 4), (4, 5), (5, 5))
SHED_CAP = 100
MAX_ORDERS = 10
LAND_PRICES = (1000, 2000, 4000)


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
    """How many to sell before the marginal unit stops being worth selling."""
    n = 0
    while n < have and price_at(item, inventory + n) >= reserve:
        n += 1
    return n


# --------------------------------------------------------------------------
# the margin
# --------------------------------------------------------------------------

# We cannot see the opponent's shed, and on this ladder they are growing melon
# too. Pricing our own supply as if it were the only supply is what makes an
# agent plant a whole farm of melon and sell it for a dollar. Assume they match
# us: it costs a little melon upside and buys a lot of protection, and the
# alternative sink — eggs — has no ceiling to miss out on.
RIVAL_SUPPLY = 1.0


class Econ:
    """Prices the *next* unit, remembering what the farm already owes the market.

    Every valuation in this file goes through here, so a decision is never
    priced at today's board price when the farm is already holding twenty of
    the thing. That single change is what makes the planner diversify.
    """

    def __init__(self, market_inv, standing, day, money):
        self.inv = dict(market_inv or {})
        self.pipeline = dict(standing or {})
        self.day = day
        self.money = money

    def _floor(self, item):
        return (self.inv.get(item, I0)
                + self.pipeline.get(item, 0) * (1.0 + RIVAL_SUPPLY))

    def price(self, item):
        return price_at(item, int(self._floor(item)))

    def batch(self, item, n):
        """Coins for `n` more units, sold at the tail of what we already owe."""
        base = int(self._floor(item))
        return float(sum(price_at(item, base + i) for i in range(int(n))))

    def commit(self, item, n):
        self.pipeline[item] = self.pipeline.get(item, 0) + n


def per_tile_day(total, days):
    """Totals over different horizons are not comparable.

    A melon returns its coins over eleven days and a goose over the rest of the
    season. Comparing raw totals says the goose is worth more than the melon
    on day zero, which is how an earlier version covered the farm in pens it
    could not afford to stock.
    """
    return total / max(1.0, days)


def crop_value(crop, day, econ):
    """Coins a fresh planting returns, or None if it cannot finish in time."""
    c = CROPS.get(crop)
    if not c or day + c["peak_age"] > LAST_DAY:
        return None
    return econ.batch(crop, c["peak_yield"]) - c["seed"]


def crop_rate(crop, day, econ):
    """Coins per action, which is the only currency the matcher can spend.

    Comparing a planting's whole-cycle total against a single watering is how
    an earlier version covered the board in pens worth five thousand coins
    apiece and let every crop on it die of thirst. A turn is a turn.
    """
    v = crop_value(crop, day, econ)
    if v is None:
        return None
    return v / CROPS[crop]["actions"]


def animal_value(kind, day, econ):
    """Coins an animal bought today returns over the rest of the season.

    Three streams. The product, on its own schedule. The care bonus, which
    banks one unit per fed-and-cared day and pays out in full at the next
    production — so a daily producer that is cared for every day yields two a
    day, and that doubling is most of why a goose beats a cow. And one
    fertiliser per animal per day, which arrives whether or not it was fed and
    sells near a hundred coins. Against that, the bird and a wheat a day.
    """
    a = ANIMALS.get(kind)
    if not a:
        return None
    producing = LAST_DAY - day - a["first"]
    if producing <= 0:
        return None
    alive = LAST_DAY - day

    harvests = producing // a["interval"] + 1
    units = harvests * (1 + a["interval"])      # base plus the banked care
    product = econ.batch(a["product"], units)
    fertiliser = econ.batch("FERTILIZER", alive)
    feed = alive * econ.price("WHEAT")
    return product + fertiliser - a["cost"] - feed


def animal_actions(kind, day):
    """Build, place, then feed, care and collect daily and harvest on schedule."""
    a = ANIMALS[kind]
    alive = max(1, LAST_DAY - day)
    return 2 + alive * (3.0 + 1.0 / a["interval"])


def animal_rate(kind, day, econ):
    v = animal_value(kind, day, econ)
    return v / animal_actions(kind, day) if v is not None else None


def _stocked_rate(kind, day, econ):
    """Rate for an animal already bought and waiting in the shed.

    Its price is spent either way, so it comes back into the numerator: the
    only question left is whether the turns to house it and keep it beat the
    turns spent elsewhere.
    """
    v = animal_value(kind, day, econ)
    if v is None:
        return 0.0
    return (v + ANIMALS[kind]["cost"]) / animal_actions(kind, day)


def best_crop(day, econ):
    """The crop with the best coins per tile-day that can still finish."""
    best, best_rate = None, 0.0
    for crop in CROPS:
        r = crop_rate(crop, day, econ)
        if r is not None and r > best_rate:
            best, best_rate = crop, r
    return best, best_rate


def best_animal(day, econ, money):
    best, best_rate = None, 0.0
    for kind, a in ANIMALS.items():
        if a["cost"] + CASH_FLOOR > money:
            continue
        r = animal_rate(kind, day, econ)
        if r is not None and r > best_rate:
            best, best_rate = kind, r
    return best, best_rate


# --------------------------------------------------------------------------
# tasks: everything the farm wants doing, priced in coins
# --------------------------------------------------------------------------

def bonus_window(crop):
    """Watering inside this window adds a unit a day to the harvest."""
    c = CROPS.get(crop)
    return ((c["max_day"] + 1) // 2, c["max_day"]) if c else (99, -1)


# A goose wants feeding, caring, collecting and harvesting: call it three and a
# half actions a day, and a unit that spends half its turns walking has about
# twelve useful ones. Past this the flock starves faster than it lays.
BIRDS_PER_UNIT = 3
CASH_FLOOR = 150


def build_tasks(tiles, day, econ, seeds, shed, n_units, hungry_value=0.0,
                stocked=0, animal=None, pen_budget=0, empty_pens=None):
    """(x, y, op, coins, need) for every tile worth an action this turn.

    `need` is a precondition on the acting unit — feeding spends a wheat from
    that unit's own pack, and placing an animal means carrying one. Without it
    the richest job on the board goes to an empty-handed unit every turn and
    the flock starves in sight of the shed.

    Empty tiles are priced one at a time against a running commitment, so the
    tenth melon is valued at what the tenth melon will actually fetch.
    """
    shed = shed or {}
    empty_pens = empty_pens or {}
    tasks = []
    empties = []
    pens_left = min(pen_budget, max(0, BIRDS_PER_UNIT * n_units - stocked))

    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            if tile == "LOCKED":
                continue

            if tile is None:
                empties.append((x, y))
                continue

            if not isinstance(tile, dict):
                continue
            kind = tile.get("kind")

            if kind == "WEED":
                _, weed_rate = best_crop(day, econ)
                tasks.append((x, y, ["DIG"], max(4.0, weed_rate * 0.5), None))
                continue

            if kind in ("COOP", "PASTURE"):
                tasks.extend(_animal_tasks(x, y, tile, day, econ, shed))
                continue

            if kind != "PLANT":
                continue

            crop = tile.get("crop", "WHEAT")
            c = CROPS.get(crop)
            if not c:
                continue
            age = day - tile.get("planted_day", day)
            units = tile.get("yield_units", 0)
            price = econ.price(crop)

            # Harvest at peak, or as soon as the season leaves no more time.
            if units > 0 and age >= c["first"] and (
                    age >= c["peak_age"] or day >= LAST_DAY):
                tasks.append((x, y, ["HARVEST"], units * price, None))

            if not tile.get("watered_today"):
                lo, hi = bonus_window(crop)
                if tile.get("consecutive_unwatered", 0) >= 1:
                    # one more dry day and the whole plant is a weed
                    tasks.append((x, y, ["WATER"],
                                  max(units, 1) * price + 20.0, None))
                elif lo <= age <= hi:
                    tasks.append((x, y, ["WATER"], float(price), None))
                # Outside the window and not yet thirsty, watering buys
                # nothing: the plant survives a skipped day, so the turn is
                # worth more anywhere else.

    # Empty tiles, priced in descending order against a running commitment.
    empties.sort(key=lambda p: min(abs(p[0] - sx) + abs(p[1] - sy)
                                   for sx, sy in SHED_TILES))
    # A bought animal with nowhere to live outranks everything: it is already
    # paid for and earns nothing until it has a pen. Only count the ones the
    # empty pens do not already cover, or the farm lays down a fresh pen for
    # the same bird on every one of the day's twenty-four turns.
    stranded = []
    for k, a in ANIMALS.items():
        missing = shed.get(k, 0) - empty_pens.get(a["pen"], 0)
        stranded.extend([k] * max(0, missing))

    for x, y in empties:
        crop, c_rate = best_crop(day, econ)
        if stranded:
            k = stranded.pop(0)
            tasks.append((x, y, ["BUILD_" + ANIMALS[k]["pen"]],
                          (animal_rate(k, day, econ) or 1.0) * 2.0, None))
            continue
        a_rate = animal_rate(animal, day, econ) if animal else None

        if animal and a_rate and pens_left > 0 and a_rate >= c_rate:
            tasks.append((x, y, ["BUILD_" + ANIMALS[animal]["pen"]],
                          a_rate, None))
            pens_left -= 1
            # A pen we have decided to build is a bird we have decided to buy.
            a = ANIMALS[animal]
            producing = LAST_DAY - day - a["first"]
            harvests = max(0, producing // a["interval"] + 1)
            econ.commit(a["product"], harvests * (1 + a["interval"]))
            econ.commit("FERTILIZER", LAST_DAY - day)
        elif crop and c_rate > 0 and seeds.get(crop, 0) > 0:
            tasks.append((x, y, ["PLANT", crop], c_rate, None))
            econ.commit(crop, CROPS[crop]["peak_yield"])
        else:
            break

    # The shed: feed to carry out, and a bought animal to walk to its pen.
    for sx, sy in SHED_TILES:
        if shed.get("WHEAT", 0) > 0 and hungry_value > 0:
            tasks.append((sx, sy, ["PICKUP", "WHEAT", CARRY_WHEAT],
                          hungry_value, None))
        for kind in ANIMALS:
            if shed.get(kind, 0) > 0:
                r = _stocked_rate(kind, day, econ)
                if r > 0:
                    tasks.append((sx, sy, ["PICKUP", kind, 1], r, None))
    return tasks


def _animal_tasks(x, y, tile, day, econ, shed):
    """A pen, empty or occupied."""
    out = []
    kind = tile.get("animal")
    if not kind:
        for k in ANIMALS:
            if shed.get(k, 0) > 0 and ANIMALS[k]["pen"] == tile.get("kind"):
                r = _stocked_rate(k, day, econ)
                if r > 0:
                    out.append((x, y, ["PLACE", k], r * 1.5, k))
        return out

    a = ANIMALS.get(kind)
    if not a:
        return out
    price = econ.price(a["product"])
    units = tile.get("yield_units", 0)

    if not tile.get("fed_today"):
        # On an ordinary day feeding buys that day's production and the right
        # to bank a care bonus. On the second dry day it buys the bird: two
        # missed feeds and it escapes, taking its price and every remaining
        # day of income with it.
        if tile.get("consecutive_unfed", 0) >= 1:
            worth = (animal_value(kind, day, econ) or 0.0) + a["cost"]
        else:
            worth = price * (1.0 + a["interval"]) / a["interval"]
        out.append((x, y, ["FEED"], max(worth, 20.0), "WHEAT"))
    if units > 0:
        # Product sitting on the tile is capped, so a full pen stops producing.
        urgency = 2.0 if units >= a["held"] else 1.0
        out.append((x, y, ["HARVEST"], units * price * urgency, None))
    if tile.get("fertilizer_available"):
        out.append((x, y, ["COLLECT_FERTILIZER"], float(econ.price("FERTILIZER")),
                    None))
    if tile.get("fed_today") and not tile.get("cared_today"):
        # One action, banked, paid out in full at the next production: for a
        # daily layer that is a second egg tomorrow.
        out.append((x, y, ["CARE"], float(price), None))
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
    them in order while both sides are free. With a dozen units and a hundred
    jobs that lands within a few percent of optimal and costs nothing, which
    matters when it runs 720 times a game.
    """
    carrying = carrying or [{} for _ in units]
    pairs = []
    for ui, (ux, uy) in enumerate(units):
        held = carrying[ui] if ui < len(carrying) else {}
        for ti, task in enumerate(tasks):
            tx, ty, value = task[0], task[1], task[3]
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

# Measured, and against expectation: more hands is worse. Sixteen hands scored
# 32,800 where ten scored 55,200 on the same seeds. The wage bill is fib(n),
# and the work a marginal hand finds is the cheap end of the board — planting
# wheat, digging weeds — so the farm runs out of jobs worth a turn well before
# it runs out of coins to hire with.
MAX_HANDS = 10
HIRE_HOURS = 1
# A hand costs fib(n) coins for twenty-four actions, so the twelfth of the day
# costs 144 and the fifteenth costs 610. Spending this share of the bank a day
# lands near a dozen early and a little over that once melon money arrives,
# which is roughly where the marginal hand stops paying for itself.
HIRE_BUDGET = 0.15
DROP_AT = 6              # a melon tile's worth; end of day banks the rest
# Land is bought once the farm has run out of tiles to work, not before, and
# never down to the last coin: an empty quadrant earns nothing and a farm with
# no seed money cannot fill it.
LAND_AT_EMPTY = 4
LAND_RESERVE = 900
# Livestock is the second call on the bank, after seed and after the wage bill.
STOCK_RESERVE = 700
SEED_CAP = 30
# Sell down to this share of base. Low on purpose: the market only recovers by
# what the town eats, about one unit a day, so stock held back for a better
# price is mostly stock that never sells.
RESERVE_FRACTION = 0.18
# FEED spends a wheat from the acting unit's own pack, not the shed. One pickup
# of this many lets a unit work a whole row of pens instead of walking back
# after every bird — the mistake that sank four earlier attempts.
CARRY_WHEAT = 12


def _fib(n):
    a, b = 1, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def hires_wanted(money, jobs, already):
    """How many more hands to take on, against the fib price and the work."""
    budget = money * HIRE_BUDGET
    spent = sum(_fib(i) for i in range(already))
    n = already
    while n < MAX_HANDS and n < jobs:
        cost = _fib(n)
        if spent + cost > budget:
            break
        spent += cost
        n += 1
    return n - already


def _future_production(kind, day, placed_day):
    """What an animal will still put on the market this season."""
    a = ANIMALS[kind]
    out = {"FERTILIZER": max(0, LAST_DAY - day)}
    first = placed_day + a["first"]
    left = LAST_DAY - max(day, first)
    if left >= 0:
        out[a["product"]] = (left // a["interval"] + 1) * (1 + a["interval"])
    return out


def standing_supply(tiles, shed, invs, day):
    """Everything the farm is already going to put on the market.

    Growing crops count at what they will yield, not what they hold today —
    a field of melon is a melon glut ten days before it is a harvest.
    """
    supply = {}
    for item, n in (shed or {}).items():
        if n <= 0:
            continue
        if item in MARKET:
            supply[item] = supply.get(item, 0) + n
        elif item in ANIMALS:
            # A bought animal is a standing order too, even before it has a
            # pen. Leaving it out made every purchase look like the first one:
            # one game bought fifteen sheep against a wool price that floors
            # after thirty units, and never housed any of them.
            for prod, count in _future_production(item, day, day).items():
                supply[prod] = supply.get(prod, 0) + count
    for inv in invs or []:
        for item, n in (inv or {}).items():
            if item in MARKET and n > 0:
                supply[item] = supply.get(item, 0) + n
    for row in tiles:
        for tile in row:
            if not isinstance(tile, dict):
                continue
            if tile.get("kind") == "PLANT":
                c = CROPS.get(tile.get("crop"))
                if c:
                    crop = tile["crop"]
                    supply[crop] = supply.get(crop, 0) + c["peak_yield"]
            elif tile.get("animal"):
                # An animal already on the board is a standing order for the
                # rest of the season, not the four units on its tile. Counting
                # only what it holds today let the planner buy a fourth cow
                # after the milk price had already been sold to the floor.
                for prod, count in _future_production(
                        tile["animal"], day, tile.get("placed_day", day)).items():
                    supply[prod] = supply.get(prod, 0) + count
    return supply


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
    quadrants = len(me.get("unlocked_quadrants") or ["NW"])

    econ = Econ(inventory, standing_supply(tiles, shed, invs, day), day, money)

    # Empty pens have to be counted by kind. A goose needs a coop and a cow a
    # pasture, and counting them together bought ten cows against six empty
    # coops — five thousand seven hundred coins of livestock that sat in the
    # shed until the season ended.
    pens = {"hungry": 0, "stock": 0, "COOP": 0, "PASTURE": 0}
    for row in tiles:
        for t in row:
            if isinstance(t, dict) and t.get("kind") in ("COOP", "PASTURE"):
                if t.get("animal"):
                    pens["stock"] += 1
                    if not t.get("fed_today"):
                        pens["hungry"] += 1
                else:
                    pens[t["kind"]] += 1
    # One trip to the shed feeds a row of pens, so the pickup is worth what it
    # unlocks spread over the walk — not one feed, and not the whole flock.
    feed_worth = econ.price("EGG") * 2.0
    hungry_value = min(pens["hungry"], CARRY_WHEAT) * feed_worth / 3.0

    empty_now = sum(1 for row in tiles for t in row if t is None)

    # Decide the livestock once, here, and let both the pens and the purchase
    # follow it. Choosing again inside the planner built thirty-one pastures
    # for a shed full of geese, which want coops.
    animal, _ = best_animal(day, econ, money)
    pen_budget = 0
    if animal:
        a = ANIMALS[animal]
        waiting = shed.get(animal, 0)
        # Never build a pen we cannot put a bird in: an empty pen is a tile
        # taken out of production for nothing.
        pen_budget = int(max(0, money - STOCK_RESERVE) // a["cost"]) \
            - pens[a["pen"]] - waiting

    tasks = build_tasks(tiles, day, econ, seeds, shed, len(units),
                        hungry_value, pens["stock"], animal, pen_budget,
                        {"COOP": pens["COOP"], "PASTURE": pens["PASTURE"]})

    # ---- market ----------------------------------------------------------
    market = []

    # Feed first, and before anything else buys. Wheat's glut curve is a log,
    # so buying it back barely moves the price — a wheat field to feed the
    # flock would be tiles and actions spent on the cheapest thing on the
    # board. Ordering this after livestock starved six geese out of nine in a
    # game the agent otherwise led: it kept buying animals it could not feed.
    #
    # The count has to include the packs. Sizing the order off the shed alone
    # re-bought the whole day's feed on all twenty-four turns, because the
    # units had just carried it out of the shed.
    feed_needed = (pens["stock"] * 2 + CARRY_WHEAT) if pens["stock"] else 0
    on_hand = shed.get("WHEAT", 0) + sum(i.get("WHEAT", 0) for i in invs)
    short = feed_needed - on_hand
    wheat_price = max(1, prices.get("WHEAT", 25))
    if short > 0 and money > wheat_price:
        n = min(short, int(money // wheat_price))
        market.append(["BUY_PRODUCT", "WHEAT", int(n)])
        money -= n * wheat_price

    # Hiring is capped at ten market orders a turn, so a farm that wants more
    # than ten hands has to keep asking on the turns after. Doing it only at
    # hour zero silently held the workforce at ten all season.
    if hour < HIRE_HOURS:
        for _ in range(hires_wanted(money, len(tasks), me.get("hires_today", 0))):
            market.append(["HIRE"])

    # Land. Twenty-five more tiles for a thousand coins is cheaper than three
    # geese — but only once the tiles already owned are working. Buying a
    # quadrant on day zero spends the melon budget on dirt.
    if quadrants - 1 < len(LAND_PRICES) and empty_now <= LAND_AT_EMPTY:
        price = LAND_PRICES[quadrants - 1]
        if money >= price + LAND_RESERVE:
            market.append(["BUY_LAND"])
            money -= price

    plant_crop, _ = best_crop(day, econ)
    if plant_crop:
        want = min(empty_now + len(units), SEED_CAP)
        have = seeds.get(plant_crop, 0)
        cost = CROPS[plant_crop]["seed"]
        if have < want and money > cost * 2 + CASH_FLOOR:
            n = min(want - have, int((money - CASH_FLOOR) // cost))
            if n > 0:
                market.append(["BUY_SEED", plant_crop, n])
                money -= n * cost

    # A bird for every empty pen of the right kind, once one is worth buying —
    # and never while animals already on the board are going unfed.
    if animal and not pens["hungry"]:
        # Every animal is three and a half actions a day for the rest of the
        # season. Buying past what the workforce can service leaves livestock
        # in the shed — which is exactly what the matcher then, correctly,
        # refuses to spend turns on.
        labour = BIRDS_PER_UNIT * len(units) - pens["stock"] \
            - sum(shed.get(k, 0) for k in ANIMALS)
        room = min(pens[ANIMALS[animal]["pen"]] - shed.get(animal, 0), labour)
        cost = ANIMALS[animal]["cost"]
        if room > 0 and money > cost + STOCK_RESERVE:
            n = min(room, int((money - CASH_FLOOR) // cost), 4)
            if n > 0:
                market.append(["BUY_ANIMAL", animal, n])
                money -= n * cost


    # Selling. The shed holds a hundred items and end of day discards the
    # overflow, so a full shed is produce burnt.
    room_pressure = sum(shed.values()) > SHED_CAP * 0.7
    for item, count in sorted(shed.items(), key=lambda kv: -kv[1]):
        if count <= 0 or item not in MARKET or len(market) >= MAX_ORDERS:
            continue
        if item == "WHEAT" and pens["stock"]:
            count -= max(0, feed_needed - sum(i.get("WHEAT", 0) for i in invs))
            if count <= 0:
                continue
        reserve = MARKET[item][0] * RESERVE_FRACTION
        n = sell_quantity(item, inventory.get(item, I0), count, reserve)
        if day >= LAST_DAY or room_pressure:
            n = count          # unsold stock scores nothing, and so does burnt
        if n > 0:
            market.append(["SELL", item, int(n)])

    # ---- field -----------------------------------------------------------
    held = [invs[i] if i < len(invs) else {} for i in range(len(units))]

    # A unit is "loaded" only for produce it cannot use. An animal it carries
    # is going to a pen, and wheat is feed — but only while there is a flock.
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
