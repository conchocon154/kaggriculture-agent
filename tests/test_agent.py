"""Tests for the agent's decisions.

The game is slow to simulate, so these drive the agent with hand-built
observations. What is worth pinning down is the shape of the action dict (a
malformed one is a silent no-op for a whole turn, which is expensive and
invisible) and the handful of rules the ablation showed actually matter.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("kagagent", ROOT / "main.py")
kagagent = importlib.util.module_from_spec(spec)
sys.modules["kagagent"] = kagagent
spec.loader.exec_module(kagagent)

agent = kagagent.agent


def obs(tiles=None, farmer=(0, 0), hands=(), money=3000, day=0, hour=5,
        seeds=None, shed=None, inventories=None):
    size = 10
    if tiles is None:
        tiles = [[None if x < 5 and y < 5 else "LOCKED"
                  for x in range(size)] for y in range(size)]
    return {
        "player": 0,
        "day": day,
        "hour": hour,
        "farms": [{"money": money, "tiles": tiles, "farmer": list(farmer),
                   "hands": [list(h) for h in hands],
                   "unlocked_quadrants": ["NW"], "hires_today": 0}],
        "private": {
            "shed": shed or {},
            "seeds": seeds if seeds is not None else {kagagent.CROP: 5},
            "inventories": inventories or [{} for _ in range(1 + len(hands))],
        },
        "market": {"inventory": {}, "prices": {}},
        "town": {"unlocked_shops": []},
    }


def plant_tile(day=0, watered=False, yield_units=0, crop=None):
    return {"kind": "PLANT", "crop": crop or kagagent.CROP, "planted_day": day,
            "watered_today": watered, "consecutive_unwatered": 0,
            "yield_units": yield_units, "fertilized_until_day": -1}


# --------------------------------------------------------------------------
# shape — a malformed action costs a whole turn, silently
# --------------------------------------------------------------------------

def test_action_has_the_three_required_keys():
    a = agent(obs())
    assert set(a) == {"farmer", "hands", "market"}
    assert isinstance(a["farmer"], list) and a["farmer"]
    assert isinstance(a["hands"], list)
    assert isinstance(a["market"], list)


def test_one_op_per_hired_hand_in_order():
    a = agent(obs(hands=[(1, 1), (2, 2), (3, 3)]))
    assert len(a["hands"]) == 3
    assert all(isinstance(op, list) and op for op in a["hands"])


def test_every_op_is_a_known_verb():
    verbs = {"NORTH", "SOUTH", "EAST", "WEST", "PASS", "PLANT", "WATER",
             "HARVEST", "FERTILIZE", "DIG", "DROP", "PICKUP", "PLACE",
             "BUILD_COOP", "BUILD_PASTURE", "FEED", "CARE", "COLLECT_FERTILIZER"}
    a = agent(obs(hands=[(1, 1), (2, 2)]))
    for op in [a["farmer"], *a["hands"]]:
        assert op[0] in verbs, op


# --------------------------------------------------------------------------
# the rules the ablation showed matter
# --------------------------------------------------------------------------

def test_hires_at_the_start_of_the_day_and_not_after():
    morning = [o for o in agent(obs(hour=0))["market"] if o[0] == "HIRE"]
    assert len(morning) == kagagent.HANDS_PER_DAY

    later = [o for o in agent(obs(hour=7))["market"] if o[0] == "HIRE"]
    assert later == [], "hiring again mid-day wastes market orders"


def test_market_orders_stay_inside_the_per_turn_cap():
    """Only 10 orders are processed per turn; the rest are dropped in silence.
    Hiring at hour 0 is the moment the queue is most likely to overflow."""
    a = agent(obs(hour=0, shed={"MELON": 40, "WHEAT": 10, "CARROT": 10}))
    assert len(a["market"]) <= 10, a["market"]


def test_sells_in_batches_rather_than_dumping_the_shed():
    a = agent(obs(shed={kagagent.CROP: 50}))
    sells = [o for o in a["market"] if o[0] == "SELL"]
    assert sells and sells[0][2] == kagagent.SELL_BATCH


def test_does_not_sell_fertilizer():
    """Not because it cannot: the docs say fertiliser is buy-only and the
    engine's generic SELL path accepts it anyway (confirmed by Kaggle staff in
    the competition's discrepancies thread). This agent keeps no animals, so it
    never holds any — the skip is here to keep an empty SELL out of the
    ten-order-per-turn queue, and it would have to come out the day a herd
    lands."""
    a = agent(obs(shed={"FERTILIZER": 20}))
    assert not [o for o in a["market"] if o[0] == "SELL"]


def test_buys_seed_when_short_and_not_when_stocked():
    short = agent(obs(seeds={kagagent.CROP: 0}))
    assert any(o[0] == "BUY_SEED" for o in short["market"])

    stocked = agent(obs(seeds={kagagent.CROP: 99}))
    assert not any(o[0] == "BUY_SEED" for o in stocked["market"])


def test_does_not_spend_its_last_coins_on_seed():
    a = agent(obs(money=30, seeds={kagagent.CROP: 0}))
    assert not any(o[0] == "BUY_SEED" for o in a["market"])


# --------------------------------------------------------------------------
# tile decisions
# --------------------------------------------------------------------------

def test_plants_on_an_empty_unlocked_tile():
    assert agent(obs())["farmer"] == ["PLANT", kagagent.CROP]


def test_waters_an_unwatered_plant_before_anything_else():
    tiles = [[None] * 10 for _ in range(10)]
    tiles[0][0] = plant_tile(watered=False)
    assert agent(obs(tiles=tiles))["farmer"] == ["WATER"]


def test_harvests_once_the_crop_is_ready():
    ready = kagagent._first_yield_day(kagagent.CROP)
    tiles = [[None] * 10 for _ in range(10)]
    tiles[0][0] = plant_tile(day=0, watered=True, yield_units=4)
    assert agent(obs(tiles=tiles, day=ready))["farmer"] == ["HARVEST"]


def test_does_not_harvest_before_the_first_yield_day():
    tiles = [[None] * 10 for _ in range(10)]
    tiles[0][0] = plant_tile(day=0, watered=True, yield_units=4)
    assert agent(obs(tiles=tiles, day=1))["farmer"] != ["HARVEST"]


def test_digs_a_weed():
    tiles = [[None] * 10 for _ in range(10)]
    tiles[0][0] = {"kind": "WEED"}
    assert agent(obs(tiles=tiles))["farmer"] == ["DIG"]


def test_a_full_unit_heads_for_the_shed_and_drops_there():
    tiles = [[None] * 10 for _ in range(10)]
    full = [{kagagent.CROP: 9}]

    walking = agent(obs(tiles=tiles, farmer=(0, 0), inventories=full))
    assert walking["farmer"][0] in {"SOUTH", "EAST"}, walking["farmer"]

    at_shed = agent(obs(tiles=tiles, farmer=(4, 4), inventories=full))
    assert at_shed["farmer"] == ["DROP"]


def test_never_acts_on_a_locked_tile():
    """Tile actions no-op on locked ground, so spending a turn there is waste."""
    tiles = [[("LOCKED" if (x >= 5 or y >= 5) else None)
              for x in range(10)] for y in range(10)]
    a = agent(obs(tiles=tiles, farmer=(7, 7)))
    assert a["farmer"][0] in kagagent.MOVES or a["farmer"] == ["PASS"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

@pytest.mark.parametrize("start,target,expected", [
    ((0, 0), (0, 3), "SOUTH"),
    ((0, 3), (0, 0), "NORTH"),
    ((0, 0), (3, 0), "EAST"),
    ((3, 0), (0, 0), "WEST"),
    ((2, 2), (2, 2), "PASS"),
])
def test_step_toward(start, target, expected):
    assert kagagent._step_toward(*start, *target) == expected


def test_two_units_do_not_walk_to_the_same_tile():
    """Without claiming, every idle unit converges on the same nearest job."""
    tiles = [[plant_tile(watered=True, yield_units=0) for _ in range(10)]
             for _ in range(10)]
    tiles[0][4] = None
    tiles[4][0] = None
    a = agent(obs(tiles=tiles, farmer=(2, 2), hands=[(2, 2)],
                  seeds={kagagent.CROP: 0}))
    assert a["farmer"] != a["hands"][0] or a["farmer"] == ["PASS"]
