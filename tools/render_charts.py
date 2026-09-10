#!/usr/bin/env python3
"""Draw the farm, and the two curves that decided how it is farmed.

Runs one real game against the built-in starter, records the board and the bank
at every day, and renders from that — so the farm in the picture is a farm the
committed agent actually built, not an illustration of one.

    python3 tools/render_charts.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches      # noqa: E402
import matplotlib.pyplot as plt            # noqa: E402
import numpy as np                         # noqa: E402

from kaggle_environments import make       # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "reports" / "tables"
FIGURES = ROOT / "reports" / "figures"

SEED = 1003
BOARD_DAYS = (4, 12, 26)

THEMES = {
    "light": dict(bg="#ffffff", ink="#1a1d21", dim="#5b6470", grid="#e4e7eb",
                  mute="#9aa3ad", locked="#f1f3f5", empty="#fafbfc"),
    "dark":  dict(bg="#0d1117", ink="#e6edf3", dim="#9aa5b1", grid="#21262d",
                  mute="#6e7781", locked="#161b22", empty="#12171d"),
}

# One colour per thing that can be on a tile. Melon is the loud one because
# melon is what the first ten days are entirely about.
TILE = {
    "MELON":      "#e0632a",
    "WHEAT":      "#d9a441",
    "CARROT":     "#e08a3c",
    "TOMATO":     "#c8443c",
    "STRAWBERRY": "#d64f6d",
    "COOP":       "#3d8f7a",
    "PASTURE":    "#2f7d92",
    "WEED":       "#7a8a5c",
}


def load_agent(path: str):
    spec = importlib.util.spec_from_file_location("kag_" + Path(path).stem,
                                                  ROOT / path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# one real game
# --------------------------------------------------------------------------

def play():
    agent = load_agent("main.py")
    env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": SEED})
    env.run([agent.agent, "starter"])

    boards, bank = {}, []
    for step in env.steps:
        obs = step[0]["observation"]
        farm = obs["farms"][0]
        if obs["hour"] == 23:
            bank.append({"day": obs["day"],
                         "mine": float(farm["money"]),
                         "theirs": float(obs["farms"][1]["money"])})
            if obs["day"] in BOARD_DAYS:
                boards[obs["day"]] = {
                    "tiles": [row[:] for row in farm["tiles"]],
                    "money": float(farm["money"]),
                    "units": [tuple(farm["farmer"])] +
                             [tuple(h) for h in farm.get("hands", [])],
                }
    final = env.steps[-1]
    return boards, bank, (final[0]["reward"], final[1]["reward"]), agent


def marginal_revenue(agent, items, n=420):
    """What the n-th unit of each good fetches, off the engine's own curve."""
    out = {}
    for item in items:
        total, series = 0.0, []
        for i in range(n):
            total += agent.price_at(item, agent.I0 + i)
            series.append(total)
        out[item] = series
    return out


# --------------------------------------------------------------------------
# figures
# --------------------------------------------------------------------------

def classify(tile):
    if tile == "LOCKED":
        return "locked", None
    if tile is None:
        return "empty", None
    kind = tile.get("kind")
    if kind == "PLANT":
        return "crop", tile.get("crop")
    if kind == "WEED":
        return "weed", None
    if kind in ("COOP", "PASTURE"):
        return ("stocked" if tile.get("animal") else "pen"), kind
    return "empty", None


def fig_board(boards, theme, c):
    fig, axes = plt.subplots(1, len(BOARD_DAYS),
                             figsize=(3.35 * len(BOARD_DAYS), 3.9))
    fig.patch.set_facecolor(c["bg"])
    for ax, day in zip(axes, BOARD_DAYS):
        b = boards[day]
        ax.set_facecolor(c["bg"])
        counts = {}
        for y, row in enumerate(b["tiles"]):
            for x, tile in enumerate(row):
                state, what = classify(tile)
                if state == "locked":
                    face, edge, alpha = c["locked"], c["grid"], 1.0
                elif state == "empty":
                    face, edge, alpha = c["empty"], c["grid"], 1.0
                elif state == "weed":
                    face, edge, alpha = TILE["WEED"], c["grid"], 0.45
                elif state == "crop":
                    face, edge, alpha = TILE.get(what, c["mute"]), c["bg"], 0.92
                elif state == "pen":
                    face, edge, alpha = TILE[what], c["bg"], 0.30
                else:
                    face, edge, alpha = TILE[what], c["bg"], 0.95
                if state in ("crop", "pen", "stocked"):
                    counts[what] = counts.get(what, 0) + 1
                ax.add_patch(mpatches.Rectangle(
                    (x, 9 - y), 1, 1, facecolor=face, edgecolor=edge,
                    linewidth=0.8, alpha=alpha))

        # The shed sits between the four centre tiles; every sale passes it.
        ax.add_patch(mpatches.Rectangle((4.62, 4.62), 0.76, 0.76,
                                        facecolor=c["ink"], edgecolor="none"))
        for ux, uy in b["units"]:
            ax.add_patch(mpatches.Circle((ux + 0.5, 9 - uy + 0.5), 0.20,
                                         facecolor=c["bg"], edgecolor=c["ink"],
                                         linewidth=1.4, zorder=4))
        # Quadrant seams: the farm is four 5x5 fields, three of them bought.
        for v in (5,):
            ax.axhline(v, color=c["dim"], linewidth=1.1, alpha=0.5)
            ax.axvline(v, color=c["dim"], linewidth=1.1, alpha=0.5)

        head = ", ".join(f"{n}×{k.lower()}" for k, n in
                         sorted(counts.items(), key=lambda kv: -kv[1])[:3])
        ax.set_title(f"day {day}   ${b['money']:,.0f}\n{head or 'empty'}",
                     color=c["ink"], fontsize=9.5, loc="left", pad=8)
        ax.set_xlim(0, 10); ax.set_ylim(0, 10)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_aspect("equal")
        for sp in ax.spines.values():
            sp.set_color(c["grid"])

    # Pale is an empty pen and solid is a stocked one, which matters: the
    # difference between them is the agent's most expensive remaining habit.
    handles = [mpatches.Patch(facecolor=TILE[k], label=lab, alpha=a)
               for k, lab, a in (("MELON", "melon", 0.92),
                                 ("CARROT", "carrot", 0.92),
                                 ("WHEAT", "wheat", 0.92),
                                 ("WEED", "weed", 0.45),
                                 ("PASTURE", "pen, empty", 0.30),
                                 ("PASTURE", "pen, stocked", 0.95))]
    handles.append(mpatches.Patch(facecolor=c["ink"], label="shed"))
    leg = fig.legend(handles=handles, frameon=False, ncol=7, fontsize=8.5,
                     loc="lower center", bbox_to_anchor=(0.5, -0.02))
    for t in leg.get_texts():
        t.set_color(c["dim"])
    fig.tight_layout()
    save(fig, "farm-board", theme, c)


def fig_bank(bank, theme, c, result):
    days = [b["day"] for b in bank]
    mine = [b["mine"] for b in bank]
    theirs = [b["theirs"] for b in bank]

    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    fig.patch.set_facecolor(c["bg"]); ax.set_facecolor(c["bg"])
    ax.plot(days, mine, color=TILE["COOP"], linewidth=2.4, label="this agent")
    ax.plot(days, theirs, color=c["mute"], linewidth=1.8, label="built-in starter")

    # The melon crop lands on day ten and pays for everything after it.
    peak = max(range(1, len(mine)), key=lambda i: mine[i] - mine[i - 1])
    ax.annotate(f"melon harvest, +${mine[peak] - mine[peak - 1]:,.0f} in a day",
                xy=(days[peak], mine[peak]),
                xytext=(days[peak] - 8.5, mine[peak] + max(mine) * 0.30),
                color=TILE["MELON"], fontsize=8.5,
                arrowprops=dict(arrowstyle="-", color=TILE["MELON"], lw=1.1))

    style(ax, c, f"Bank over the season — final {result[0]:,.0f} to {result[1]:,.0f}",
          xlabel="day", ylabel="coins")
    leg = ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    for t in leg.get_texts():
        t.set_color(c["dim"])
    save(fig, "bank-over-season", theme, c)


def fig_depth(curves, theme, c):
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    fig.patch.set_facecolor(c["bg"]); ax.set_facecolor(c["bg"])
    palette = {"MELON": TILE["MELON"], "EGG": TILE["COOP"],
               "FERTILIZER": TILE["PASTURE"], "WHEAT": TILE["WHEAT"],
               "WOOL": c["mute"]}
    for item, series in curves.items():
        ax.plot(range(1, len(series) + 1), series, linewidth=2.2,
                color=palette[item], label=item.lower())

    # Labels at the right-hand end, nudged apart. Wheat and wool finish within
    # a few hundred coins of each other and land on top of one another
    # otherwise, which hides the very comparison the chart is making.
    ends = sorted(((series[-1], item) for item, series in curves.items()),
                  reverse=True)
    span = max(v for v, _ in ends)
    gap, placed = span * 0.055, []
    for value, item in ends:
        y = value
        if placed and placed[-1] - y < gap:
            y = placed[-1] - gap
        placed.append(y)
        ax.annotate(item.lower(), xy=(len(curves[item]), y),
                    xytext=(7, 0), textcoords="offset points",
                    color=palette[item], fontsize=8.5, va="center")

    style(ax, c, "What a whole season of each good is worth, cumulatively",
          xlabel="units sold into the market", ylabel="coins")
    ax.set_xlim(0, len(next(iter(curves.values()))) * 1.16)
    save(fig, "market-depth", theme, c)


def style(ax, c, title, xlabel="", ylabel=""):
    ax.set_title(title, color=c["ink"], fontsize=11, loc="left", pad=10)
    ax.set_xlabel(xlabel, color=c["dim"], fontsize=9)
    ax.set_ylabel(ylabel, color=c["dim"], fontsize=9)
    ax.tick_params(colors=c["dim"], labelsize=8.5)
    for side, sp in ax.spines.items():
        sp.set_visible(side in ("left", "bottom"))
        sp.set_color(c["grid"])
    ax.grid(True, color=c["grid"], linewidth=0.7, alpha=0.9)
    ax.set_axisbelow(True)


def save(fig, name, theme, c):
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / f"{name}-{theme}.png", dpi=170, facecolor=c["bg"],
                bbox_inches="tight", pad_inches=0.24)
    plt.close(fig)


# --------------------------------------------------------------------------

def main() -> int:
    boards, bank, result, agent = play()
    curves = marginal_revenue(
        agent, ["MELON", "EGG", "FERTILIZER", "WHEAT", "WOOL"])

    TABLES.mkdir(parents=True, exist_ok=True)
    with (TABLES / "bank_over_season.csv").open("w") as fh:
        fh.write("day,mine,theirs\n")
        for b in bank:
            fh.write(f"{b['day']},{b['mine']:.0f},{b['theirs']:.0f}\n")
    with (TABLES / "market_depth.csv").open("w") as fh:
        items = list(curves)
        fh.write("units," + ",".join(i.lower() for i in items) + "\n")
        for i in range(len(curves[items[0]])):
            fh.write(f"{i + 1}," + ",".join(f"{curves[k][i]:.0f}"
                                            for k in items) + "\n")

    for theme, c in THEMES.items():
        fig_board(boards, theme, c)
        fig_bank(bank, theme, c, result)
        fig_depth(curves, theme, c)

    print(f"game: {result[0]:,.0f} to {result[1]:,.0f}")
    print(f"wrote 2 tables and {len(list(FIGURES.glob('*.png')))} figures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
