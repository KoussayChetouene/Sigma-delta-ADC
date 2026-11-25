"""Integer CIC (Hogenauer) decimator, bit-exact with the STM32 firmware.

Structure: K integrators at the input rate -> keep every R-th sample -> K combs
(differential delay M = 1). DC gain is R**K, so divide by R**K to get back to
the normalised [-1, +1] scale.

Phase convention (shared with firmware/src/main.c): the first output is taken
after input sample index R-1, then every R samples; all delay states start at 0.
The firmware uses wrapping 32-bit arithmetic, which is exact because every
output fits in 32 bits (|y| <= R**K = 262144 for R = 64, K = 3); here int64 is
wide enough without wrapping for 2**20 input samples.
"""
from __future__ import annotations

import numpy as np


def cic_decimate(v, R: int = 64, K: int = 3) -> np.ndarray:
    """Decimate an integer stream ``v`` (e.g. +/-1 DAC levels) by R with a K-stage CIC.

    Returns the raw integer output (gain R**K).
    """
    y = np.asarray(v, dtype=np.int64)
    for _ in range(K):
        y = np.cumsum(y)
    y = y[R - 1::R]
    for _ in range(K):
        y = np.diff(y, prepend=0)
    return y


def cic_gain(R: int = 64, K: int = 3) -> int:
    return R ** K
