"""Hardware-free test of the PC pipeline.

Builds a byte-for-byte imitation of a firmware frame from the model (including
the firmware's wrapping uint32 CIC arithmetic), then runs it through the same
parse -> checksum -> CIC check -> analysis path used for real captures.

    python pc/selftest.py
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pc import link  # noqa: E402
from pc.capture import check_cic  # noqa: E402
from pc.analyze import analyze_record  # noqa: E402
from sdm import mod1  # noqa: E402

FS, R, N = 50_000, 64, 2**20
DDS_INC = 5239977


def firmware_cic_uint32(bits: np.ndarray) -> np.ndarray:
    """Same arithmetic as the ISR: uint32 integrators/combs that wrap, cast to int32."""
    x = np.where(bits == 1, np.uint32(0xFFFFFFFF), np.uint32(1)).astype(np.uint32)
    with np.errstate(over="ignore"):
        i = x
        for _ in range(3):
            i = np.cumsum(i, dtype=np.uint32)
        y = i[R - 1::R]
        for _ in range(3):
            y = (y - np.concatenate(([np.uint32(0)], y[:-1]))).astype(np.uint32)
    return y.view(np.int32)


def fake_frame(amp_counts: int, gain: float = 0.833) -> tuple[bytes, bytes, bytes]:
    fin = DDS_INC * FS / 2**32
    a = gain * amp_counts / link.PWM_HALF
    rng = np.random.default_rng(0)
    x = a * np.sin(2 * np.pi * fin * np.arange(N) / FS) + 2e-4 * rng.standard_normal(N)
    v = mod1(x)
    bits = ((1 - v) // 2).astype(np.uint8)              # b = (1 - v) / 2
    packed = np.packbits(bits, bitorder="little")
    dec = firmware_cic_uint32(bits)
    payload = packed.tobytes() + dec.astype("<i4").tobytes()
    header = link.HDR.pack(link.MAGIC, N, len(dec), amp_counts, R, FS, DDS_INC)
    trailer = struct.pack("<I", int(np.frombuffer(payload, np.uint8).sum(dtype=np.uint64)) & 0xFFFFFFFF)
    return header, payload, trailer


def main() -> None:
    for amp, name in ((1083, "selftest_tone"), (0, "selftest_idle")):
        rec = link.parse_frame(*fake_frame(amp))
        assert check_cic(rec), "CIC mismatch"
        path = link.save_record(rec, name)
        analyze_record(path, out_dir=link.ROOT / "results" / "selftest")
    # a corrupted frame must be rejected
    h, p, t = fake_frame(1083)
    bad = bytearray(p)
    bad[1000] ^= 0x10
    try:
        link.parse_frame(h, bytes(bad), t)
        raise AssertionError("corrupted frame was accepted")
    except link.FrameError:
        print("\ncorrupted frame correctly rejected by checksum")
    print("SELFTEST PASSED")


if __name__ == "__main__":
    main()
