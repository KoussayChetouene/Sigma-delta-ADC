"""Frame format shared with firmware/src/main.c, plus record save/load."""
from __future__ import annotations

import struct
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

MAGIC = b"SDM1"
HDR = struct.Struct("<4sIIHHII")   # magic, n_bits, n_dec, amp, cic_r, fs_hz, dds_inc
BAUD = 921600
PWM_HALF = 2160                    # PWM counts for a full +/-1.65 V swing at the pin
AMP_MAX = 2100                     # firmware limit
CIC_K = 3


class FrameError(RuntimeError):
    pass


def parse_frame(header: bytes, payload: bytes, trailer: bytes) -> dict:
    """Decode one capture frame and check its checksum."""
    magic, n_bits, n_dec, amp, cic_r, fs_hz, dds_inc = HDR.unpack(header)
    if magic != MAGIC:
        raise FrameError(f"bad magic {magic!r}")
    n_bytes = n_bits // 8
    if len(payload) != n_bytes + 4 * n_dec:
        raise FrameError(f"payload is {len(payload)} bytes, expected {n_bytes + 4 * n_dec}")
    (sum_fw,) = struct.unpack("<I", trailer)
    sum_pc = int(np.frombuffer(payload, dtype=np.uint8).sum(dtype=np.uint64)) & 0xFFFFFFFF
    if sum_fw != sum_pc:
        raise FrameError(f"checksum mismatch (board {sum_fw:#010x}, PC {sum_pc:#010x}): "
                         "serial data corrupted; try again or lower BAUD in both firmware and pc/link.py")
    return {
        "bits_packed": np.frombuffer(payload[:n_bytes], dtype=np.uint8).copy(),
        "dec": np.frombuffer(payload[n_bytes:], dtype="<i4").astype(np.int32),
        "amp_counts": amp, "cic_r": cic_r, "fs_hz": fs_hz, "dds_inc": dds_inc,
        "n_bits": n_bits,
    }


def unpack_bits(bits_packed: np.ndarray) -> np.ndarray:
    """Packed bytes (LSB = earliest sample) -> array of 0/1."""
    return np.unpackbits(bits_packed, bitorder="little")


def save_record(rec: dict, name: str) -> Path:
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / f"{name}.npz"
    np.savez_compressed(path, timestamp=time.strftime("%Y-%m-%d %H:%M:%S"), **rec)
    return path


def load_record(path) -> dict:
    with np.load(path) as z:
        rec = {k: z[k] for k in z.files}
    for k in ("amp_counts", "cic_r", "fs_hz", "dds_inc", "n_bits"):
        rec[k] = int(rec[k])
    rec["timestamp"] = str(rec["timestamp"])
    return rec
