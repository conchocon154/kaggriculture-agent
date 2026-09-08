"""Tests for the flock, the market model behind it, and the money that runs it.

Everything here pins down a mistake that was measured, not a rule that was
guessed. Four of them cost between ten and twenty thousand coins a game, and
every one of them looked correct in the source.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("kagagent_animals", ROOT / "main.py")
ka = importlib.util.module_from_spec(spec)
sys.modules["kagagent_animals"] = ka
spec.loader.exec_module(ka)

PRICES = {"MELON": 250, "WHEAT": 25, "CARROT": 35,
          "MILK": 160, "EGG": 50, "WOOL": 200, "FERTILIZER": 100}


def econ(day=0, market=None, standing=None, money=100000):
    return ka.Econ(market or {}, standing or {}, day, money)


def pen(kind="COOP", animal=None, fed=True, cared=True, units=0,
        fert=False, unfed_days=0, placed=0):
    t = {"kind": kind}
    if animal:
        t.update({"animal": animal, "fed_today": fed, "cared_today": cared,
                  "yield_units": units, "fertilizer_available": fert,
                  "consecutive_unfed": unfed_days, "placed_day": placed})
    return t


def board(**kw):
    tiles = [[None] * 10 for _ in range(10)]
    return tiles


def tasks_for(tiles, day=10, shed=None, units=4, animal=None, pen_budget=0,
              empty_pens=None, hungry=0.0, stocked=0, e=None, seeds=None):
    return ka.build_tasks(tiles, day, e or econ(day),
                          seeds if seeds is not None else {"MELON": 5},
                          shed or {}, units, hungry, stocked, animal,
                          pen_budget, empty_pens or {})


def obs(tiles=None, money=3000, day=10, hour=5, shed=None, seeds=None,
        inventories=None, hands=(), market_inv=None):
    if tiles is None:
        tiles = [[None if x < 5 and y < 5 else "LOCKED" for x in range(10)]
                 for y in range(10)]
    return {
        "player": 0, "day": day, "hour": hour, "step": day * 24 + hour,
        "farms": [{"money": money, "tiles": tiles, "farmer": [4, 4],
                   "hands": [list(h) for h in hands],
                   "unlocked_quadrants": ["NW"], "hires_today": 0}],
        "private": {"shed": shed or {}, "seeds": seeds or {"WHEAT": 5},
                    "inventories": inventories or [{}
                                                   for _ in range(1 + len(hands))]},
        "market": {"inventory": market_inv or {}, "prices": dict(PRICES)},
        "town": {"unlocked_shops": []},
    }


# --------------------------------------------------------------------------
# the margin: what the market will actually pay
# --------------------------------------------------------------------------

def test_the_price_of_the_next_unit_falls_as_our_own_supply_grows():
    """Pricing a crop at a flat share of base says every empty tile wants the
    same crop, so the farm monocrops and drowns its own market."""
    fresh = econ()
    loaded = econ(standing={"MELON": 120})
    assert loaded.price("MELON") < fresh.price("MELON")


def test_melon_is_worth_about_twenty_six_thousand_for_the_whole_season():
    """The number the strategy turns on. Past roughly a hundred and fifty
    units the curve is flat at the floor, so a second field of melon is a
    field of one-dollar melons."""
    e = econ()
    assert 20000 < e.batch("MELON", 100) < 30000
    assert e.batch("MELON", 400) - e.batch("MELON", 150) < 1000


def test_eggs_and_fertiliser_never_crash_the_way_melon_does():
    """Which is the whole reason the flock exists."""
    e = econ()
    assert e.batch("EGG", 400) > 2 * e.batch("EGG", 100)
    assert ka.price_at("EGG", ka.I0 + 400) > 30
    assert ka.price_at("MELON", ka.I0 + 400) == 1


def test_supply_is_priced_as_if_the_opponent_matches_us():
    """We cannot see their shed and on this ladder they are growing melon too.
    Assuming we are the only seller is how an agent plants a whole farm of it."""
    assert ka.RIVAL_SUPPLY > 0
    solo = ka.price_at("MELON", ka.I0 + 60)
    assert econ(standing={"MELON": 60}).price("MELON") < solo


# --------------------------------------------------------------------------
# coins per action, which is the only currency the matcher can spend
# --------------------------------------------------------------------------

def test_a_planting_and_a_pen_are_compared_per_action():
    """Comparing a pen's whole-season total against a single watering is how
    one version covered the board in pens worth thousands apiece and let every
    crop on it die of thirst. Both sides have to be a turn's worth."""
    e = econ(0)
    assert ka.animal_value("GOOSE", 0, e) > ka.crop_value("MELON", 0, e)
    assert ka.crop_rate("MELON", 0, e) > ka.animal_rate("GOOSE", 0, e)


def test_melon_outranks_every_animal_while_melon_is_still_deep():
    e = econ(0)
    melon = ka.crop_rate("MELON", 0, e)
    for kind in ka.ANIMALS:
        assert ka.animal_rate(kind, 0, e) < melon, kind


def test_a_flooded_melon_market_flips_the_choice():
    """Once our own supply has taken melon to the floor, tiles are better
    spent on the curves that do not crash."""
    flooded = econ(0, standing={"MELON": 200})
    assert ka.animal_rate("GOOSE", 0, flooded) > ka.crop_rate("MELON", 0, flooded)


def test_an_animal_bought_too_late_to_produce_is_worth_nothing():
    assert ka.animal_value("COW", 0, econ(0)) is not None
    assert ka.animal_value("COW", ka.LAST_DAY - 7, econ()) is None


def test_care_is_most_of_why_a_goose_beats_a_cow_per_action():
    """CARE banks a unit per fed-and-cared day and pays out in full at the next
    production, so a daily layer that is cared for daily yields two a day."""
    e = econ(0)
    assert ka.animal_rate("GOOSE", 0, e) > 0
    tiles = board()
    tiles[0][0] = pen(animal="GOOSE", fed=True, cared=False)
    assert [t for t in tasks_for(tiles) if t[2] == ["CARE"]]


def test_no_animal_is_chosen_without_the_money_for_one():
    assert ka.best_animal(0, econ(0), money=50)[0] is None


# --------------------------------------------------------------------------
# standing supply: what the farm already owes the market
# --------------------------------------------------------------------------

def test_a_placed_animal_is_a_standing_order_for_the_rest_of_the_season():
    """Counting only the units on its tile let the planner buy a fourth cow
    after the milk price had already been sold to the floor."""
    tiles = board()
    tiles[0][0] = pen("PASTURE", animal="COW", placed=5)
    supply = ka.standing_supply(tiles, {}, [], 10)
    assert supply["MILK"] > 4
    assert supply["FERTILIZER"] > 0


def test_an_animal_waiting_in_the_shed_counts_too():
    """Leaving it out made every purchase look like the first one: one game
    bought fifteen sheep against a wool price that floors after thirty units,
    and never housed any of them."""
    supply = ka.standing_supply(board(), {"SHEEP": 3}, [], 10)
    assert supply.get("WOOL", 0) > 0


def test_a_growing_crop_is_a_glut_before_it_is_a_harvest():
    tiles = board()
    tiles[0][0] = {"kind": "PLANT", "crop": "MELON", "planted_day": 0,
                   "watered_today": True, "consecutive_unwatered": 0,
                   "yield_units": 0, "fertilized_until_day": -1}
    assert ka.standing_supply(tiles, {}, [], 3)["MELON"] == 6


# --------------------------------------------------------------------------
# pen tasks
# --------------------------------------------------------------------------

def ops_at(tasks, x, y):
    return [t[2][0] for t in tasks if (t[0], t[1]) == (x, y)]


def test_a_hungry_animal_asks_to_be_fed_and_the_task_needs_wheat():
    tiles = board()
    tiles[0][0] = pen(animal="GOOSE", fed=False)
    feed = [t for t in tasks_for(tiles) if t[2] == ["FEED"]]
    assert feed
    assert feed[0][4] == "WHEAT", "feeding must require wheat in the pack"


def test_a_second_dry_day_buys_the_bird_rather_than_the_day():
    a, b = board(), board()
    a[0][0] = pen(animal="GOOSE", fed=False, unfed_days=0)
    b[0][0] = pen(animal="GOOSE", fed=False, unfed_days=1)
    v1 = [t[3] for t in tasks_for(a) if t[2] == ["FEED"]][0]
    v2 = [t[3] for t in tasks_for(b) if t[2] == ["FEED"]][0]
    assert v2 > v1 * 3


def test_a_fed_animal_is_harvested_collected_and_cared_for():
    tiles = board()
    tiles[0][0] = pen(animal="GOOSE", fed=True, cared=False, units=3, fert=True)
    ops = ops_at(tasks_for(tiles), 0, 0)
    assert "FEED" not in ops
    assert set(ops) == {"HARVEST", "COLLECT_FERTILIZER", "CARE"}


def test_a_full_pen_is_harvested_first_because_it_has_stopped_producing():
    slack, full = board(), board()
    slack[0][0] = pen(animal="GOOSE", units=1)
    full[0][0] = pen(animal="GOOSE", units=ka.ANIMALS["GOOSE"]["held"])
    v_slack = [t[3] for t in tasks_for(slack) if t[2] == ["HARVEST"]][0]
    v_full = [t[3] for t in tasks_for(full) if t[2] == ["HARVEST"]][0]
    assert v_full > v_slack * ka.ANIMALS["GOOSE"]["held"]


def test_an_empty_pen_asks_for_an_animal_only_when_one_is_in_the_shed():
    tiles = board()
    tiles[0][0] = pen("COOP")
    assert not [t for t in tasks_for(tiles) if t[2][0] == "PLACE"]

    place = [t for t in tasks_for(tiles, shed={"GOOSE": 1}) if t[2][0] == "PLACE"]
    assert place and place[0][4] == "GOOSE", "placing must require carrying one"


def test_a_pen_is_only_offered_to_the_animal_it_fits():
    """A goose needs a coop and a cow a pasture. Counting empty pens together
    bought ten cows against six empty coops — five thousand seven hundred
    coins of livestock that sat in the shed until the season ended."""
    tiles = board()
    tiles[0][0] = pen("COOP")
    assert not [t for t in tasks_for(tiles, shed={"COW": 2}) if t[2][0] == "PLACE"]


def test_pens_for_stranded_livestock_stop_at_what_the_empty_ones_cover():
    """Otherwise the farm lays down a fresh pen for the same bird on every one
    of the day's twenty-four turns."""
    tiles = board()
    covered = tasks_for(tiles, shed={"GOOSE": 2}, empty_pens={"COOP": 2})
    assert not [t for t in covered if t[2][0].startswith("BUILD")]
    short = tasks_for(tiles, shed={"GOOSE": 2}, empty_pens={"COOP": 0})
    assert len([t for t in short if t[2] == ["BUILD_COOP"]]) == 2


# --------------------------------------------------------------------------
# the precondition, which is what sank four earlier attempts
# --------------------------------------------------------------------------

def test_a_unit_without_wheat_is_never_given_a_feed_job():
    """FEED spends a wheat from the acting unit's own pack. Assigning it to an
    empty-handed unit wastes the turn and the animal starves anyway."""
    tasks = [(0, 0, ["FEED"], 500.0, "WHEAT")]
    assert ka.assign([(0, 0)], tasks, [{}]) == {}
    assert ka.assign([(0, 0)], tasks, [{"WHEAT": 3}]) == {0: 0}


def test_a_unit_without_an_animal_is_never_given_a_place_job():
    tasks = [(0, 0, ["PLACE", "GOOSE"], 900.0, "GOOSE")]
    assert ka.assign([(0, 0)], tasks, [{"WHEAT": 9}]) == {}
    assert ka.assign([(0, 0)], tasks, [{"GOOSE": 1}]) == {0: 0}


def test_tasks_without_a_precondition_are_open_to_anyone():
    assert ka.assign([(0, 0)], [(0, 0, ["WATER"], 10.0, None)], [{}]) == {0: 0}


# --------------------------------------------------------------------------
# the money that runs the flock
# --------------------------------------------------------------------------

def _orders(action, op):
    return [o for o in action["market"] if o[0] == op]


def test_feed_is_sized_off_the_packs_as_well_as_the_shed():
    """Sizing it off the shed alone re-bought the whole day's feed on all
    twenty-four turns, because the units had just carried it out of the shed.
    That drained the bank to zero by day thirteen of every game."""
    tiles = [[None if x < 5 and y < 5 else "LOCKED" for x in range(10)]
             for y in range(10)]
    tiles[0][0] = pen(animal="GOOSE", fed=False)
    empty = obs(tiles=tiles, hands=[(4, 4)], inventories=[{}, {}])
    carried = obs(tiles=tiles, hands=[(4, 4)],
                  inventories=[{"WHEAT": 40}, {"WHEAT": 40}])
    assert _orders(ka.agent(empty), "BUY_PRODUCT")
    assert not _orders(ka.agent(carried), "BUY_PRODUCT")


def test_feed_is_bought_before_livestock():
    """Ordering this the other way starved six geese out of nine in a game the
    agent was otherwise leading: it kept buying animals it could not feed."""
    tiles = [[None if x < 5 and y < 5 else "LOCKED" for x in range(10)]
             for y in range(10)]
    tiles[0][0] = pen(animal="GOOSE", fed=False)
    tiles[0][1] = pen("COOP")
    ops = [o[0] for o in ka.agent(obs(tiles=tiles, money=5000))["market"]]
    assert "BUY_PRODUCT" in ops
    if "BUY_ANIMAL" in ops:
        assert ops.index("BUY_PRODUCT") < ops.index("BUY_ANIMAL")


def test_no_livestock_while_animals_already_on_the_board_go_unfed():
    tiles = [[None if x < 5 and y < 5 else "LOCKED" for x in range(10)]
             for y in range(10)]
    tiles[0][0] = pen(animal="GOOSE", fed=False)
    tiles[0][1] = pen("COOP")
    assert not _orders(ka.agent(obs(tiles=tiles, money=50000)), "BUY_ANIMAL")


def test_land_waits_until_the_tiles_already_owned_are_working():
    """Buying a quadrant on day zero spends the melon budget on dirt."""
    idle = obs(day=0, money=50000)
    assert not _orders(ka.agent(idle), "BUY_LAND")

    tiles = [[pen("COOP", animal="GOOSE") if x < 5 and y < 5 else "LOCKED"
              for x in range(10)] for y in range(10)]
    assert _orders(ka.agent(obs(tiles=tiles, day=0, money=50000)), "BUY_LAND")


def test_the_last_quadrant_is_not_bought_twice():
    tiles = [[None] * 10 for _ in range(10)]
    for y in range(10):
        for x in range(10):
            tiles[y][x] = pen("COOP", animal="GOOSE")
    o = obs(tiles=tiles, money=50000)
    o["farms"][0]["unlocked_quadrants"] = ["NW", "NE", "SW", "SE"]
    assert not _orders(ka.agent(o), "BUY_LAND")
