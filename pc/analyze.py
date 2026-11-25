"""Analyse board captures and compare them with the ideal model.

    python pc/analyze.py data/tone_m6dB.npz          # one record
    python pc/analyze.py --sweep data/sweep_*.npz    # SNDR vs amplitude
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pc import link  # noqa: E402
from sdm import analyze_tone, bits_to_levels, cic_decimate, mod1, spectrum_dbfs  # noqa: E402
from sdm.metrics import power_bins, DC_BINS  # noqa: E402
from sdm import plotstyle as ps  # noqa: E402

OUT = ROOT / "results" / "board"
VDD = 3.3
CIC_SKIP = 8


def _fin(rec) -> float:
    return rec["dds_inc"] * rec["fs_hz"] / 2**32


def _model_bits(amp: float, fin: float, fs: float, n: int, dc: float = 0.0) -> np.ndarray:
    """Ideal 1st-order modulator at the board's operating point (tone amplitude and DC).

    The DC offset matters at low amplitude: with zero DC an ideal 1st-order loop puts
    idle tones in band, while the board's offset pushes them above the band.
    """
    return mod1(dc + amp * np.sin(2 * np.pi * fin * np.arange(n) / fs))


def idle_report(v, fs, fb) -> dict:
    f, P = power_bins(v, fs)
    kb = int(np.floor(fb / fs * len(v)))
    band = P[DC_BINS:kb + 1]
    top = np.argsort(band)[::-1][:5] + DC_BINS
    return {"inband_noise_dbfs": float(10 * np.log10(band.sum() / 0.5)),
            "top_spurs_hz_dbfs": [(round(float(f[k]), 2), round(float(10 * np.log10(P[k] / 0.5)), 1))
                                  for k in top]}


def analyze_record(path, plot: bool = True, quiet: bool = False, out_dir: Path = OUT) -> dict:
    path, OUT_ = Path(path), Path(out_dir)
    rec = link.load_record(path)
    fs, R = float(rec["fs_hz"]), rec["cic_r"]
    fb, fin = fs / (2 * R), _fin(rec)
    v = bits_to_levels(link.unpack_bits(rec["bits_packed"])).astype(float)
    dec = rec["dec"] / R**link.CIC_K
    dc = float(v.mean())
    out = {"record": path.name, "timestamp": rec["timestamp"], "amp_counts": rec["amp_counts"],
           "fs_hz": fs, "osr": R, "fin_hz": fin,
           "dc_offset_norm": dc, "dc_offset_mv": dc * VDD / 2 * 1e3,
           "ones_density": float(np.mean(link.unpack_bits(rec["bits_packed"])))}

    if rec["amp_counts"] == 0:
        out["idle"] = idle_report(v, fs, fb)
        model = None
    else:
        out["bitstream"] = analyze_tone(v, fs, fb, fin)
        nd = 2 ** int(np.log2(len(dec) - CIC_SKIP))
        out["after_cic"] = analyze_tone(dec[CIC_SKIP:CIC_SKIP + nd], fs / R, fs / (2 * R), fin)
        amp = 10 ** (out["bitstream"]["sig_dbfs"] / 20)
        vm = _model_bits(amp, fin, fs, len(v), dc)
        model = analyze_tone(vm, fs, fb, fin)
        out["model_same_point"] = model
        out["model_zero_offset"] = analyze_tone(_model_bits(amp, fin, fs, len(v)), fs, fb, fin)

    if not quiet:
        print(f"\n== {path.name} ==")
        print(f"  ones density {out['ones_density']:.4f}, DC offset {out['dc_offset_mv']:+.1f} mV "
              f"(re 1.65 V)")
        if model is None:
            print(f"  idle channel: in-band noise {out['idle']['inband_noise_dbfs']:.1f} dBFS; "
                  f"largest in-band spurs (Hz, dBFS): {out['idle']['top_spurs_hz_dbfs'][:3]}")
        else:
            b, a = out["bitstream"], out["after_cic"]
            print(f"  tone {b['f_sig_hz']:.3f} Hz at {b['sig_dbfs']:.2f} dBFS")
            print(f"  board, bitstream : SNDR {b['sndr_db']:.1f} dB  ENOB {b['enob_bits']:.2f}  "
                  f"SFDR {b['sfdr_db']:.1f} dB  THD {b['thd_db']:.1f} dB")
            print(f"  board, after CIC : SNDR {a['sndr_db']:.1f} dB  ENOB {a['enob_bits']:.2f}")
            print(f"  ideal model, same amplitude and DC: SNDR {model['sndr_db']:.1f} dB  "
                  f"ENOB {model['enob_bits']:.2f}  SFDR {model['sfdr_db']:.1f} dB  "
                  f"(zero-DC model: SNDR {out['model_zero_offset']['sndr_db']:.1f} dB)")

    OUT_.mkdir(parents=True, exist_ok=True)
    (OUT_ / f"{path.stem}.json").write_text(json.dumps(out, indent=2, default=float))

    if plot:
        ps.apply()
        series = [("Board measurement", v, ps.C2, out.get("bitstream"))]
        if model is not None:
            series.append(("Ideal 1st-order model, same amplitude and DC", vm, ps.C1, model))
        fig, axes = plt.subplots(len(series), 1, figsize=(8, 3.1 * len(series) + 0.4),
                                 sharex=True, sharey=True, squeeze=False,
                                 gridspec_kw={"hspace": 0.3})
        for ax, (lab, data, col, m) in zip(axes[:, 0], series):
            f, db, nbw = spectrum_dbfs(data, fs, navg=16)
            ax.semilogx(f[1:], db[1:], color=col, lw=0.7, rasterized=True)
            ax.axvspan(f[1], fb, color=ps.GRID, alpha=0.7, lw=0, zorder=0)
            t = lab if m is None else f"{lab}: SNDR {m['sndr_db']:.1f} dB, ENOB {m['enob_bits']:.2f} bit"
            ax.set_title(t, fontsize=10)
            ax.set_ylabel("Amplitude [dBFS]")
        ax.set_xlim(f[1], fs / 2)
        ax.set_ylim(-160, 5)
        ax.set_xlabel(f"Frequency [Hz]   (bitstream, fs = {fs / 1e3:.0f} kHz, signal band "
                      f"0 to {fb:.0f} Hz shaded, 16-segment average, NBW {nbw:.2f} Hz)")
        fig.savefig(OUT_ / f"{path.stem}_spectrum.png")
        plt.close(fig)
        if not quiet:
            print(f"  figure: {OUT_ / (path.stem + '_spectrum.png')}")
    return out


def analyze_sweep(paths) -> None:
    res = [analyze_record(p, plot=False, quiet=True) for p in paths]
    res = [r for r in res if "bitstream" in r]
    res.sort(key=lambda r: r["bitstream"]["sig_dbfs"])
    amp = np.array([r["bitstream"]["sig_dbfs"] for r in res])
    board = np.array([r["bitstream"]["sndr_db"] for r in res])
    model = np.array([r["model_same_point"]["sndr_db"] for r in res])
    model0 = np.array([r["model_zero_offset"]["sndr_db"] for r in res])
    dc_mv = np.mean([r["dc_offset_mv"] for r in res])
    ps.apply()
    fig, ax = plt.subplots(figsize=(7, 4.3))
    ax.plot(amp, model0, color=ps.INK2, ls="--", lw=1.0,
            label="Ideal model, zero DC offset (idle tones in band)")
    ax.plot(amp, model, color=ps.C1, marker="o", ms=3.5,
            label=f"Ideal model, board's DC offset ({dc_mv:+.0f} mV)")
    ax.plot(amp, board, color=ps.C2, marker="o", ms=4.5, lw=1.8, label="Board measurement")
    i = int(np.argmax(board))
    ax.plot([amp[i]], [board[i]], "o", ms=8, color=ps.C2, mec="white", mew=1.5, zorder=5)
    ax.annotate(f"peak {board[i]:.1f} dB\n(ENOB {(board[i] - 1.76) / 6.02:.2f})",
                (amp[i], board[i]), xytext=(4, -22), textcoords="offset points",
                ha="center", va="top", fontsize=9, color=ps.INK)
    ax.set_xlabel("Measured input amplitude [dBFS]")
    ax.set_ylabel("SNDR [dB]")
    ax.set_title("Board vs model: SNDR vs input amplitude (bitstream, 0 to 391 Hz)")
    ax.legend(loc="upper left")
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / "sweep_sndr_vs_amplitude.png")
    plt.close(fig)
    rows = ["| Amplitude [dBFS] | Board SNDR [dB] | Board ENOB | Model SNDR, board's DC [dB] "
            "| Model SNDR, zero DC [dB] |",
            "|---:|---:|---:|---:|---:|"]
    rows += [f"| {a:.1f} | {b:.1f} | {(b - 1.76) / 6.02:.2f} | {m:.1f} | {m0:.1f} |"
             for a, b, m, m0 in zip(amp, board, model, model0)]
    (OUT / "sweep_summary.md").write_text("\n".join(rows) + "\n")
    print("\n".join(rows))
    print(f"figure: {OUT / 'sweep_sndr_vs_amplitude.png'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()
    files = [p for pat in args.files for p in (glob.glob(pat) or [pat])]
    if args.sweep:
        analyze_sweep(files)
    else:
        for p in files:
            analyze_record(p)


if __name__ == "__main__":
    main()
