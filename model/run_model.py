"""Part 1 - system model of the sigma-delta ADC.

Runs the 1st-order (board architecture) and 2nd-order (IC architecture)
modulators with the same clocking as the board prototype, then writes
figures and a results table to results/model/.

    python model/run_model.py            # full run (~1 min)
    python model/run_model.py --quick    # shorter records, for a fast check
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sdm import mod1, mod2, cic_decimate, analyze_tone, spectrum_dbfs, theory_sqnr_db  # noqa: E402
from sdm import plotstyle as ps  # noqa: E402

# ---- system parameters (identical to the board, see firmware/src/main.c) ----
FS = 50_000.0                 # modulator clock [Hz]
R = 64                        # CIC decimation = OSR
K = 3                         # CIC order
FB = FS / (2 * R)             # signal band edge, 390.625 Hz
FS_DEC = FS / R               # output rate, 781.25 S/s
PHASE_INC = round(61.0 / FS * 2**32)   # same 32-bit DDS increment as the firmware
FIN = PHASE_INC * FS / 2**32           # ~61.000 Hz, deliberately not a sub-multiple of FS
AMP_DBFS = -6.0
CIC_SKIP = 8                  # decimated samples dropped at start (CIC filling up)

OUT = ROOT / "results" / "model"


def tone(n: int, amp_dbfs: float, fin: float = FIN) -> np.ndarray:
    a = 10 ** (amp_dbfs / 20)
    return a * np.sin(2 * np.pi * fin * np.arange(n) / FS)


def run_point(mod, amp_dbfs: float, n: int, **kw) -> tuple[dict, dict, np.ndarray]:
    """Return (raw-bitstream metrics, after-CIC metrics, bitstream)."""
    v = mod(tone(n, amp_dbfs), **kw)
    raw = analyze_tone(v, FS, FB, FIN)
    d = cic_decimate(v, R, K) / R**K
    nd = 2 ** int(np.log2(len(d) - CIC_SKIP))
    dec = analyze_tone(d[CIC_SKIP:CIC_SKIP + nd], FS_DEC, FS_DEC / 2, FIN)
    return raw, dec, v


def label_end(ax, x, y, text, color, dx=0, dy=0, ha="left"):
    ax.annotate(text, (x, y), xytext=(dx, dy), textcoords="offset points",
                color=ps.INK, fontsize=9, ha=ha, va="center")
    ax.plot([x], [y], "o", ms=4, color=color, mec="white", mew=1.0, zorder=5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    n_main = 2**18 if args.quick else 2**20       # 2**20 = 21 s, same as one board capture
    n_sweep = 2**16 if args.quick else 2**17

    ps.apply()
    OUT.mkdir(parents=True, exist_ok=True)
    summary: dict = {"fs_hz": FS, "osr": R, "cic_order": K, "f_band_hz": FB,
                     "fin_hz": FIN, "amp_dbfs": AMP_DBFS, "n_samples": n_main}

    # ------------------------------------------------------------------ 1. spectra
    res = {}
    for name, mod in (("mod1", mod1), ("mod2", mod2)):
        raw, dec, v = run_point(mod, AMP_DBFS, n_main)
        res[name] = (raw, dec, v)
        summary[name] = {"bitstream": raw, "after_cic": dec,
                         "theory_peak_sqnr_db": theory_sqnr_db(int(name[-1]), R)}
        print(f"{name}: bitstream SNDR {raw['sndr_db']:.1f} dB (ENOB {raw['enob_bits']:.2f}),"
              f" after CIC {dec['sndr_db']:.1f} dB, SFDR {raw['sfdr_db']:.1f} dB")

    # small multiples (one modulator per panel, shared axes) instead of two
    # overlapping noisy traces; 16-segment averaging smooths the floor
    fig, axes = plt.subplots(2, 1, figsize=(8, 6.2), sharex=True, sharey=True,
                             gridspec_kw={"hspace": 0.28})
    for ax, name, col, lab, slope in ((axes[0], "mod1", ps.C1, "1st order", 20),
                                      (axes[1], "mod2", ps.C2, "2nd order", 40)):
        f, db, nbw = spectrum_dbfs(res[name][2], FS, navg=16)
        ax.semilogx(f[1:], db[1:], color=col, lw=0.7, rasterized=True)
        ax.axvspan(f[1], FB, color=ps.GRID, alpha=0.7, lw=0, zorder=0)
        ax.text(FB * 0.92, -150, f"signal band\n0 to {FB:.0f} Hz", ha="right", va="bottom",
                color=ps.INK2, fontsize=8.5)
        # noise-shaping slope guide, drawn just under the floor between 1 and 8 kHz
        fg = np.array([1e3, 8e3])
        k = (f > 1e3) & (f < 8e3)
        off = np.median(db[k] - slope * np.log10(f[k] / 1e3)) - 12
        ax.plot(fg, off + slope * np.log10(fg / 1e3), color=ps.INK, lw=1.0, ls="--")
        ax.text(1.6e3, off + slope * np.log10(1.6) - 4, f"{slope} dB/decade",
                color=ps.INK, fontsize=9, ha="left", va="top")
        r = res[name][0]
        ax.set_title(f"{lab}: SNDR {r['sndr_db']:.1f} dB, ENOB {r['enob_bits']:.2f} bit "
                     f"(bitstream, {FIN:.0f} Hz tone at {AMP_DBFS:.0f} dBFS)", fontsize=10)
        ax.set_ylabel("Amplitude [dBFS]")
    axes[1].set_xlim(f[1], FS / 2)
    axes[1].set_ylim(-160, 5)
    axes[1].set_xlabel(f"Frequency [Hz]   (fs = 50 kHz, OSR = {R}, "
                       f"16-segment average, NBW {nbw:.2f} Hz)")
    fig.savefig(OUT / "fig1_spectrum.png")
    plt.close(fig)

    # ------------------------------------------------- 2. SNDR vs input amplitude
    amps = np.arange(-90, 0.1, 2.0)
    sweep = {"amp_dbfs": amps.tolist()}
    for name, mod in (("mod1", mod1), ("mod2", mod2)):
        sweep[name] = [run_point(mod, a, n_sweep)[0]["sndr_db"] for a in amps]
    summary["sweep"] = sweep
    fig, ax = plt.subplots(figsize=(7, 4.4))
    for name, col, lab in (("mod1", ps.C1, "1st order"), ("mod2", ps.C2, "2nd order")):
        y = np.array(sweep[name])
        pk = theory_sqnr_db(int(name[-1]), R)
        i = int(np.nanargmax(y))
        ax.plot(amps, pk + amps, color=col, lw=0.9, ls=(0, (4, 3)), alpha=0.8,
                label=f"{lab}, linear-model theory")
        ax.plot(amps, y, color=col, lw=1.6, marker="o", ms=3.5,
                label=f"{lab}, simulated (peak {y[i]:.1f} dB at {amps[i]:.0f} dBFS)")
        ax.plot([amps[i]], [y[i]], "o", ms=8, color=col, mec="white", mew=1.5, zorder=5)
        summary[name]["peak_sndr_db"] = float(y[i])
        summary[name]["peak_sndr_amp_dbfs"] = float(amps[i])
        ok = amps[y > 0]
        summary[name]["dynamic_range_db"] = float(-ok.min()) if len(ok) else None
    ax.set_xlabel("Input amplitude [dBFS]")
    ax.set_ylabel("SNDR [dB]")
    ax.set_ylim(-5, 100)
    ax.set_xlim(-92, 2)
    ax.set_title(f"SNDR vs input amplitude (bitstream, band 0 to {FB:.0f} Hz)")
    ax.legend(loc="upper left", fontsize=8.5)
    fig.savefig(OUT / "fig2_sndr_vs_amplitude.png")
    plt.close(fig)

    # -------------------------------- 3. op-amp DC gain (integrator leakage) spec
    a0_db = np.arange(10, 90.1, 5.0)
    gain_sweep = {"a0_db": a0_db.tolist()}
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for name, mod, col, lab in (("mod1", mod1, ps.C1, "1st order"),
                                ("mod2", mod2, ps.C2, "2nd order")):
        ideal = run_point(mod, AMP_DBFS, n_sweep)[0]["sndr_db"]
        y = [run_point(mod, AMP_DBFS, n_sweep, leak=10 ** (-g / 20))[0]["sndr_db"] for g in a0_db]
        gain_sweep[name] = y
        ax.plot(a0_db, y, color=col, marker="o", ms=3.5, label=lab)
        ax.axhline(ideal, color=col, lw=0.8, ls=":")
        ok = [g for g, s in zip(a0_db, y) if s >= ideal - 1.0]
        a0_min = float(min(ok)) if ok else None
        summary[name]["min_opamp_gain_db_for_1db_loss"] = a0_min
        if a0_min is not None:
            ya = y[list(a0_db).index(a0_min)]
            ax.plot([a0_min], [ya], "o", ms=4, color=col, mec="white", mew=1.0, zorder=5)
            # text placed in empty space left of the A0 = OSR line, with a leader
            xt, yt = (34.5, ya - 15) if name == "mod1" else (a0_min + 2, ya - 4)
            ax.annotate(f"< 1 dB loss\nfrom A0 = {a0_min:.0f} dB", (a0_min, ya), xytext=(xt, yt),
                        textcoords="data", ha="right" if name == "mod1" else "left",
                        va="center", fontsize=9, color=ps.INK,
                        arrowprops=dict(arrowstyle="-", color=ps.INK2, lw=0.7,
                                        shrinkA=2, shrinkB=4) if name == "mod1" else None)
    ax.axvline(20 * np.log10(R), color=ps.INK2, lw=0.8, ls="--")
    ax.text(20 * np.log10(R) + 1, 22, f"A0 = OSR\n({20 * np.log10(R):.0f} dB)", color=ps.INK2,
            fontsize=8.5)
    summary["opamp_gain_sweep"] = gain_sweep
    ax.set_xlabel("Op-amp DC gain A0 [dB]  (integrator leak = 1/A0)")
    ax.set_ylabel("SNDR [dB]")
    ax.set_title(f"Integrator leakage: SNDR vs op-amp DC gain ({AMP_DBFS:.0f} dBFS input)")
    ax.legend(loc="lower right")
    fig.savefig(OUT / "fig3_opamp_gain.png")
    plt.close(fig)

    # ------------------------------------------------- 4. integrator output swing
    x = tone(n_sweep, AMP_DBFS)
    _, s = mod1(x, return_state=True)
    _, s1, s2 = mod2(x, return_state=True)
    fig, ax = plt.subplots(figsize=(7, 4))
    bins = np.linspace(-2, 2, 161)
    swing = {}
    for data, col, lab, key in ((s, ps.C1, "1st order: integrator", "mod1_s"),
                                (s1, ps.C2, "2nd order: integrator 1", "mod2_s1"),
                                (s2, ps.C3, "2nd order: integrator 2", "mod2_s2")):
        ax.hist(data, bins=bins, histtype="step", color=col, lw=1.4, label=lab)
        swing[key] = float(np.max(np.abs(data)))
    summary["integrator_max_abs_swing_vref"] = swing
    ax.set_yscale("log")
    ax.set_xlabel("Integrator output [x Vref]")
    ax.set_ylabel("Occurrences")
    ax.set_title(f"Integrator output swing ({AMP_DBFS:.0f} dBFS input): sets op-amp swing spec")
    ax.legend(loc="upper right", fontsize=8.5)
    fig.savefig(OUT / "fig4_integrator_swing.png")
    plt.close(fig)

    # ------------------------------------------------------- 5. time-domain view
    nper = int(round(2 * FS / FIN))           # two periods of the tone
    v1 = res["mod1"][2]
    dec1 = cic_decimate(v1, R, K) / R**K
    t0 = 64 * 40                              # start after the CIC has filled
    t = (np.arange(t0, t0 + nper) - t0) / FS * 1e3
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 4.4), sharex=True,
                                 gridspec_kw={"height_ratios": [1, 2.2], "hspace": 0.12})
    seg = (v1[t0:t0 + nper] > 0).astype(float)
    from matplotlib.colors import LinearSegmentedColormap
    # area-averaged rendering: each pixel's shade = local density of +1 bits
    a1.imshow(seg[None, :], aspect="auto", interpolation="antialiased",
              cmap=LinearSegmentedColormap.from_list("bits", ["white", ps.C1]),
              extent=(t[0], t[-1], 0, 1), vmin=0, vmax=1)
    a1.set_yticks([])
    a1.grid(False)
    a1.set_ylabel("bitstream\n(shade = density\nof +1 bits)", rotation=0, ha="right",
                  va="center", fontsize=8.5)
    a1.set_title("1st-order modulator: bitstream density follows the input; "
                 "CIC output reconstructs it")
    a2.plot(t, tone(n_main, AMP_DBFS)[t0:t0 + nper], color=ps.INK2, lw=1.0,
            label="input x(t)")
    kd = np.arange(len(dec1)) * R + (R - 1)
    # CIC group delay = K (R - 1) / 2 input samples; shift so the output lines up in time
    gd = K * (R - 1) / 2
    td = kd - gd - t0
    sel = (td >= 0) & (td < nper)
    a2.plot(td[sel] / FS * 1e3, dec1[sel], "o", ms=4.5, color=ps.C1,
            mec="white", mew=0.8, label=f"CIC output ({FS_DEC:.2f} S/s), delay-aligned")
    a2.set_xlabel("Time [ms]")
    a2.set_ylabel("Normalised value")
    a2.set_ylim(-0.78, 0.62)
    a2.legend(loc="lower center", ncol=2, fontsize=8.5)
    fig.savefig(OUT / "fig5_time_domain.png")
    plt.close(fig)

    # ------------------------------------------- 6. first-cut specs for Part 3 (IC)
    kT = 1.380649e-23 * 300
    a_pk_diff = 1.0                           # assumed full-scale amplitude, differential [V]
    p_sig = (a_pk_diff * 10 ** (AMP_DBFS / 20)) ** 2 / 2
    snr_th = 80.0                             # thermal-noise SNR target at the test amplitude
    cs_min = 4 * kT / (R * p_sig / 10 ** (snr_th / 10))   # fully differential: 4kT/(Cs*OSR)
    summary["ic_first_cut"] = {
        "assumptions": "fully differential SC, 1 V peak differential full scale, "
                       f"{snr_th:.0f} dB thermal SNR at {AMP_DBFS:.0f} dBFS, T = 300 K",
        "cs_min_pf": cs_min * 1e12,
        "opamp_dc_gain_min_db": summary["mod2"]["min_opamp_gain_db_for_1db_loss"],
        "integrator_swing_max_vref": max(swing["mod2_s1"], swing["mod2_s2"]),
    }

    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (np.floating, np.integer)):
            return o.item()
        return o

    (OUT / "summary.json").write_text(json.dumps(clean(summary), indent=2))

    m1, m2 = summary["mod1"], summary["mod2"]
    rows = [
        ("Theory, peak SQNR (linear model, 0 dBFS)", m1["theory_peak_sqnr_db"], m2["theory_peak_sqnr_db"]),
        (f"Simulated SNDR, bitstream, {AMP_DBFS:.0f} dBFS", m1["bitstream"]["sndr_db"], m2["bitstream"]["sndr_db"]),
        (f"Simulated SNDR, after CIC, {AMP_DBFS:.0f} dBFS", m1["after_cic"]["sndr_db"], m2["after_cic"]["sndr_db"]),
        (f"ENOB, bitstream, {AMP_DBFS:.0f} dBFS", m1["bitstream"]["enob_bits"], m2["bitstream"]["enob_bits"]),
        (f"SFDR, bitstream, {AMP_DBFS:.0f} dBFS", m1["bitstream"]["sfdr_db"], m2["bitstream"]["sfdr_db"]),
        ("Peak SNDR (amplitude sweep)", m1["peak_sndr_db"], m2["peak_sndr_db"]),
        ("Dynamic range [dB]", m1["dynamic_range_db"], m2["dynamic_range_db"]),
        ("Min op-amp DC gain for < 1 dB loss [dB]", m1["min_opamp_gain_db_for_1db_loss"],
         m2["min_opamp_gain_db_for_1db_loss"]),
    ]
    md = ["| Metric | 1st order | 2nd order |", "|---|---:|---:|"]
    for lab, a, b in rows:
        fa = "-" if a is None else f"{a:.1f}"
        fb_ = "-" if b is None else f"{b:.1f}"
        md.append(f"| {lab} | {fa} | {fb_} |")
    ic = summary["ic_first_cut"]
    md += ["", f"First-cut Part 3 specs ({ic['assumptions']}):",
           f"- sampling capacitor Cs >= {ic['cs_min_pf']:.2f} pF (kT/C)",
           f"- op-amp DC gain >= {ic['opamp_dc_gain_min_db']:.0f} dB",
           f"- integrator output swing up to {ic['integrator_swing_max_vref']:.2f} x Vref"]
    (OUT / "summary.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    print(f"\nFigures and summary written to {OUT}")


if __name__ == "__main__":
    main()
