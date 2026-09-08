"""Tests for the scheduler.

The game is slow to simulate, so these drive the pieces directly and the agent
with hand-built observations. Three things are worth pinning down: that the
reimplemented price curve still matches the engine's, that the planner refuses
to buy a seed that cannot finish the season, and that the action dict keeps its
shape — a malformed one is a silent no-op for a whole turn, which is expensive
and invisible.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("kagagent", ROOT / "main.py")
kagagent = importlib.util.module_from_spec(spec)
sys.modules["kagagent"] = kagagent
spec.loader.exec_module(kagagent)

agent = kagagent.agent
I0 = kagagent.I0


def obs(tiles=None, farmer=(0, 0), hands=(), money=3000, day=0, hour=5,
        seeds=None, shed=None, inventories=None, prices=None, inventory=None):
    if tiles is None:
        tiles = [[None if x < 5 and y < 5 else "LOCKED" for x in range(10)]
                 for y in range(10)]
    return {
        "player": 0, "day": day, "hour": hour, "step": day * 24 + hour,
        "farms": [{"money": money, "tiles": tiles, "farmer": list(farmer),
                   "hands": [list(h) for h in hands],
                   "unlocked_quadrants": ["NW"], "hires_today": 0}],
        "private": {
            "shed": shed or {},
            "seeds": seeds if seeds is not None else {"MELON": 9},
            "inventories": inventories or [{} for _ in range(1 + len(hands))],
        },
        "market": {"inventory": inventory or {}, "prices": prices or {}},
        "town": {"unlocked_shops": []},
    }


def plant(crop="MELON", day=0, watered=True, units=0, dry=0):
    return {"kind": "PLANT", "crop": crop, "planted_day": day,
            "watered_today": watered, "consecutive_unwatered": dry,
            "yield_units": units, "fertilized_until_day": -1}


def econ(day=0, market=None, standing=None, money=3000):
    """A fresh pricing context. Every valuation goes through one of these."""
    return kagagent.Econ(market or {}, standing or {}, day, money)


def tasks_for(tiles, day=0, seeds=None, shed=None, units=1, e=None,
              animal=None, pen_budget=0, empty_pens=None, hungry=0.0,
              stocked=0):
    return kagagent.build_tasks(tiles, day, e or econ(day),
                                seeds if seeds is not None else {"MELON": 9},
                                shed or {}, units, hungry, stocked,
                                animal, pen_budget, empty_pens or {})


# --------------------------------------------------------------------------
# the price curve, which the agent reimplements in order to plan
# --------------------------------------------------------------------------

def test_price_matches_the_published_table():
    """The competition documents P(I0-T), P(I0+T) and P(I0+2T) per resource.
    If the reimplementation drifts from those, every plan built on it is wrong."""
    expected = {
        "WHEAT":      (45, 20, 19),
        "CARROT":     (70, 10, 1),
        "TOMATO":     (84, 24, 9),
        "STRAWBERRY": (204, 1, 1),
        "MELON":      (300, 1, 1),
        "EGG":        (70, 40, 39),
        "MILK":       (256, 1, 1),
        "WOOL":       (240, 1, 1),
        "FERTILIZER": (140, 60, 20),
    }
    for item, (below, above, above2) in expected.items():
        T = kagagent.MARKET[item][1]
        assert kagagent.price_at(item, I0 - T) == below, item
        assert kagagent.price_at(item, I0 + T) == above, item
        assert kagagent.price_at(item, I0 + 2 * T) == above2, item


def test_price_is_base_at_the_starting_inventory():
    for item, params in kagagent.MARKET.items():
        assert kagagent.price_at(item, I0) == params[0], item


def test_price_never_goes_below_the_floor():
    assert kagagent.price_at("MELON", I0 + 10_000) == 1


def test_price_falls_as_inventory_grows():
    prev = kagagent.price_at("MELON", I0)
    for extra in range(50, 400, 50):
        cur = kagagent.price_at("MELON", I0 + extra)
        assert cur <= prev
        prev = cur


# --------------------------------------------------------------------------
# order sizing off that curve
# --------------------------------------------------------------------------

def test_sell_quantity_stops_at_the_reservation_price():
    n = kagagent.sell_quantity("MELON", I0, have=500, reserve=100)
    assert 0 < n < 500
    assert kagagent.price_at("MELON", I0 + n - 1) >= 100
    assert kagagent.price_at("MELON", I0 + n) < 100


def test_sell_quantity_never_exceeds_what_is_held():
    assert kagagent.sell_quantity("WHEAT", I0, have=3, reserve=1) == 3


def test_sell_quantity_is_zero_when_the_market_is_already_below_reserve():
    assert kagagent.sell_quantity("MELON", I0 + 5000, have=50, reserve=100) == 0


# --------------------------------------------------------------------------
# the planner: do not plant what cannot finish
# --------------------------------------------------------------------------

def test_crop_that_cannot_reach_its_peak_is_worth_nothing():
    """A melon reaches its cap at age ten. Planted on day 20 it is eighty
    coins burnt, and the last four versions kept planting them to the bell."""
    assert kagagent.crop_value("MELON", 19, econ(19)) is not None
    assert kagagent.crop_value("MELON", 20, econ(20)) is None
    assert kagagent.crop_value("WHEAT", 25, econ(25)) is not None
    assert kagagent.crop_value("WHEAT", 26, econ(26)) is None


def test_planner_switches_to_a_fast_crop_late_in_the_season():
    assert kagagent.best_crop(0, econ(0))[0] == "MELON"
    assert kagagent.best_crop(22, econ(22))[0] in ("WHEAT", "CARROT")


def test_planner_gives_up_when_nothing_can_finish():
    assert kagagent.best_crop(29, econ(29))[0] is None


def test_agent_stops_buying_seed_it_cannot_grow():
    late = agent(obs(day=28, seeds={}))
    assert not [o for o in late["market"] if o[0] == "BUY_SEED"]


# --------------------------------------------------------------------------
# task pricing
# --------------------------------------------------------------------------

def test_a_plant_about_to_die_outranks_a_routine_watering():
    tiles = [[None] * 10 for _ in range(10)]
    tiles[0][0] = plant(watered=False, dry=1, units=4)   # one dry day already
    tiles[0][1] = plant(watered=False, dry=0, day=0)     # inside the window
    tiles[0][1] = plant(watered=False, dry=0, day=-6)    # inside the window
    tasks = tasks_for(tiles, 3, {"MELON": 5})
    at_risk = [t for t in tasks if (t[0], t[1]) == (0, 0) and t[2] == ["WATER"]]
    routine = [t for t in tasks if (t[0], t[1]) == (1, 0) and t[2] == ["WATER"]]
    assert at_risk and routine
    assert at_risk[0][3] > routine[0][3]


def test_watering_inside_the_bonus_window_beats_watering_outside_it():
    lo, hi = kagagent.bonus_window("MELON")
    tiles = [[None] * 10 for _ in range(10)]
    tiles[0][0] = plant(watered=False, day=0)
    inside = tasks_for(tiles, lo, {})
    outside = tasks_for(tiles, lo - 1, {})
    wi = [t[3] for t in inside if t[2] == ["WATER"]][0]
    # Outside the window a healthy plant survives a skipped day, so there is
    # nothing to price: the turn is worth more anywhere else on the board.
    assert not [t for t in outside if t[2] == ["WATER"]]
    assert wi > 0


def test_harvest_is_priced_on_what_is_actually_on_the_plant():
    tiles = [[None] * 10 for _ in range(10)]
    tiles[0][0] = plant(day=0, units=6)
    tiles[0][1] = plant(day=0, units=1)
    tasks = tasks_for(tiles, 10, {})
    big = [t[3] for t in tasks if (t[0], t[1]) == (0, 0) and t[2] == ["HARVEST"]][0]
    small = [t[3] for t in tasks if (t[0], t[1]) == (1, 0) and t[2] == ["HARVEST"]][0]
    assert big > small


def test_no_plant_task_without_seed():
    tasks = tasks_for([[None] * 10 for _ in range(10)], 0, {"MELON": 0})
    assert not [t for t in tasks if t[2][0] == "PLANT"]


def test_locked_tiles_are_never_given_work():
    tiles = [["LOCKED"] * 10 for _ in range(10)]
    assert tasks_for(tiles, 0) == []


# --------------------------------------------------------------------------
# assignment
# --------------------------------------------------------------------------

def test_each_unit_and_each_task_is_used_at_most_once():
    units = [(0, 0), (1, 1), (2, 2)]
    tasks = [(0, 0, ["WATER"], 10.0), (4, 4, ["WATER"], 12.0),
             (2, 2, ["HARVEST"], 30.0)]
    out = kagagent.assign(units, tasks)
    assert len(set(out.values())) == len(out)
    assert set(out) <= set(range(len(units)))


def test_the_walk_is_priced_in():
    """Same value, different distance: the near one wins."""
    units = [(0, 0)]
    tasks = [(9, 9, ["HARVEST"], 100.0), (0, 0, ["HARVEST"], 100.0)]
    assert kagagent.assign(units, tasks)[0] == 1


def test_a_rich_job_is_still_worth_a_walk():
    units = [(0, 0)]
    tasks = [(3, 0, ["HARVEST"], 500.0), (0, 0, ["WATER"], 3.0)]
    assert kagagent.assign(units, tasks)[0] == 0


def test_more_units_than_tasks_leaves_units_unassigned():
    out = kagagent.assign([(0, 0), (1, 1)], [(0, 0, ["WATER"], 5.0)])
    assert len(out) == 1


# --------------------------------------------------------------------------
# the action dict
# --------------------------------------------------------------------------

def test_action_shape():
    a = agent(obs(hands=[(1, 1), (2, 2)]))
    assert set(a) == {"farmer", "hands", "market"}
    assert isinstance(a["farmer"], list) and a["farmer"]
    assert len(a["hands"]) == 2


def test_every_op_is_a_known_verb():
    verbs = {"NORTH", "SOUTH", "EAST", "WEST", "PASS", "PLANT", "WATER",
             "HARVEST", "FERTILIZE", "DIG", "DROP", "PICKUP", "PLACE"}
    a = agent(obs(hands=[(1, 1), (2, 2)]))
    for op in [a["farmer"], *a["hands"]]:
        assert op[0] in verbs, op


def test_market_orders_stay_inside_the_per_turn_cap():
    """Only ten are processed a turn and the rest vanish silently; hour 0 with
    a full shed is when the queue is most likely to overflow."""
    a = agent(obs(hour=0, shed={k: 40 for k in kagagent.MARKET}))
    assert len(a["market"]) <= kagagent.MAX_ORDERS


def test_hires_at_the_start_of_the_day_and_not_after():
    assert [o for o in agent(obs(hour=0))["market"] if o[0] == "HIRE"]
    assert not [o for o in agent(obs(hour=9))["market"] if o[0] == "HIRE"]


def test_hiring_stops_at_the_cap_and_at_the_wage_bill():
    """A hand costs fib(n) for the day, so the bill accelerates. Sixteen hands
    scored two thirds of what ten did — the marginal hand finds only the cheap
    end of the board — and the budget is what holds the line."""
    rich = kagagent.hires_wanted(money=10 ** 6, jobs=200, already=0)
    assert rich == kagagent.MAX_HANDS
    assert kagagent.hires_wanted(money=20, jobs=200, already=0) < rich
    assert kagagent.hires_wanted(money=10 ** 6, jobs=3, already=0) == 3
    assert kagagent.hires_wanted(money=10 ** 6, jobs=200,
                                 already=kagagent.MAX_HANDS) == 0


def test_a_loaded_unit_banks_its_load():
    """SELL spends from the shed, so produce in a pack is not yet money."""
    full = [{"MELON": kagagent.DROP_AT}]
    walking = agent(obs(farmer=(0, 0), inventories=full))
    assert walking["farmer"][0] in {"SOUTH", "EAST"}
    assert agent(obs(farmer=(4, 4), inventories=full))["farmer"] == ["DROP"]


def test_everything_is_sold_on_the_last_day():
    """Unsold stock scores nothing, so the reservation price stops applying."""
    a = agent(obs(day=kagagent.LAST_DAY, shed={"MELON": 40},
                  inventory={"MELON": I0 + 4000}))
    sells = [o for o in a["market"] if o[0] == "SELL" and o[1] == "MELON"]
    assert sells and sells[0][2] == 40


def test_holds_stock_when_the_price_is_under_water_mid_season():
    a = agent(obs(day=5, shed={"MELON": 40}, inventory={"MELON": I0 + 4000}))
    assert not [o for o in a["market"] if o[0] == "SELL" and o[1] == "MELON"]


@pytest.mark.parametrize("start,target,expected", [
    ((0, 0), (0, 3), "SOUTH"), ((0, 3), (0, 0), "NORTH"),
    ((0, 0), (3, 0), "EAST"), ((3, 0), (0, 0), "WEST"),
    ((2, 2), (2, 2), "PASS"),
])
def test_step_toward(start, target, expected):
    assert kagagent.step_toward(*start, *target) == expected


def test_shape_functions_agree_with_the_engine():
    assert kagagent._shape("linear", 4, 10) == 4
    assert kagagent._shape("sq", 4, 10) == 16
    assert kagagent._shape("sqrt", 9, 10) == 3
    assert kagagent._shape("log", 0, 10) == 0
    assert kagagent._shape("hinge", 10, 10) == pytest.approx(1.0)
    assert kagagent._shape("hinge", 20, 10) == pytest.approx(2 + 8 * 1.0)
    assert kagagent._shape("sqrt", -5, 10) == 0        # clamped at zero
