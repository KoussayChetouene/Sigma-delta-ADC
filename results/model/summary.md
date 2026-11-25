| Metric | 1st order | 2nd order |
|---|---:|---:|
| Theory, peak SQNR (linear model, 0 dBFS) | 56.8 | 85.2 |
| Simulated SNDR, bitstream, -6 dBFS | 46.2 | 69.7 |
| Simulated SNDR, after CIC, -6 dBFS | 51.1 | 74.5 |
| ENOB, bitstream, -6 dBFS | 7.4 | 11.3 |
| SFDR, bitstream, -6 dBFS | 53.8 | 81.2 |
| Peak SNDR (amplitude sweep) | 52.5 | 70.2 |
| Dynamic range [dB] | 40.0 | 74.0 |
| Min op-amp DC gain for < 1 dB loss [dB] | 25.0 | 35.0 |

First-cut Part 3 specs (fully differential SC, 1 V peak differential full scale, 80 dB thermal SNR at -6 dBFS, T = 300 K):
- sampling capacitor Cs >= 0.21 pF (kT/C)
- op-amp DC gain >= 35 dB
- integrator output swing up to 1.37 x Vref
