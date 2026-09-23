# Signal Box debug firmware

Organizer-only bring-up firmware for the XIAO RP2040 and XIAO RP2350 signal-box
hardware. It exercises the challenge circuitry and emits machine-readable UART
markers for a production fixture. It contains no challenge flags and is not
participant firmware.

**New XIAO RP2350 boards:** use the separate [RP2350 build and first-boot
instructions](rp2350/README.md). One wired unit has passed both fixture WP modes
and cold-start final acceptance; see the handoff §13.9 for operator results.
The acceptance commands below are shared; the RP2040 build and boot narration
below do not apply to RP2350. Keep the tester on RP2040.

## RP2040 build and flash

The firmware is bare-metal but uses the generated RP2040 register headers from
a Pico SDK checkout as the source of truth. No Pico SDK libraries are linked.

```sh
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/raspberrypi/pico-sdk /tmp/pico-sdk
git -C /tmp/pico-sdk sparse-checkout set src/rp2040/hardware_regs
make -C challenges/misc/signal-box/firmware/debug
```

Set `PICO_SDK_PATH=/path/to/pico-sdk` if it is elsewhere. Hold BOOTSEL while
connecting USB, then copy `build/signal-box-debug.uf2` to the `RPI-RP2` volume.
Always perform the first acceptance run after a complete USB power disconnect,
not immediately after flashing.

Build outputs are ignored. `make clean` removes them.

## RP2040 boot narration

The onboard blue LED is active-low and reports progress before UART exists:

1. 3 blinks: C `main` entered and bank-0 GPIO resets were released.
2. 1 blink: XOSC became stable.
3. 2 blinks: `clk_ref` uses XOSC and the microsecond tick is calibrated.
4. 3 blinks: the 125 MHz PLL and system/peripheral clocks are configured.
5. Solid briefly: runtime peripheral resets were released.

A repeating four-blink group means XOSC failed after three bounded attempts.
Repeating groups of 5, 6, 7, or 8 identify `clk_ref`, PLL lock, `clk_sys`, or
runtime-reset failure respectively. On success the UART banner reports
`XOSC_ATTEMPTS`; a healthy board normally reports 1.

## Fixture connections

The fixture must connect independently to all six external test points. Do not
short UART TX to RX; the fixture receives on TX and sends commands on RX.

| Mystery test point | Fixture connection | Acceptance criterion |
|---|---|---|
| UART TX | 3.3 V UART receiver | Decodes the banner and result lines at 115200 8N1. |
| UART RX | 3.3 V UART transmitter | Sending `run` is accepted and produces `RESULT UART_RX PASS`. |
| I2C SDA | open-drain drive plus digital capture | Idle high; fixture-driven low is observed by the MCU; toggles during the marked I2C window; decoder sees address `0x50`. |
| I2C SCL | open-drain drive plus digital capture | Idle high; fixture-driven low is observed by the MCU; approximately 100 kHz clocks appear during the marked window. |
| 3V3 | voltage input/DMM | 3.15-3.45 V relative to the GND test point. |
| GND | fixture ground | Common reference and low-resistance continuity to USB ground. |

A photodiode or phototransistor aimed at the external D0 LED must also be part
of the fixture. During `FIXTURE LED START`, it must decode byte `0xD2`,
MSB-first, with 100 ms symbols. The three preceding on/off pulses are an
acquisition marker.

Use high-impedance capture inputs on SDA/SCL. During `FIXTURE PASSIVE START`,
the fixture must pull SDA low and release it, then pull SCL low and release it;
use open-drain outputs and never actively drive either line high. The firmware
must report `TP_SDA_INPUT PASS` and `TP_SCL_INPUT PASS`. In particular, do not
use the battery-test mode of an SMD tester; the instrument described in the
handoff loaded a 4.7 kΩ pull-up down to approximately 0.74 V.

## Running acceptance

Open the UART at 115200 8N1 and send:

```text
run
```

The command performs:

- UART RX command receipt and UART TX response;
- passive SDA/SCL idle-high check before I2C initialization;
- a three-second passive window in which fixture-driven lows prove both test
  points reach the MCU pads;
- a read-only scan of `0x50-0x57`, requiring `0x50` to be the only ACK;
- eight marked EEPROM reads for capture at the I2C test points;
- EEPROM ACK/read at address `0x50`;
- backup, test-pattern write, readback, restore, and final readback at `0x0FF0`;
- GPIO26 low/high input readback;
- the externally observed D0 LED pattern.

The padding range containing `0x0FF0-0x0FF7` must remain reserved for
manufacturing diagnostics. The firmware always attempts restoration after
a write attempt, even if verification fails. Do not remove power between
`INFO EEPROM scratch=...` and `RESULT EEPROM_RESTORE ...`.

## Protected-region manufacturing tests

These tests are deliberately excluded from `run`. Reserve `0x1FF0-0x1FF7` in
the provisioned EEPROM image as the protected manufacturing-test record.
Perform the following sequence on stable power:

1. Hold EEPROM WP LOW and run `protected-rw` before provisioning. Expect
   `PROTECTED_WRITE`, `PROTECTED_RESTORE`, and `PROTECTED_RW_RESTORE` to pass.
   This proves those upper-quarter memory cells can be programmed.
2. Provision the complete EEPROM image while WP remains LOW.
3. Tie WP HIGH as it will be in the finished unit.
4. Run `wp-check`. Expect `EEPROM_WP_HIGH`, `PROTECTED_RESTORE`, and `WP_CHECK`
   to pass. The command attempts to change the protected record and verifies
   that its bytes remain unchanged.

If WP is unexpectedly low during `wp-check`, the firmware reports
`EEPROM_WP_HIGH FAIL` and immediately attempts to restore the saved bytes. Do
not remove power until `PROTECTED_RESTORE` is printed. A failed WP check must
block enclosure assembly even when restoration succeeds.

A unit passes only when:

1. every emitted `RESULT` line says `PASS`;
2. the fixture validates all six test-point criteria in the table;
3. the optical fixture decodes `D2`; and
4. the same result is obtained after a cold USB power cycle.

The firmware prints `external-results-required=3` because 3V3/GND voltage, I2C
activity at the physical test points, and emitted light cannot be proven solely
from the MCU side of their connections.

## Additional commands

```text
status   repeat non-destructive preflight results
bus      emit the marked I2C transaction window
passive  monitor fixture-driven SDA/SCL for three seconds
led      emit the optical D2 fixture pattern
eeprom       test unprotected 0x0FF0-0x0FF7 with restore
protected-rw test protected 0x1FF0-0x1FF7; WP must be LOW
wp-check     verify protected writes are blocked; WP must be HIGH
help         list commands
```

## Limits of electrical diagnosis

Functional tests cover the EEPROM, address straps, pull-ups, UART/I2C routing,
external LED path, and exposed test-point continuity when paired with the
fixture. Stable I2C operation does not independently prove the value or
placement of the 100 nF decoupling capacitor; assembly inspection remains
required. `wp-check` verifies write protection behavior at the reserved test
record, while the fixture should also verify that EEPROM pin 7 is at 3.3 V
before enclosure assembly.
