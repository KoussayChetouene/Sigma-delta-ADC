"""Behavioural discrete-time sigma-delta modulators (1-bit quantizer).

Normalised units used everywhere in this project
------------------------------------------------
* Input ``x`` is referred to the 1-bit DAC reference: x = (Vin - Vmid) / (VDD / 2),
  so the full-scale range is [-1, +1]. On the board VDD = 3.3 V and Vmid = 1.65 V.
* Output ``v`` is the 1-bit DAC level, +1 or -1.
* The board stores the comparator bit b. Because the analog integrator is
  inverting, v = 1 - 2*b (b = 1 means "input is low"). ``bits_to_levels`` does
  this mapping, so ones-density = 1 - Vin / VDD.

Both models use delaying integrators, which matches both the board (the MCU
latches the comparator, then drives the feedback for one full period) and a
two-phase switched-capacitor implementation (Part 3).
"""
from __future__ import annotations

import numpy as np


def bits_to_levels(bits: np.ndarray) -> np.ndarray:
    """Map stored comparator bits {0, 1} to DAC levels {+1, -1} (v = 1 - 2b)."""
    return 1 - 2 * np.asarray(bits, dtype=np.int8)


def mod1(x, leak: float = 0.0, return_state: bool = False):
    """First-order modulator.

        v[n]   = sign(s[n])
        s[n+1] = (1 - leak) * s[n] + x[n] - v[n]

    STF = z^-1, NTF = 1 - z^-1.

    ``leak`` models a lossy integrator. For a switched-capacitor integrator
    built around an op-amp with DC gain A0, leak ~= 1 / A0 (first-order estimate).

    Returns v (int8 array of +/-1), and the integrator state if requested.
    """
    xs = np.asarray(x, dtype=float).tolist()
    p = 1.0 - leak
    v = [0] * len(xs)
    st = [0.0] * len(xs) if return_state else None
    s = 0.0
    for i, xi in enumerate(xs):
        vi = 1 if s >= 0.0 else -1
        v[i] = vi
        if st is not None:
            st[i] = s
        s = p * s + xi - vi
    v = np.asarray(v, dtype=np.int8)
    return (v, np.asarray(st)) if return_state else v


def mod2(x, a1: float = 0.5, a2: float = 0.5, leak: float = 0.0,
         return_state: bool = False):
    """Second-order modulator, Boser-Wooley scaling (both integrator gains 0.5).

        v[n]    = sign(s2[n])
        s2[n+1] = (1 - leak) * s2[n] + a2 * (s1[n] - v[n])
        s1[n+1] = (1 - leak) * s1[n] + a1 * (x[n] - v[n])

    With the 1-bit quantizer's effective gain settling near 1/(a1*a2), the loop
    gives STF ~= z^-2 and NTF ~= (1 - z^-1)^2. The 0.5 gains keep both integrator
    outputs within roughly +/-1.5 Vref, which sets the op-amp swing spec for Part 3.

    Returns v (int8 array of +/-1), and (s1, s2) if requested.
    """
    xs = np.asarray(x, dtype=float).tolist()
    p = 1.0 - leak
    n = len(xs)
    v = [0] * n
    st1 = [0.0] * n if return_state else None
    st2 = [0.0] * n if return_state else None
    s1 = 0.0
    s2 = 0.0
    for i, xi in enumerate(xs):
        vi = 1 if s2 >= 0.0 else -1
        v[i] = vi
        if st1 is not None:
            st1[i] = s1
            st2[i] = s2
        s2 = p * s2 + a2 * (s1 - vi)   # uses s1[n] (delaying integrators)
        s1 = p * s1 + a1 * (xi - vi)
    v = np.asarray(v, dtype=np.int8)
    if return_state:
        return v, np.asarray(st1), np.asarray(st2)
    return v
