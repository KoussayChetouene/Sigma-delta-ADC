# Board prototype: build, flash, measure

Time needed: about 45 min wiring, 5 min flashing, 10 min measuring.
Tools: breadboard, jumper wires, multimeter. No oscilloscope needed.

## 1. Circuit

```
 TEST SIGNAL FILTER                        INTEGRATOR (MCP6002 half A)

 D10 ─[1k]─┬─[1k]─┬─[10k]─┐                ┌────||────┐  C = 100 nF
           │      │       │                │          │
         100nF  100nF     ├── N_SUM ───────┴── pin 2  │
           │      │       │                           │
          GND    GND      │     N_REF ──────── pin 3  │
                          │                    pin 1 ─┴── N_INT
 D7 (FB) ──────[10k]──────┘

 COMPARATOR (MCP6002 half B)              1.65 V REFERENCE (N_REF)

 N_INT ─── pin 5 (+)                      3V3 ─[10k]─┬─[10k]─ GND
 N_REF ─── pin 6 (−)                                 ├─ 1 µF ─ GND
           pin 7 ───> D4 (CMP)                       └─ N_REF

 OP-AMP SUPPLY (4th 100 nF, as close to the chip as possible)

 3V3 ──┬── pin 8
       │
     100nF
       │
 GND ──┴── pin 4
```

The circuit uses **four** 100 nF capacitors (integrator, two in the test-signal filter,
one supply decoupling) and **one** 1 µF (reference).

Netlist (every node and everything that touches it; use this as the checklist):

| Node | Connects to |
|---|---|
| **3V3** | Disco CN6 "3V3", MCP6002 pin 8, top 10 kΩ of the divider, 100 nF decoupling, (10 µF +) |
| **GND** | Disco CN6 "GND", MCP6002 pin 4, bottom 10 kΩ of the divider, 1 µF, both filter 100 nF, 100 nF decoupling |
| **N_REF** (1.65 V) | both divider 10 kΩ, 1 µF, MCP6002 **pin 3** and **pin 6** |
| **N_F1** | 1 kΩ from D10, second 1 kΩ, 100 nF to GND |
| **N_F2** | second 1 kΩ, 100 nF to GND, 10 kΩ input resistor |
| **N_SUM** | MCP6002 **pin 2**, 10 kΩ input resistor (from N_F2), 10 kΩ feedback resistor (from D7), integrator 100 nF |
| **N_INT** | MCP6002 **pin 1**, other leg of the integrator 100 nF, MCP6002 **pin 5** |
| **CMP** | MCP6002 **pin 7**, Disco **D4** |
| **FB** | Disco **D7**, 10 kΩ feedback resistor |
| **PWM** | Disco **D10**, first 1 kΩ |

How it works: the PWM plus the two RC stages make a clean ~61 Hz test sine (the
Discovery board's DAC pins are not on its headers). Op-amp A integrates the
difference between that input and the 1-bit feedback FB. Op-amp B, used as a
comparator, tells the STM32 whether the integrator is above or below 1.65 V. Every
20 µs (fs = 50 kHz) the STM32 reads the comparator and copies it to FB. That closed
loop is a 1st-order sigma-delta modulator.

## 2. Parts (all from your kit)

| Part | Qty | Where |
|---|---|---|
| MCP6002 (8-pin DIP) | 1 | across the breadboard's centre gap |
| 10 kΩ | 4 | input resistor, feedback resistor, 2 for the 1.65 V divider |
| 1 kΩ | 2 | PWM filter |
| 100 nF ceramic ("104") | 4 | integrator, MCP6002 supply decoupling, 2 for the PWM filter |
| 1 µF | 1 | 1.65 V reference filter (if electrolytic: **+** leg to N_REF) |
| 10 µF electrolytic (optional) | 1 | across the 3V3/GND rails, **+** to 3V3 |

MCP6002 pins (dot or notch = pin 1, counting anticlockwise seen from the top):

```
        ┌──∪──┐
 OUTA 1 │     │ 8 VDD (3V3)
 INA− 2 │     │ 7 OUTB
 INA+ 3 │     │ 6 INB−
  VSS 4 │     │ 5 INB+
        └─────┘
```

Discovery board connections (Arduino headers, printed on the board):

| Signal | Header pin | MCU pin | Direction |
|---|---|---|---|
| 3V3 | CN6 "3V3" (power header, pin 4) | - | board → breadboard + rail |
| GND | CN6 "GND" (pin 6 or 7) | - | board → breadboard − rail |
| FB (1-bit DAC) | **D7** | PI3 | board → 10 kΩ feedback resistor |
| CMP (comparator) | **D4** | PG7 | MCP6002 pin 7 → board |
| PWM test signal | **D10** | PA8 (TIM1_CH1) | board → first 1 kΩ |

**Already have the sensor wiring connected** (MPU6050 on D14/D15, DHT11 on D2, 433 MHz
modules on D0/D1, PDM mic on D12/D13)? Leave it in place. This firmware does not touch
those pins, except D1, which it holds low so the 433 MHz transmitter stays silent. The
ΣΔ circuit only uses **D4, D7, D10, 3V3 and GND**, which are all free in that wiring.
The extra sensors share the 3V3 rail; if the measurement looks noisy, unplug them and compare.

## 3. Wiring order (with a check after each block)

Unplug the USB cable while wiring.

1. **Power rails.** CN6 3V3 → red (+) rail, CN6 GND → blue (−) rail.
2. **Op-amp supply.** Pin 8 → + rail, pin 4 → − rail, 100 nF between pins 8 and 4, as close to the chip as possible.
3. **1.65 V reference (N_REF).** 10 kΩ from + rail to a free row (that row is N_REF), 10 kΩ from N_REF to − rail, 1 µF from N_REF to − rail. Wire N_REF to **pin 3** and to **pin 6**.
   *Check:* plug USB in. Multimeter between N_REF and GND reads **1.60 to 1.70 V**. Unplug.
4. **Integrator.** 100 nF between **pin 2** and **pin 1**.
5. **Feedback resistor.** 10 kΩ from **D7** to **pin 2**.
6. **Comparator.** Wire **pin 1 → pin 5**. Wire **pin 7 → D4**.
7. **Test-signal filter.** D10 → 1 kΩ → row N_F1; 100 nF from N_F1 to GND; N_F1 → 1 kΩ → row N_F2; 100 nF from N_F2 to GND; **10 kΩ from N_F2 to pin 2** (input resistor).
8. Optional: 10 µF across the rails (+ leg on 3V3).

Double-check the two connections that most often go wrong:
- pin 5 (comparator +) goes to the **integrator output (pin 1)**, pin 6 (comparator −) goes to **N_REF**. Swapped = positive feedback, and the integrator sticks at a rail.
- Both 10 kΩ resistors (from D7 and from N_F2) land on **pin 2**, the same pin as one leg of the integrator capacitor.

## 4. Flash the firmware

The firmware is already built: `firmware/build/sdm_f746.bin` (rebuild with
`firmware/build.ps1` if you change `firmware/src/main.c`).

Plug the USB cable into the connector marked **USB ST-LINK (CN14)**, then either:

- **Drag and drop:** copy `firmware\build\sdm_f746.bin` onto the `DIS_F746NG` drive that appears in Explorer. The board reprograms itself and restarts (the LCD stays dark; that's expected).
- **Or from PowerShell:**
  ```powershell
  cd firmware
  powershell -ExecutionPolicy Bypass -File .\flash.ps1
  ```

This replaces ST's demo firmware on the board. You can restore it later from ST's
website if you want it back.

## 5. Check the running loop with the multimeter

At power-up the tone is off and the PWM runs at 50 % duty, so the input sits at 1.65 V.
A multimeter on DC volts averages the fast switching, so you should read:

| Point | Expected | If not |
|---|---|---|
| N_REF | 1.60 to 1.70 V | check the divider |
| N_F2 | about 1.65 V | check D10 wire and the 1 kΩ resistors |
| pin 1 (integrator out) | 1.55 to 1.75 V | **at 0 V or 3.3 V = loop not closed**: check comparator pins 5/6, D7, D4 |
| D7 (FB) and pin 7 | about 1.65 V (switching ~50 % of the time) | stuck at 0 or 3.3 V = loop not closed |

## 6. Measure

From the project folder:

```powershell
python pc/capture.py --ping                      # board answers "SDM1 fs=50000 ..."
python pc/capture.py --amp-db off --name idle    # ~23 s, no tone: noise floor and mains hum
python pc/capture.py --amp-db -6                 # ~23 s, 61 Hz tone: SNDR, ENOB, spectrum
python pc/capture.py --sweep                     # 10 amplitudes, about 4 min: SNDR vs amplitude
```

Each capture prints SNDR/ENOB next to the ideal model's at the same amplitude, checks
that the on-chip CIC output is bit-exact with the Python CIC, and writes a figure and a
JSON file to `results/board/`. Raw data goes to `data/`.

Keep the board still and the wires short while capturing. Running the laptop on
battery reduces 50 Hz hum.

## 7. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ST-LINK virtual COM port not found` | USB in the wrong connector (use CN14), or pass `--port COMx` (see Device Manager → Ports) |
| `The board did not answer` | firmware not flashed, or press the black RESET button and retry |
| `transfer error ... retrying` | bytes lost on the serial link; the PC retries a capture up to 3 times. If it never succeeds, set `BAUD` to 115200 in `firmware/src/main.c` **and** `pc/link.py`, rebuild, reflash (captures get ~15 s slower). Don't change `ser.timeout` in `pc/capture.py` while a frame is arriving: on Windows that reconfigures the port and the ST-LINK drops ~1 ms of data |
| Integrator output stuck at a rail | comparator inputs swapped, or FB/CMP wires on the wrong pins |
| Big spurs at 50, 100, 150 Hz | mains pickup: shorter wires, laptop on battery, keep hands away |
| SNDR far below the model, noisy floor everywhere | loose breadboard contact, missing 100 nF decoupling, or the 1 µF missing on N_REF |
