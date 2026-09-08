"""Tests for the herd branch.

The arithmetic here decided that animals stay switched off on a 25-tile farm,
so most of what these pin down is that the comparison is being made on
comparable units and that the feed precondition is honoured — the two mistakes
that cost four earlier attempts.
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


def pen(kind="PASTURE", animal=None, fed=True, cared=True, units=0,
        fert=False, unfed_days=0):
    t = {"kind": kind}
    if animal:
        t.update({"animal": animal, "fed_today": fed, "cared_today": cared,
                  "yield_units": units, "fertilizer_available": fert,
                  "consecutive_unfed": unfed_days, "placed_day": 0})
    return t


# --------------------------------------------------------------------------
# valuation
# --------------------------------------------------------------------------

def test_an_animal_bought_too_late_to_produce_is_worth_nothing():
    """A cow first yields on day 8; bought on day 22 it never produces."""
    assert ka.animal_value("COW", 0, PRICES) is not None
    assert ka.animal_value("COW", ka.LAST_DAY - 7, PRICES) is None


def test_totals_are_compared_per_tile_day_not_raw():
    """The bug that cost 25,000 coins a game: a melon returns its coins over ten
    days and a cow over the rest of the season, so the raw totals say the cow is
    worth twice the melon while per tile-day the melon is well ahead."""
    melon_total = ka.crop_value("MELON", 0, 250)
    cow_total = ka.animal_value("COW", 0, PRICES)
    assert cow_total > melon_total                      # raw totals mislead

    melon_rate = ka.per_tile_day(melon_total, ka.CROPS["MELON"]["first"])
    cow_rate = ka.animal_rate("COW", 0, PRICES)
    assert melon_rate > cow_rate                        # per tile-day does not


def test_per_tile_day_never_divides_by_zero():
    assert ka.per_tile_day(100.0, 0) == 100.0


def test_melon_outranks_every_animal_at_full_price():
    """The reason the herd stays off: this is arithmetic, not a preference."""
    melon = ka.per_tile_day(ka.crop_value("MELON", 0, 250),
                            ka.CROPS["MELON"]["first"])
    for kind in ka.ANIMALS:
        assert ka.animal_rate(kind, 0, PRICES) < melon, kind


def test_a_collapsed_melon_price_flips_the_choice():
    """If our own supply floors melon, converting tiles becomes correct."""
    cheap = dict(PRICES, MELON=20)
    melon = ka.per_tile_day(ka.crop_value("MELON", 0, 20),
                            ka.CROPS["MELON"]["first"])
    assert ka.animal_rate("COW", 0, cheap) > melon


def test_no_animal_is_chosen_without_the_money_for_one():
    assert ka.choose_animal(0, PRICES, money=50) is None


# --------------------------------------------------------------------------
# pen tasks
# --------------------------------------------------------------------------

def build(tiles, day=10, animal="COW", shed=None):
    return ka.build_tasks(tiles, day, PRICES, {"MELON": 5}, "MELON",
                          animal, shed or {}, hungry_value=40.0)


def ops_at(tasks, x, y):
    return [t[2][0] for t in tasks if (t[0], t[1]) == (x, y)]


def test_a_hungry_animal_asks_to_be_fed_and_the_task_needs_wheat():
    tiles = [[None] * 10 for _ in range(10)]
    tiles[0][0] = pen(animal="COW", fed=False)
    feed = [t for t in build(tiles) if t[2] == ["FEED"]]
    assert feed
    assert feed[0][4] == "WHEAT", "feeding must require wheat in the pack"


def test_a_second_dry_day_doubles_what_feeding_is_worth():
    a = [[None] * 10 for _ in range(10)]
    a[0][0] = pen(animal="COW", fed=False, unfed_days=0)
    b = [[None] * 10 for _ in range(10)]
    b[0][0] = pen(animal="COW", fed=False, unfed_days=1)
    v1 = [t[3] for t in build(a) if t[2] == ["FEED"]][0]
    v2 = [t[3] for t in build(b) if t[2] == ["FEED"]][0]
    assert v2 > v1


def test_a_fed_animal_is_harvested_collected_and_cared_for():
    tiles = [[None] * 10 for _ in range(10)]
    tiles[0][0] = pen(animal="COW", fed=True, cared=False, units=3, fert=True)
    ops = ops_at(build(tiles), 0, 0)
    assert "FEED" not in ops
    assert set(ops) == {"HARVEST", "COLLECT_FERTILIZER", "CARE"}


def test_an_empty_pen_asks_for_an_animal_only_when_one_is_in_the_shed():
    tiles = [[None] * 10 for _ in range(10)]
    tiles[0][0] = pen()
    assert not [t for t in build(tiles) if t[2][0] == "PLACE"]

    place = [t for t in build(tiles, shed={"COW": 1}) if t[2][0] == "PLACE"]
    assert place and place[0][4] == "COW", "placing must require carrying one"


# --------------------------------------------------------------------------
# the precondition, which is what sank the earlier attempts
# --------------------------------------------------------------------------

def test_a_unit_without_wheat_is_never_given_a_feed_job():
    """FEED spends a wheat from the acting unit's own pack. Assigning it to an
    empty-handed unit wastes the turn and the animal starves anyway."""
    tasks = [(0, 0, ["FEED"], 500.0, "WHEAT")]
    empty = ka.assign([(0, 0)], tasks, [{}])
    assert empty == {}

    stocked = ka.assign([(0, 0)], tasks, [{"WHEAT": 3}])
    assert stocked == {0: 0}


def test_a_unit_without_an_animal_is_never_given_a_place_job():
    tasks = [(0, 0, ["PLACE", "COW"], 900.0, "COW")]
    assert ka.assign([(0, 0)], tasks, [{"WHEAT": 9}]) == {}
    assert ka.assign([(0, 0)], tasks, [{"COW": 1}]) == {0: 0}


def test_tasks_without_a_precondition_are_open_to_anyone():
    tasks = [(0, 0, ["WATER"], 10.0, None)]
    assert ka.assign([(0, 0)], tasks, [{}]) == {0: 0}


# --------------------------------------------------------------------------
# wheat is feed only while there is a herd
# --------------------------------------------------------------------------

def _obs(tiles, inventories, shed=None, day=24):
    return {
        "player": 0, "day": day, "hour": 9, "step": day * 24 + 9,
        "farms": [{"money": 3000, "tiles": tiles, "farmer": [0, 0], "hands": [],
                   "unlocked_quadrants": ["NW"], "hires_today": 0}],
        "private": {"shed": shed or {}, "seeds": {"WHEAT": 5},
                    "inventories": inventories},
        "market": {"inventory": {}, "prices": PRICES},
        "town": {"unlocked_shops": []},
    }


def test_late_season_wheat_is_banked_when_there_is_no_herd():
    """Wheat is the late-season crop once melon can no longer finish. Treating
    it as feed regardless left it in packs, never banked and never sold."""
    tiles = [[None if x < 5 and y < 5 else "LOCKED" for x in range(10)]
             for y in range(10)]
    a = ka.agent(_obs(tiles, [{"WHEAT": ka.DROP_AT + 4}]))
    assert a["farmer"][0] in {"SOUTH", "EAST", "DROP"}


def test_wheat_is_held_as_feed_when_a_herd_exists():
    tiles = [[None if x < 5 and y < 5 else "LOCKED" for x in range(10)]
             for y in range(10)]
    tiles[0][0] = pen(animal="COW", fed=False)
    a = ka.agent(_obs(tiles, [{"WHEAT": ka.DROP_AT + 4}]))
    assert a["farmer"] != ["DROP"]
