# Signal Box XIAO test fixture

Firmware for a spare Seeed XIAO RP2040 that replaces the logic analyzer and
USB-UART adapter during production acceptance. The DUT must be running the
companion firmware in `../debug/`.

The tester is powered from its own USB connection. Each DUT is powered from a
separate USB connection. **Never connect the tester and DUT 3V3 rails.** Power
the tester before connecting or powering a DUT; do not leave a powered DUT
attached to an unpowered tester.

## Six-pin fixture wiring

A keyed connector is strongly recommended. The following order is suggested,
but the electrical mapping is what matters:

| Header | DUT test point | Tester connection |
|---:|---|---|
| 1 | GND | XIAO GND |
| 2 | 3V3 | 10 kΩ to tester D1/GPIO27/ADC1; another 10 kΩ from D1 to GND |
| 3 | SDA | D2/GPIO28 |
| 4 | SCL | D3/GPIO29 |
| 5 | UART TX | D4/GPIO6/PIO UART RX |
| 6 | UART RX | D5/GPIO7/PIO UART TX |

The two 10 kΩ resistors form a 2:1 divider. Nominal DUT 3.3 V therefore appears
as approximately 1.65 V at tester D1. D1 is an ADC input, not a power
connection. The ADC compares the DUT rail to the tester's own 3V3 reference, so
measure the known-good tester rail once before using the jig. The compiled
`1955-2140` window represents DUT 3.15-3.45 V only when the tester rail is
3.300 V; adjust `src/config.h` if calibration differs. A precision absolute
voltage guarantee would require an external reference or a DMM, but not one DMM
measurement per DUT.

GPIO28 and GPIO29 are normally high impedance. During the DUT's marked passive
window, the tester drives only LOW through the GPIO output-enable control and
then returns to high impedance. It never actively drives either I2C line high.

D4/GPIO6 and D5/GPIO7 are not a native RP2040 UART TX/RX pair. The tester uses
two PIO state machines to provide the required 115200 8N1 UART on those exact
pins.

## WP mode jumper

Connect tester **D10/GPIO3** to a two-position jumper:

- **3V3 / HIGH:** WP-on final mode; the tester runs `wp-check`.
- **GND / LOW:** WP-off preprovision mode; the tester runs `protected-rw`.

D10 is sampled once when the tester boots. Reset or power-cycle the tester after
moving the jumper. An internal pull-up makes an absent jumper select the safer
WP-on final mode. The jumper selects the expected test only; it does not drive
or otherwise control the DUT EEPROM's WP pin.

## Build output

```sh
make -C challenges/misc/signal-box/firmware/tester
```

This produces one jumper-selectable image:

- `build/signal-box-tester.uf2`

It reuses the verified bare-metal boot chain under `../common/`.

## LED meanings

The tester uses its onboard active-low RGB LEDs:

- **Off:** waiting for a powered DUT.
- **Blue:** test in progress.
- **Green:** every automatic check passed.
- **Red:** at least one check failed or timed out.

The DUT's external D0 LED remains a manual visual check. It should visibly
blink during the blue test interval. Green means the D0 GPIO readback passed,
but cannot prove that the physical LED or its resistor emitted light.

## Tester diagnostic UART

The tester's native UART pins remain separate from the D4/D5 PIO link to the
DUT. Connect a 3.3 V USB-UART adapter as follows:

| Adapter | Tester |
|---|---|
| RX | D6/GPIO0/UART0 TX |
| TX | D7/GPIO1/UART0 RX (currently unused) |
| GND | GND |

Do not connect the adapter's VCC pin. Open the port at **115200 8N1**. The log
reports tester mode, DUT detection, raw averaged ADC code, prompt detection,
normal fixture result, protected/WP result, overall pass/fail, and DUT removal.
Logging occurs between DUT protocol phases so it does not overflow the PIO UART
receiver.

Example WP-on output:

```text
SIGNAL-BOX TESTER 0.3.0 MODE=WP_ON D10=HIGH
WAITING FOR DUT
DUT DETECTED
POWER ADC=0x0801
POWER PASS
DUT_UART PROMPT_PASS
RUN START
RUN PASS
WP_CHECK START
WP_CHECK PASS
OVERALL PASS
DUT REMOVED
```

## Pre-provisioning batch

1. Flash `signal-box-tester.uf2` onto the tester.
2. Tie tester D10 LOW and reset the tester; UART must report
   `MODE=WP_OFF D10=LOW`.
3. Leave the DUT EEPROM WP LOW.
4. Connect the six-pin fixture before powering or resetting the DUT.
5. Power the DUT by USB.
6. Wait for green or red and visually check its D0 LED.
7. Remove DUT power or unplug the fixture. The tester returns to the waiting
   state when the sensed DUT voltage disappears.

WP-off mode runs the normal fixture sequence followed by `protected-rw`. It
expects protected EEPROM writes and restoration to succeed.

## Final batch

1. Provision the EEPROM while DUT WP is LOW.
2. Tie DUT WP HIGH.
3. Tie tester D10 HIGH and reset the tester; UART must report
   `MODE=WP_ON D10=HIGH`.
4. Connect and power each DUT as above.

WP-on mode runs the normal fixture sequence followed by `wp-check`. Green
requires the protected write attempt to leave `0x1FF0-0x1FF7` unchanged.

## What green verifies

- DUT 3V3 test point is within the divider-derived acceptance window.
- Both UART test points carry bidirectional communication at 115200 8N1.
- SDA and SCL idle high, can be pulled low from the fixture, and reach the DUT.
- Both I2C test points show high and low levels while the DUT runs transactions.
- The EEPROM is the only responder in `0x50-0x57` and appears at `0x50`.
- Unprotected EEPROM write/read/restore succeeds.
- Protected write/read/restore succeeds in pre-provisioning mode, or WP blocks
  the write in final mode.
- DUT GPIO26 readback succeeds.

The 100 nF EEPROM decoupling capacitor still requires assembly inspection, and
the external LED remains the stated visual check.

## Handling units

Connect the fixture before powering the DUT so the tester receives the boot
banner. If a DUT was already powered, reset it after connecting. The tester
places UART and I2C fixture pins in high impedance whenever it is waiting or
showing a completed result. During an active test it checks DUT power every
10 ms and releases the pins if power disappears, minimizing UART back-powering
through an unpowered DUT's input protection.
