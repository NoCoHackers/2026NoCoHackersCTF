# XIAO RP2350 debug bring-up

Organizer-only port of the existing DUT acceptance firmware. **One wired unit
has passed both fixture WP modes and cold-start final acceptance.** Operator
results are recorded in the [handoff §13.9](../../../SIGNAL-BOX-HANDOFF.md).
Keep the known-good tester on its XIAO RP2040.
The default build includes no challenge flags, signing keys, encryption, OTP
programming, debug locking or anti-rollback operations. Separate opt-in lab
profiles now implement volatile debug controls; see
[recovery probes](../../security/RECOVERY-PROBES.md). They are not hardware-accepted
and their unsigned build outputs must not be flashed.

## Verified board mapping

| DUT connection | XIAO pad | RP2350 GPIO |
|---|---|---:|
| External LED through 330 ohms to GND | D0 | 26 |
| EEPROM SDA, external 4.7 kohm pull-up to DUT 3V3 | D4 | 6 (I2C1 SDA) |
| EEPROM SCL, external 4.7 kohm pull-up to DUT 3V3 | D5 | 7 (I2C1 SCL) |
| UART TX | D6 | 0 (UART0 TX) |
| UART RX | D7 | 1 (UART0 RX) |
| Onboard user LED, active-low yellow | D19 | 25 |

These challenge pads preserve the RP2040 DUT wiring and six-point fixture
interface. **Not every XIAO pad is identical:** RP2350 D3 is GPIO5, not RP2040
GPIO29. Do not flash the RP2040 tester image onto an RP2350. The RP2350 RGB
pixel uses GPIO22 with power enable GPIO23; this firmware does not drive it.

Sources:

- [Seeed getting-started guide](https://wiki.seeedstudio.com/getting-started-xiao-rp2350/)
  (GPIO25 yellow LED, active-low).
- [Pico SDK 2.2.0 board definition](https://github.com/raspberrypi/pico-sdk/blob/2.2.0/src/boards/include/boards/seeed_xiao_rp2350.h)
  (RP2350A, UART/I2C pins, flash clock divider 4; its 4 MiB flash default is
  overridden by this project).
- [Arduino-Pico XIAO variant](https://github.com/earlephilhower/arduino-pico/blob/master/variants/seeed_xiao_rp2350/pins_arduino.h)
  (D-pad to GPIO mapping).

The [Seeed SKU 102010550 datasheet, pages 3 and 5](https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/8932/102010550.pdf)
specifies **2 MB flash** and 520 kB SRAM. This build overrides both linker and
C-header flash sizes to **2 MiB (2097152 bytes)** rather than the SDK's 4 MiB
default. Picotool's separate content-based estimate also reports 2048 KiB.

The SDK selects `boot2_w25q080`; that names a compatible setup routine, not the
fitted part. No lid removal or visual chip identification is needed for the
current prototype. If future work needs part-specific commands, identify the
flash electronically first.

## Build

Requires CMake, GNU Make, the ARM bare-metal GCC toolchain (including C++ and
newlib), Python 3, and Pico SDK **2.2.0**. The SDK uses picotool for RP2350 image
metadata and UF2 packaging; it builds picotool automatically if not installed.
That host build additionally needs a native C++ compiler (Fedora: `gcc-c++`).
This does not use `../common/make_uf2.py`, the RP2040 linker, or its boot2.

From the repository root:

```sh
git clone --depth 1 --branch 2.2.0 \
  https://github.com/raspberrypi/pico-sdk.git /tmp/signal-box-pico-sdk-2.2.0
cmake -S challenges/misc/signal-box/firmware/debug/rp2350 \
  -B challenges/misc/signal-box/firmware/debug/build-rp2350 \
  -DPICO_SDK_PATH=/tmp/signal-box-pico-sdk-2.2.0 \
  -DCMAKE_BUILD_TYPE=MinSizeRel
cmake --build challenges/misc/signal-box/firmware/debug/build-rp2350 --parallel 4
```

A missing TinyUSB submodule warning is harmless here: both SDK USB and UART
stdio are disabled. The existing direct-register UART console is the only
console; there is no USB serial device.

If a native C++ compiler is unavailable, an alternative is Raspberry Pi's
[prebuilt picotool 2.1.1](https://github.com/raspberrypi/pico-sdk-tools/releases/tag/v2.1.1-3).
Extract the archive for your host outside the repo and add
`-Dpicotool_DIR=/path/to/extracted/picotool` to the configure command (the
directory containing `picotoolConfig.cmake`). This is how this port was
build-checked locally; no system packages were installed.

Output:

```text
challenges/misc/signal-box/firmware/debug/build-rp2350/signal-box-debug-rp2350.uf2
```

Build outputs are ignored. The RP2040 debug and tester builds remain separate:

```sh
make -C challenges/misc/signal-box/firmware/debug PICO_SDK_PATH=/tmp/signal-box-pico-sdk-2.2.0
make -C challenges/misc/signal-box/firmware/tester PICO_SDK_PATH=/tmp/signal-box-pico-sdk-2.2.0
```

## First unprovisioned board: flash, then cold boot

1. Disconnect the fixture and UART adapter. Hold **BOOT** while connecting the
   new XIAO by USB (or hold BOOT, press/release RESET, then release BOOT).
2. Copy **only the RP2350 UF2 above** to its BOOTSEL drive. This replaces any
   existing application in flash. Do not use the old RP2040 UF2.
3. Unplug USB completely. Connect a **3.3 V logic** USB-UART adapter:
   adapter RX to D6, adapter TX to D7, GND to GND, **VCC unconnected**.
   Open 115200 baud, 8N1, no flow control.
4. Power the XIAO by USB. The yellow LED makes three 100 ms blinks, then
   lights briefly. UART should show:

   ```text
   SIGNAL-BOX DEBUG 0.2.0-rp2350
   BOOT BOARD=XIAO_RP2350 CLOCK_INIT=PICO_SDK
   ```

   After non-writing preflight checks and command help, expect `debug> `.
   Type `help` to prove RX and echo, then `status`. On a bare board without
   EEPROM/pull-ups, failed EEPROM or bus preflight checks are expected.
   GPIO26 readback should pass even without an external LED attached.
5. Repeat a genuinely cold test with UART TX disconnected during power-off
   (or the adapter also unpowered) so possible adapter backfeed cannot mask
   initialization problems. Reconnect UART only after DUT power is present.
6. Power down before adding the EEPROM, pull-ups, capacitor, and D0 LED. With
   those connected, require the preflight EEPROM scan to be `01` (only 0x50).
   Send `led` and verify the actual external light pattern.
7. Use the existing RP2040 tester for `run` and both WP modes, following the
   [handoff](../../../SIGNAL-BOX-HANDOFF.md#133-tester-hardware--one-spare-xiao-rp2040).
   The tester is powered first; **never join the DUT and tester 3V3 rails**.
   Disconnect the standalone UART adapter before attaching the tester so
   two transmitters do not contend on DUT RX. A manual `run` without the
   tester's passive-bus drive will fail the two input-window tests normally.

The startup preflight does not write EEPROM. `run`, `eeprom`, `protected-rw`,
and `wp-check` do attempt writes; keep stable power until restoration results
print. Both manufacturing reservations remain unchanged: `0x0ff0-0x0ff7` and
`0x1ff0-0x1ff7`. See the [shared acceptance procedures](../README.md).

## Port differences and limits

- Pico SDK provides RP2350 Cortex-M33 Secure-state startup, image definition,
  linker layout, flash setup, clock initialization, and UF2 generation.
  **"ARM Secure" in picotool output means the CPU execution state, not signed
  secure boot or encrypted firmware.** This is an ordinary unsigned XIP image.
- `SYS_CLK_HZ=125000000` deliberately retains the existing UART divisors and
  100 kHz I2C timing. SDK startup initializes all tick generators at 1 MHz.
- RP2350 uses TIMER0, its own reset bit and generated register addresses,
  the RP2350 SIO function name, and explicitly clears pad isolation (`ISO`).
- The RP2040 custom clock path and its 3/1/2/3 narration remain unchanged.
  On RP2350 clocks/ticks are initialized **before main**, so the three yellow
  blinks prove arrival at main, not individual clock stages. SDK early clock
  waits are not instrumented or bounded by this port. No blinks/no banner can
  therefore mean an early boot/SDK clock failure; do not diagnose hardware
  from that observation alone. Repeating eight blinks means runtime-reset
  release failed after reaching main.
- UART fixture commands, result labels (including `LED_GPIO26`), CRLF handling,
  and EEPROM write/read/restore code are shared with the RP2040 build.
- Operator bench results confirm UART communication, visual external LED
  activity, standalone EEPROM tests, both tester WP workflows, and cold-start
  final acceptance on one wired unit. Independently measured UART/I2C waveforms,
  optical byte decoding, and induced WP-failure recovery remain unverified.
  Repeat acceptance on every assembled unit; compilation or one unit's pass
  does not accept the batch.

Do not program OTP, enable secure boot, or deploy the opt-in security profiles
on these boards yet. The ordinary electrical bring-up procedure above is only
for unprovisioned units. Signed/encrypted SRAM boot, locked debug, organizer
recovery and adversarial raw-flash readback remain separate hardware gates.
The offline lab profile and backup preparation workflow is documented in
[RECOVERY-PROBES.md](../../security/RECOVERY-PROBES.md).
