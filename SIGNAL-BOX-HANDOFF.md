# SIGNAL-BOX HANDOFF — implementation notes & gotchas for the rewrite

Written after bring-up (Milestone 1) completed. The prior implementation lived in
`challenges/misc/signal-box/` and was deliberately deleted after this document
was written; everything needed to rebuild it — and every trap that was stepped
in — is captured here. The challenge *design* (five flags, EEPROM map, optical
protocol, provisioning workflow) still lives in the original hardware handoff:
`~/Downloads/xiao_rp2040_hardware_ctf_software_handoff.md` — read it first; this
document covers what that one could not: the RP2040 facts, the boot chain, and
the failure modes.

**Tally of the bring-up saga: 6 firmware bugs, 0 hardware faults, 1 bad
instrument (a "multimeter" that was an active load). No EEPROM, XIAO, resistor,
breadboard, or wire was ever actually broken.**

---

## 1. Mission

Bare-metal RP2040 firmware for the "OTSC-86" hardware CTF unit: Seeed XIAO
RP2040 + Microchip 24FC64F EEPROM, five flags (UART discovery, console
enumeration, I2C identification, EEPROM extraction, optical OOK LED). Design
per the Downloads handoff. Repo integration plan (section 12): `misc`
category, `x-noco.kind: static`, five scored manifests, capture-fixture
solves for CI.

## 2. Hardware facts (all verified against vendor sources — do not re-derive)

**XIAO RP2040 pin map** (from arduino-pico variant `seeed_xiao_rp2040/pins_arduino.h`
+ Seeed v1.3 schematic):

| XIAO pad | RP2040 GPIO | use in this challenge |
|---|---|---|
| D0 | GPIO26 | external OOK LED → 330R → LED → GND |
| D4 | GPIO6 | I2C1 SDA (FSEL 3) → 24FC64 pin 5, 4.7k pull-up to 3V3 |
| D5 | GPIO7 | I2C1 SCL (FSEL 3) → 24FC64 pin 6, 4.7k pull-up to 3V3 |
| D6 | GPIO0 | UART0 TX (FSEL 2), 115200 8N1 |
| D7 | GPIO1 | UART0 RX (FSEL 2) |

Onboard LEDs (Zephyr dts + schematic + Seeed wiki, all verified): discrete RGB
trio — **red=GPIO17, green=GPIO16, blue=GPIO25, all ACTIVE-LOW, always powered**
("direct"); the **blue GPIO25** is the user LED and was used as the boot-narration
channel. WS2812 is on **GPIO12** with power enable (RGB_EN) on **GPIO11** —
unrelated to the challenge; never drove it. Power LED is always-on green. The
XIAO v1.3 flash is a GD25Q16 (2 MiB). 3V3 comes from an onboard LDO from VBUS.

**24FC64F** (Microchip DS22154B, table 2-1, verified): DIP-8 pins 1-3 = A0-A1-A2
(all tied GND → address 0x50), 4 = VSS, 5 = SDA, 6 = SCL, 7 = WP, 8 = VCC.
8 KiB. WP high protects 0x1800-0x1FFF (upper quarter). **The chip ACKs its
address even when completely blank** — a blank EEPROM must still ACK at 0x50;
if it doesn't, the bus/driver is broken, not the chip.

**Reference sources used during bring-up** (all still fetchable):
- pico-sdk register headers (sparse clone; section 3) — the ground truth for
  every address/field below.
- Bootrom source: `github.com/raspberrypi/pico-bootrom-rp2040` (its
  `bootrom_main.c` comments document XOSC key semantics and inherited state).
- RP2040 datasheet: `datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf`
  (§2.16 XOSC, §2.15 clocks).
- XIAO RP2040 v1.3 schematic: `files.seeedstudio.com/wiki/XIAO-RP2040/res/Seeed-Studio-XIAO-RP2040-v1.3.pdf`
- 24FC64F datasheet: `ww1.microchip.com/downloads/en/devicedoc/22154b.pdf`

## 3. Getting the ground truth (do this before writing a single register)

```sh
git clone --depth 1 --filter=blob:none --sparse https://github.com/raspberrypi/pico-sdk /tmp/pico-sdk
cd /tmp/pico-sdk
git sparse-checkout set src/rp2040/hardware_regs src/rp2040/boot_stage2 \
    src/rp2_common/hardware_i2c src/rp2_common/hardware_clocks
```
`src/rp2040/hardware_regs/include/hardware/regs/*.h` defines every field's
offset, LSB/MSB, key values, and reset value. **RULE: no register constant is
ever hand-built or written from memory. Every constant in the rewrite must be
traceable to a named field in these headers.** (See section 7 — two of the six
bugs were hand-built constants whose "verification" checked values but not
field positions.)

## 4. Verified RP2040 fact tables (the rewrite's foundation)

### 4.1 Bases (addressmap.h)

XOSC 0x40024000 · CLOCKS 0x40008000 · RESETS 0x4000c000 · PSM 0x40010000 ·
IO_BANK0 0x40014000 · PADS_BANK0 0x4001c000 · PLL_SYS 0x40028000 · PLL_USB
0x4002c000 · UART0 0x40034000 · UART1 0x40038000 · I2C0 0x40044000 ·
I2C1 0x40048000 · TIMER 0x40054000 · WATCHDOG 0x40058000 · SIO 0xd0000000 ·
XIP_SSI 0x18000000 · VTOR (PPB) 0xe000ed08.

### 4.2 IO_BANK0 — **8-byte stride** (the #1 trap)

Each GPIO owns **8 bytes**: `GPIOn_CTRL = 0x04 + 8n`, then its `INTR` at
`0x08 + 8n`. Verified: GPIO0=0x04, GPIO1=0x0c, GPIO6=0x34, GPIO7=0x3c,
GPIO25=0xcc, GPIO26=0xd4. FUNCSEL is bits 0-4: XIP=0, SPI=1, **UART=2,
I2C=3**, PWM=4, **SIO=5**, PIO0=6, PIO1=7, NULL=0x1f.
GPIO0/1 FSEL 2 = UART0 TX/RX; GPIO6/7 FSEL 3 = I2C1 SDA/SCL.

### 4.3 PADS_BANK0 — 4-byte stride

`GPIOn pad = 0x04 + 4n` (GPIO26 = 0x6c ✓). Bits: SLEWFAST 0, SCHMITT 1,
PULL 2:3 (00 float, 01 down, 10 up), DRIVE 4:5 (2/4/8/12 mA), IE 6, OD 7.

### 4.4 RESETS — POR holds everything

`RESET` (offset 0x00, **1 = held, POR value 0x01ffffff**), `WDSEL` 0x04,
`RESET_DONE` 0x08. Bits: I2C1=4, IO_BANK0=5, PADS_BANK0=8, PLL_SYS=12,
SYSCFG=18, TIMER=21, UART0=22. **The bootrom only releases the QSPI/USB bits
it needs; bank 0 (IO_BANK0, PADS_BANK0) stays held until software releases
it. XOSC and the watchdog are NOT resettable (own enable registers).**

### 4.5 XOSC — **key halves** (the #5 trap)

CTRL (0x00): **FREQ_RANGE key 0xaa0 (1-15 MHz) occupies bits 0-11; ENABLE key
0xfab (disable 0xd1e) occupies bits 12-23.** Verified field-by-field:
ENABLE_BITS=0x00fff000, FREQ_RANGE_BITS=0x00000fff. Invalid key values are
silently ignored (the bootrom source says so explicitly). STATUS 0x04:
STABLE = bit 31, ENABLED = bit 12. STARTUP 0x0c: DELAY counts in **256-XOSC-
cycle units** (47 ≈ 1 ms at 12 MHz); POR STARTUP = 0. **The STABLE counter
counts XOSC cycles — a crystal that never starts counts nothing, so STABLE
never asserts and any unbounded wait hangs forever.** The bootrom's own start
sequence is: write ONLY the enable key (it never touches RANGE/STARTUP),
wait STABLE. ROSC at POR: 1.8-11.3 MHz (typ 6.5, per bootrom source comments).

### 4.6 WATCHDOG.TICK — the µs timer calibration (the #6 trap)

TICK at offset **0x2c**: CYCLES = bits 8:0 (**clk_ref cycles per microsecond**),
ENABLE = bit 9. **POR value 0x200 (default ~512 cycles).** The TIMER block's
microsecond tick is driven by this; the SDK/bootrom program CYCLES = 12 when
clk_ref is the 12 MHz XOSC. Nobody programs it for you on a cold boot. A
correct clock with a wrong TICK makes every timed delay run 512/clk_ref_MHz
times slow (42.7× at 12 MHz).

### 4.7 CLOCKS

CLK_REF_CTRL 0x30 (SRC bits 0:1; ROSC=0, XOSC=**2**), CLK_REF_DIV 0x34 (INT
bits 8+; undivided = 0x100), CLK_REF_SELECTED 0x38 (**bit n = source n**),
CLK_SYS_CTRL 0x3c (SRC bit 0: 0=clk_ref, 1=aux; AUXSRC bits 5:7, PLL_SYS=**0**),
CLK_SYS_DIV 0x40, CLK_SYS_SELECTED 0x44, CLK_PERI_CTRL 0x48 (AUXSRC bits 5:7,
CLK_SYS=0; **ENABLE bit 11 = 0x800**; no divider).

### 4.8 PLL_SYS

CS 0x00 (REFDIV bits 0:5, LOCK bit 31), PWR 0x04 (**PD bit 0, DSMPD bit 2 —
leave SET for integer mode, POSTDIVPD bit 3, VCOPD bit 5**), FBDIV_INT 0x08,
PRIM 0x0c (POSTDIV1 bits 16:18, POSTDIV2 bits 12:14). 125 MHz: REFDIV=1,
FBDIV=125 (VCO 1500 MHz), postdiv1=6, postdiv2=2. Sequence: reset+unreset
PLL_SYS, write CS/FBDIV while powered down, clear PD|VCOPD, wait LOCK, write
PRIM, clear POSTDIVPD.

### 4.9 UART0 (PL011)

DR 0x00, FR 0x18 (RXFE bit 4, TXFF bit 5), IBRD 0x24, FBRD 0x28, LCR_H 0x2c
(WLEN bits 5:6 = 3 for 8N1, FEN bit 4), CR 0x30 (UARTEN 0, TXE 8, RXE 9),
IMSC 0x38, ICR 0x44. At clk_peri = 125 MHz and 115200 8N1: **IBRD=67, FBRD=52**.

### 4.10 I2C1 (DW_apb_i2c)

CON 0x00 (MASTER bit 0, SPEED bits 1:2 with FAST=2, 10BIT bit 4, RESTART_EN
bit 5, SLAVE_DIS bit 6 → master config = 0x65), **TAR 0x04 (bits 9:0 hold the
plain 7-bit address; reset value 0x55; WRITABLE ONLY WHILE THE BLOCK IS
DISABLED)**, DATA_CMD 0x10 (DAT bits 7:0, CMD_READ bit 8, STOP bit 9, RESTART
bit 10), FS_SCL_HCNT 0x1c, FS_SCL_LCNT 0x20, RAW_INTR_STAT 0x34 (TX_ABRT bit
6), CLR_TX_ABRT 0x50, ENABLE 0x6c, STATUS 0x70 (MST_ACTIVE bit 5, TFE bit 2,
RFNE bit 3), SDA_HOLD 0x7c, TX_ABRT_SOURCE 0x80, FS_SPKLEN 0xa0.
100 kHz at ic_clk = 125 MHz (SDK shaping): **HCNT=500, LCNT=750, SPKLEN=46,
SDA_TX_HOLD=38**. TX FIFO depth 16; keep ≤8 queued. Abort recovery: hold+re-
unreset the whole block (RESETS bit 4) — the DW abort bit also waits for the
bus, so only a block reset escapes a stuck transaction. The SDK's per-
transaction pattern is `enable=0; tar=addr; enable=1` — **the TAR write is
dropped while enabled** (that reset-0x55 default is trap #2).

### 4.11 TIMER / SIO / misc

TIMER: TIMEHR 0x08 (reading it latches TIMELR 0x0c) — coherent 64-bit µs time.
SIO: GPIO_IN 0x04, GPIO_OUT 0x10, OUT_SET 0x14, OUT_CLR 0x18, OUT_XOR 0x1c,
GPIO_OE 0x20, OE_SET 0x24, OE_CLR 0x28. SET/CLR/XOR are write-only aliases
(reading returns 0; a read-modify-write of them is therefore still safe).
**libgcc on arm-none-eabi ships ARM-mode (not Thumb) division helpers —
`__aeabi_uidiv`/`uidivmod` produce "Unknown destination type (ARM/Thumb)"
link errors on Cortex-M0+. The firmware must contain NO division anywhere**
(trap #4; e.g. decimal printing was rewritten subtraction-based).

## 5. Boot chain (keep this structure — it survived everything)

### 5.1 Flash image layout + linker

```
0x10000000  boot2, EXACTLY 256 bytes (last 4 = bootrom CRC, patched post-objcopy)
0x10000100  vector table (16 core entries: SP=0x20042000, then reset+0x1),
            then .text/.rodata; .data load image; SRAM .data/.bss; stack top
```
Flash region 2 MiB (XIAO GD25Q16), SRAM 264 KiB. Startup: `cpsid i`, write
VTOR=0x10000100, copy .data, zero .bss, call main, park on return.

### 5.2 boot2 (generic 03h, adapted from pico-sdk boot_stage2 — BSD-3)

Position-independent, stack only, ≤252 bytes; the exit vectors through
0x10000100 (sets VTOR, loads SP+PC from the table). Key SSI constants
(verified): CTRLR0 = 0x001F0300 (std SPI, DFS_32=31, TMOD=EEPROM-read),
SPI_CTRLR0 = 0x03000218 (03h prefix, ADDR_L=6, INST_L=2, 1C1A), BAUDR=4,
CTRLR1=0, SSIENR toggled off→config→on. XIP then reads via 03h; at clk_sys
125 MHz that is 31.25 MHz — within W25Q/GD25Q spec.

### 5.3 Bootrom CRC (verified byte-for-byte vs pico-sdk `pad_checksum -s 0xffffffff`)

```python
def boot2_checksum(data252):
    rev = bytes(int(f"{b:08b}"[::-1], 2) for b in data252)
    crc = binascii.crc32(rev, 0) ^ 0xFFFFFFFF
    return int(f"{crc:032b}"[::-1], 2)   # bitrev32, store little-endian at 252
```

### 5.4 UF2 (verified vs microsoft/uf2 `uf2conv.py` + `uf2families.json`)

512-byte blocks; header: magicStart0 0x0A324655, magicStart1 0x9E5D5157,
flags 0x2000 (family present), targetAddr, payloadSize 256, blockNo, numBlocks,
**familyID 0xE48BFF56 in the fileSize slot**; 256-byte payload; zero pad;
magicEnd 0x0AB16F30. Targets 0x10000000+256n.

## 6. Boot sequence that finally worked, cold and warm

1. `gpio_bank0_enable()`: release IO_BANK0|PADS_BANK0 from the POR hold
   (wait RESET_DONE) — **before any GPIO register write** (trap #3). (On the
   production path this is folded into clock_init's hold/release; debug paths
   that touch GPIO before clocks must release the bank themselves.)
2. `clock_xosc_init()`: STARTUP=47; **CTRL = (0xfab<<12) | 0xaa0** (trap #5!);
   wait STABLE with a **bounded retry** (~30 ms ROSC crude-loop window, then
   disable (0xd1e<<12)|0xaa0 and re-kick). Count attempts; the debug build
   prints them (1 = healthy).
3. `clock_ref_init()`: clk_ref → XOSC (SRC=2, wait SELECTED bit 2); **then
   program WATCHDOG.TICK = (1<<9) | 12** (trap #6).
4. `clock_pll_init()`: 125 MHz PLL as in 4.8.
5. `clock_sys_init()`: clk_sys glitchless mux step (clear SRC → wait SELECTED
   bit0 → SRC=1|AUXSRC=0 → wait bit1); clk_peri = ENABLE|0<<5.
6. `clock_release_peripherals()`: unreset IO_BANK0/PADS_BANK0/UART0/I2C1/TIMER.
7. uart_init, i2c_init, gpio init; superloop (no interrupts anywhere — held
   up through everything).

**THE WARM/COLD RULE (read twice):** a warm boot after a BOOTSEL flash session
inherits a running XOSC, TICK=12, and released resets from the bootrom's USB
clock setup. A cold boot inherits NOTHING. Any behavior that differs between
warm and cold is state you forgot to initialize — and "works right after I
flash it" tests exactly the wrong path. **Make the cold power-cycle the FIRST
boot you test, from day one, before any feature work.**

## 7. The six bugs — actual wrong code, symptom, rule

**Bug 1 — IO_BANK0 stride (took days, killed UART-RX/I2C/LED):**
```c
#define IO_CTRL(n) (IO_BANK0_BASE + 0x04u + 4u * (n))   // WRONG: stride is 8
```
Every funcsel except GPIO0 (n=0, coincidence) landed on a neighbor's
register: UART RX dead forever, I2C peripheral never connected to its pads
("BUS STUCK LOW" on every scan), D0 LED never lit. Symptom that pointed at
hardware (two EEPROMs "identically bad") was 100% this. Right: `8u * (n)`.

**Bug 2 — IC_TAR written while enabled:**
```c
i2c_wait_idle(); io_write(I2C_TAR, addr);   // WRONG: dropped, TAR stays 0x55
```
Every probe addressed 0x55 while the EEPROM sat at 0x50. Right: the SDK's
`enable=0 → tar=addr → enable=1` dance around every transaction.

**Bug 3 — GPIO before releasing bank-0 resets:** POR holds everything
(0x1ffffff); the ROM never releases bank 0. All pre-release GPIO writes are
silently dropped — which is why the boot-marker LEDs "never blinked" and
every out-of-breadboard observation was meaningless. Right:
`gpio_bank0_enable()` before the first GPIO touch.

**Bug 4 — libgcc division on M0+:** the first-ever link of `uart_putdec`
pulled ARM-mode `__aeabi_uidiv` helpers. Right: no division anywhere;
subtraction-based decimal print.

**Bug 5 — XOSC key halves swapped (the whole "must reflash to boot" mystery):**
```c
io_write(XOSC_CTRL, (0xaa0u << 12) | 0xfabu);   // WRONG: both keys invalid, write is inert
```
Warm boots: ROM had left the XOSC running → STABLE already set → fine.
Cold boots: nothing ever enabled the crystal → startup counter counts zero
XOSC cycles → STABLE never asserts → hang forever (visible as "3 blinks,
then nothing" once the markers worked). Right: `(0xfabu << 12) | 0xaa0`.

**Bug 6 — WATCHDOG.TICK never programmed:** cold boot ran every timed
delay 42.7× slow (1.5 s solid phase took ~64 s; 1 Hz heartbeat was ~20 s on /
20 s off). Warm boots hid it: the ROM leaves TICK=12 behind. Right: program
`TICK = (1<<9)|12` right after clk_ref moves to the 12 MHz XOSC.

**Common thread of 1 and 5:** both were hand-assembled register constants
where the "verification against the SDK" confirmed base addresses, offsets,
and key *values* — but never field *positions*. Hence the rule in section 3:
derive constants from named fields, or don't write them.

## 8. The instrument bug (do not repeat this measurement)

The "multimeter" was an SMD tester whose **battery-test function is an
active ~1.4 kΩ load**, not a 10 MΩ voltmeter. On a 4.7 k-pulled node it
manufactured a steady **0.74 V "diode clamp"** reading, dragged both I2C
lines low on every probe touch, produced contradictory readings between
sessions, and led to a multi-day hunt for a "sink" that never existed (two
good EEPROMs were wrongly suspected; the decoupling cap was wrongly blamed).
Rules:
- Verify the instrument: a proper DMM reads 3.3 V on a pulled-up idle bus.
- **The firmware console is the primary instrument**: the passive-bus build
  (section 9) reports SDA/SCL levels live with picoamp-grade loading; a
  logic analyzer beats any probe on flaky contacts.
- A node whose level changes when you touch a probe to it is floating or
  the probe is loading it — check the probe before the circuit.

## 9. Diagnostic builds — keep all of them in the rewrite

- **Staged boot narration** (debug build): onboard blue LED blinks
  3 = main entry, +1 = XOSC stable, +2 = clk_ref on XOSC, +3 = PLL locked,
  solid ~1.5 s = fully up; then console banner with `XOSC attempts: N` and
  the I2C scan. A cold boot that stalls shows a truncated count that names
  the stage. This instrument is what finally localized bugs 5 and 6 — build
  it in the FIRST session, not the tenth.
- **Passive bus monitor** (build variant): D4/D5 as plain SIO inputs with
  pad pulls off, DW I2C never initialized; prints observed SDA/SCL H/L on
  change and every 5 s. SIO inputs see pads regardless of funcsel. Isolates
  wiring faults from firmware in seconds.
- **LED census** (build variant): endless slow tour — 3 blinks GPIO25
  (blue), 2 = GPIO16 (green), 1 = GPIO17 (red), 4 = GPIO26 (D0, external),
  GPIO11 held high as insurance. Polarity-agnostic (blinks alternate).
  Answers "which pin is the LED" empirically when documentation is muddy.
- Makefile pattern: `MAIN_SRC`/`UF2_OUT` selected by `DEBUG=1 / PASSIVE=1 /
  LEDCENSUS=1`; all build artifacts + generated `flags.h` gitignored.

## 10. Rewrite checklist (the process that would have prevented all of it)

1. Copy section 4's fact tables as `rp2040.h` — and re-verify each one
   against the headers per section 3, field by field, LSB by LSB.
2. Boot chain first (section 5), then clocks (section 6), then one
   peripheral at a time: UART TX → UART RX (type into it!) → LED → I2C probe
   (EEPROM ACK at 0x50 on a blank chip) — in that order, each proven before
   the next.
3. **Test cold power-cycle after every milestone**, with nothing connected
   but USB, judged by the boot narration. Never accept "works after flash".
4. Bounded waits + explicit recovery everywhere (I2C timeouts + block reset;
   XOSC retry). An unbounded wait is a future mystery.
5. No division, no 64-bit division, no libgcc surprises (section 4.11).
6. No hand-built register constants (sections 3, 7).
7. Console input (echo) tested explicitly — RX was silently dead for days
   because nobody ever typed.
8. Keep the second-opinion/debug narrative habit: when observations
   contradict, first suspect the instrument, then the instrumented
   firmware, and only then the hardware. The hardware was innocent for a
   week and it nearly got condemned twice.

## 11. Production notes carried over from bring-up

- Cold/warm boot: both paths are now identical because the firmware
  initializes everything itself (XOSC enable, TICK calibration, reset
  releases). Keep it that way; audit for other inherited state if warm
  behavior ever diverges (the full known list: XOSC running, TICK=12,
  released resets).
- UART adapter backfeed (TX idle-high into GPIO1's ESD diode holding 3V3)
  was THEORIZED during the saga but **never confirmed and turned out
  unnecessary** — cold boot works with everything connected once bugs 5/6
  are fixed. Optional hardening only: 1 k series resistors in both UART
  lines on the production protoboard also protects pads during hot-plug.
  Do not present it as a solved fact.
- WP handling for provisioning (breadboard: WP to GND; final assembly WP
  high) per the Downloads handoff §10. The debug strap-scan (0x50-0x57)
  is a bring-up tool only — challenge firmware must not ship a scanner.

## 12. Roadmap — not yet built (in order)

1. **Milestone 2 — EEPROM provisioning**: `provision/build_image.py` reads
   the five flags from the challenge manifests (the only place flag
   literals may live — repo rule), builds the full 8 KiB `OTSCCFG` image per
   handoff §7 (header magic + device ID + realistic decoy regions + the
   device-ID-keyed repeating-XOR `CRED` record in the WP quarter 0x1800);
   organizer-only provisioning firmware (same bare-metal stack) writes and
   verifies it with WP held low, prints PASS/FAIL.
2. **Milestone 3 — the diagnostic shell**: `help/status/diag/version/reboot`
   console in the OTSC-86 voice; Flag 1 in the boot banner, Flag 2 behind a
   hidden diag mechanic; NO dump commands, no flag text in error paths;
   flags injected at build time into a gitignored `flags.h` (never literals
   in the tree — `tools/validate.py` fails on any flag outside manifests).
3. **Milestone 5 — OOK transmitter**: 20 baud (50 ms bit), frame = 4×0x55
   preamble + 0xD5 sync + len + ASCII flag + XOR checksum, MSB-first,
   non-blocking off the µs timer in the same superloop; UART stays
   responsive during transmission.
4. **Milestone 6 + repo integration**: end-to-end solver walk; five scored
   manifests under `challenges/misc/signal-box/` (`kind: static`, no
   Dockerfile); each entry's `solution/solve-*.sh` decodes a committed
   capture fixture generated by the provisioning tooling (115200-baud TX
   sample capture → software-UART decode; EEPROM image → header/XOR decode;
   LED sample trace → OOK decode) — fixtures carry flags only in encoded
   form so the repo's flag-literal scan passes; `solution/writeup.md`;
   organizer README containing this document's war stories (battery-tester
   trap, warm/cold rule, passive-bus monitor) as the runbook; then
   `tools/validate.py` → `tools/test-challenge.sh` → PR per AGENTS.md.
5. Challenge constants stay centralized in `config.h` (pins, baud, I2C
   addr, EEPROM offsets, OOK timing, device strings) per handoff §15.
