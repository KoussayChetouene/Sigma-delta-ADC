"""Capture data from the board over the ST-LINK virtual COM port.

    python pc/capture.py --ping                      # check the link
    python pc/capture.py --amp-db -6 --name tone_m6  # one capture (21 s + 17 s transfer), then analysis
    python pc/capture.py --amp-db off --name idle    # no tone: idle-channel noise
    python pc/capture.py --sweep                     # SNDR vs amplitude (about 7 min)

--amp-db is relative to the largest swing the PWM pin can make (+/-1.65 V); the
RC filter and the 10 k input resistor scale it by about 0.83, so the modulator
sees roughly 1.6 dB less. The analysis measures the real amplitude in dBFS.
"""
from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

import numpy as np
import serial
import serial.tools.list_ports

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pc import link  # noqa: E402
from pc.analyze import analyze_record, analyze_sweep  # noqa: E402
from sdm import bits_to_levels, cic_decimate  # noqa: E402

SWEEP_DB = [-60, -50, -40, -30, -20, -14, -10, -6, -3, -1]


def find_port() -> str:
    for p in serial.tools.list_ports.comports():
        text = f"{p.description} {p.manufacturer}".lower()
        if p.vid == 0x0483 or "stlink" in text or "st-link" in text:
            return p.device
    ports = ", ".join(p.device for p in serial.tools.list_ports.comports()) or "none"
    raise SystemExit("ST-LINK virtual COM port not found (ports seen: " + ports + ").\n"
                     "Plug the board's USB ST-LINK connector (CN14) or pass --port COMx.")


def read_exact(ser: serial.Serial, n: int, what: str) -> bytes:
    data = ser.read(n)
    if len(data) != n:
        raise link.FrameError(f"timeout while reading {what}: got {len(data)} of {n} bytes")
    return data


def ping(ser: serial.Serial) -> str:
    ser.reset_input_buffer()
    ser.write(b"P")
    return ser.readline().decode(errors="replace").strip()


CAPTURE_S = 2**20 / 50000                          # 21 s of samples at fs
XFER_S = (2**20 // 8 + 4 * 2**14) * 10 / link.BAUD  # frame transfer time (8N1)
TRIES = 3


def drain(ser: serial.Serial) -> None:
    """Throw away whatever is still arriving from a failed transfer."""
    ser.timeout = 0.5
    while ser.read(65536):
        pass
    ser.reset_input_buffer()


def capture(ser: serial.Serial, amp_counts: int) -> dict:
    """One capture; retried if the serial transfer loses or corrupts bytes."""
    for attempt in range(1, TRIES + 1):
        try:
            return capture_once(ser, amp_counts)
        except link.FrameError as e:
            if attempt == TRIES:
                raise
            print(f"  transfer error: {e}\n  retrying ({attempt + 1}/{TRIES}) ...", flush=True)
            drain(ser)


def capture_once(ser: serial.Serial, amp_counts: int) -> dict:
    # Set the timeout once, while the line is idle. On Windows, changing it re-applies
    # the whole port configuration, and the ST-LINK bridge then drops the bytes in
    # flight (measured: ~1 ms of data lost per change, mid-frame).
    ser.timeout = CAPTURE_S + 1.5 * XFER_S + 10.0
    ser.reset_input_buffer()
    ser.write(b"C" + struct.pack("<H", amp_counts))
    t0 = time.time()
    print(f"  capturing {CAPTURE_S:.0f} s + {XFER_S:.0f} s transfer "
          f"(amplitude {amp_counts} PWM counts), keep the board still ...", flush=True)
    # wait for the magic word (the board sends nothing else while capturing)
    window = b""
    while window != link.MAGIC:
        c = ser.read(1)
        if not c:
            raise link.FrameError(f"no data from the board after {ser.timeout:.0f} s "
                                  "(is the firmware flashed? does --ping work?)")
        window = (window + c)[-4:]
    header = link.MAGIC + read_exact(ser, link.HDR.size - 4, "header")
    _, n_bits, n_dec, *_ = link.HDR.unpack(header)
    payload = read_exact(ser, n_bits // 8 + 4 * n_dec, "payload")
    trailer = read_exact(ser, 4, "checksum")
    rec = link.parse_frame(header, payload, trailer)
    print(f"  received {len(payload) / 1024:.0f} KiB in {time.time() - t0:.1f} s, checksum OK")
    return rec


def check_cic(rec: dict) -> bool:
    """The firmware CIC must match the Python reference sample for sample."""
    v = bits_to_levels(link.unpack_bits(rec["bits_packed"]))
    ref = cic_decimate(v, rec["cic_r"], link.CIC_K)
    ok = np.array_equal(ref, rec["dec"].astype(np.int64))
    print(f"  firmware CIC vs Python CIC: {'bit-exact match' if ok else 'MISMATCH'} "
          f"({len(ref)} samples)")
    return ok


def amp_from_db(db) -> int:
    if str(db).lower() == "off":
        return 0
    return int(min(round(link.PWM_HALF * 10 ** (float(db) / 20)), link.AMP_MAX))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port, e.g. COM5 (default: auto-detect ST-LINK)")
    ap.add_argument("--ping", action="store_true", help="only check the link")
    ap.add_argument("--amp-db", default="-6", help="tone amplitude in dB re PWM full swing, or 'off'")
    ap.add_argument("--name", default=None, help="record name (file data/<name>.npz)")
    ap.add_argument("--sweep", action="store_true", help=f"capture at {SWEEP_DB} dB")
    args = ap.parse_args()

    port = args.port or find_port()
    with serial.Serial(port, link.BAUD, timeout=2.0) as ser:
        time.sleep(0.1)
        reply = ping(ser)
        print(f"{port}: {reply or '(no reply)'}")
        if not reply.startswith("SDM1"):
            raise SystemExit("The board did not answer. Check that the firmware is flashed "
                             "(firmware/flash.ps1) and press the black RESET button.")
        if args.ping:
            return

        if args.sweep:
            paths = []
            for db in SWEEP_DB:
                print(f"[sweep] {db} dB")
                rec = capture(ser, amp_from_db(db))
                check_cic(rec)
                paths.append(link.save_record(rec, f"sweep_{abs(db):02d}dB"))
            analyze_sweep(paths)
            return

        name = args.name or ("idle" if str(args.amp_db).lower() == "off"
                             else f"tone_{str(args.amp_db).replace('-', 'm')}dB")
        rec = capture(ser, amp_from_db(args.amp_db))
        check_cic(rec)
        path = link.save_record(rec, name)
        print(f"  saved {path}")
    analyze_record(path)


if __name__ == "__main__":
    main()
