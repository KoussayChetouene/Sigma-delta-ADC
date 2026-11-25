"""Shared Matplotlib style: one palette, thin marks, recessive grid."""
from __future__ import annotations

import matplotlib as mpl

# Categorical slots, always assigned in this order (never cycled)
C1 = "#257de0"   # blue   - 1st-order / model
C2 = "#f47230"   # orange - 2nd-order / board
C3 = "#00b894"   # aqua   - third series
INK = "#191919"
INK2 = "#666666"
GRID = "#e7e7e7"
AXIS = "#c2c2c2"


def apply() -> None:
    mpl.rcParams.update({
        "figure.dpi": 110,
        "savefig.dpi": 160,
        "savefig.bbox": "tight",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
        "font.size": 9.5,
        "text.color": INK,
        "axes.labelcolor": INK2,
        "axes.titlesize": 11,
        "axes.titleweight": "semibold",
        "axes.titlecolor": INK,
        "axes.titlelocation": "left",
        "axes.edgecolor": AXIS,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "xtick.major.size": 3,
        "ytick.major.size": 3,
        "legend.frameon": False,
        "legend.fontsize": 9,
        "lines.linewidth": 1.4,
    })
