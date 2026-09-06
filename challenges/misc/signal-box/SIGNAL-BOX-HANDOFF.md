# SIGNAL-BOX HANDOFF — implementation notes & gotchas for the rewrite

> **CURRENT AGENT: START WITH SECTION 13.** It records the firmware and fixture
> that now exist, the verified wiring and operating procedures, the RP2350
> production-target decision in §13.7, and the exact resume point in §13.8.
> Sections 2–11 remain the RP2040 development ground truth; section 12 is the
> remaining production-challenge roadmap.

Written after bring-up (Milestone 1) completed. The prior implementation lived in
`challenges/misc/signal-box/` and was deliberately deleted after this document
was written; everything needed to rebuild it — and every trap that was stepped
in — is captured here. The challenge *design* (five flags, EEPROM map, optical
protocol, provisioning workflow) still lives in the original hardware handoff:
`~/Downloads/xiao_rp2040_hardware_ctf_software_handoff.md` — read it first; this
document covers what that one could not: the RP2040 facts, the boot chain, and
the failure modes.

**Checkpoint update:** the replacement DUT debug firmware and a second-XIAO
production tester now exist under `firmware/`; see section 13. EEPROM
provisioning, participant firmware, flags/manifests, and capture-fixture solves
remain unbuilt. Thirty Seeed RP2350 boards have been ordered: RP2040 XIAOs stay
the development platform, but the event DUT will use RP2350; see §13.7.

**Tally of the bring-up saga: 6 firmware bugs, 0 hardware faults, 1 bad
instrument (a "multimeter" that was an active load). No EEPROM, XIAO, resistor,
breadboard, or wire was ever actually broken.**

---

## 1. Mission

Bare-metal firmware for the "OTSC-86" hardware CTF unit: RP2040 XIAOs are the
current development platform, while the final event units will use newly
ordered Seeed RP2350 boards (exact SKU/pinout to verify on arrival) with the
Microchip 24FC64F EEPROM. Five flags cover UART discovery, console enumeration,
I2C identification, EEPROM extraction, and the optical OOK LED. Design per the
Downloads handoff, as amended by the production-target decision in §13.7. Repo
integration plan (section 12): `misc` category, `x-noco.kind: static`, five
scored manifests, capture-fixture solves for CI.

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

## 13. Current checkpoint — DUT debug firmware and XIAO tester built

This section is the restart point after the diagnostic/manufacturing work. The
code is organizer-only and contains no challenge flags. It is not participant
firmware.

### 13.1 Source layout and builds

```text
firmware/
  common/   shared boot2, startup, linker, register helpers, UF2 packager
  debug/    firmware flashed onto each DUT for electrical acceptance
  tester/   firmware flashed onto one spare XIAO used as the fixture
```

Both builds are standalone bare-metal `arm-none-eabi` builds. They use only the
generated RP2040 register headers from `PICO_SDK_PATH`; no Pico SDK runtime is
linked.

```sh
make -C challenges/misc/signal-box/firmware/debug
make -C challenges/misc/signal-box/firmware/tester
```

Current outputs:

```text
firmware/debug/build/signal-box-debug.uf2
firmware/tester/build/signal-box-tester.uf2
```

Both builds pass with `arm-none-eabi-gcc 15.2.0`, have no unresolved runtime or
division helpers, use the RP2040 UF2 family ID, and produce a boot2 checksum
matching the Pico SDK `pad_checksum -s 0xffffffff` implementation. The current
boot2 checksum is `0x15c0cc98`.

### 13.2 DUT debug firmware (`0.1.1`)

`firmware/debug/src/debug.c` preserves the cold-boot sequence and failure
markers from sections 6 and 9. UART is GPIO0/GPIO1 at 115200 8N1. All UART
newlines pass through one CRLF-normalizing function; do not reintroduce bare LF
writes because terminals display the following line at an increasing indent.

The onboard blue LED boot groups are:

```text
3  main entered / bank-0 released
1  XOSC stable
2  clk_ref on XOSC and TICK calibrated
3  PLL/sys/peripheral clocks configured
solid briefly  runtime peripherals released
```

Repeating 4/5/6/7/8 groups identify XOSC, clk_ref, PLL, clk_sys, or runtime-reset
failure. The external D0 LED makes one very short pulse during the automatic
GPIO26 preflight. That pulse by itself is normal: if no fixture command follows,
the DUT waits at `debug>`. Do not interpret the single D0 pulse as a dead XIAO.

UART commands:

```text
run            complete normal fixture sequence
status         non-destructive preflight status
bus            marked I2C traffic window
passive        three-second fixture-driven SDA/SCL input window
led            transmit optical fixture byte D2
eeprom         unprotected write/read/restore
protected-rw   protected write/read/restore; DUT WP must be LOW
wp-check       verify protected writes do not change data; DUT WP must be HIGH
help
```

Normal `run` verifies UART command receipt, SDA/SCL idle-high,
fixture-driven low levels, I2C initialization and traffic, a scan of
`0x50-0x57` with only `0x50` allowed to ACK, EEPROM read/ACK, unprotected
write/read/restore, GPIO26 readback, and an external LED pattern marker.

EEPROM manufacturing reservations:

```text
0x0ff0-0x0ff7  normal unprotected write/read/restore scratch
0x1ff0-0x1ff7  protected manufacturing-test record
```

Future provisioning code must reserve both ranges. Every write test backs up
the original bytes and attempts restoration even after a failed verification.
Do not remove power between a write-test start and its restore result.
`wp-check` deliberately attempts a protected write, verifies no change, and
attempts restoration if WP was unexpectedly low.

### 13.3 Tester hardware — one spare XIAO RP2040

The six DUT test points and tester header are in the same physical order:

| Header | DUT test point | Tester connection |
|---:|---|---|
| 1 | GND | tester GND |
| 2 | 3V3 | 10 kΩ to D1/GPIO27/ADC1; another 10 kΩ from D1 to GND |
| 3 | SDA | D2/GPIO28 |
| 4 | SCL | D3/GPIO29 |
| 5 | UART TX | D4/GPIO6, PIO UART RX |
| 6 | UART RX | D5/GPIO7, PIO UART TX |

The pin-2 network must measure approximately 10 kΩ from header pin 2 to tester
D1 and 20 kΩ from header pin 2 to GND with power off. An early fixture had the
divider on the wrong pin: the tester never detected DUT power, so it never sent
`run`; the DUT only made its normal one-time D0 preflight pulse. Correcting the
divider produced a green pass. This is the first check if that symptom returns.

Tester and DUT are powered by separate USB connections. **Never join their 3V3
rails.** Power the tester first, connect the keyed six-pin fixture, then power or
reset the DUT. The tester's fixture pins are high impedance while waiting and
after a result; active-test power is checked every 10 ms and pins are released
if DUT power disappears.

D4/D5 are not an RP2040 hardware-UART pair. The tester uses two PIO0 state
machines with the Pico example four-instruction 115200-baud UART programs. RX
occupies PIO instructions 0-3 and TX occupies 4-7. The fixed divider is
`135 + 162/256` at a 125 MHz system clock (~115200.7 baud). This was statically
reviewed and then worked in the assembled fixture.

D2/D3 remain high impedance except during the marked passive test, where the
tester drives LOW using output-enable and then releases. It never actively
drives an I2C high level.

### 13.4 Tester WP mode jumper — one unified image (`0.3.0`)

The old separate preprovision/final tester images were replaced by the single
`signal-box-tester.uf2`. A tester-local jumper on **D10/GPIO3** selects the
expected DUT WP state and is sampled once at tester boot:

```text
D10 -> 3V3   MODE=WP_ON   final acceptance; send wp-check
D10 -> GND   MODE=WP_OFF  preprovision acceptance; send protected-rw
D10 open     MODE=WP_ON   internal pull-up; safer default
```

Reset or power-cycle the tester after moving the jumper. The jumper does not
control or connect to the DUT EEPROM WP pin; it only selects which command and
result set the tester expects.

Manufacturing order:

1. DUT WP LOW, tester D10 LOW: run the normal tests plus `protected-rw`.
2. Provision the complete EEPROM while DUT WP remains LOW (tooling not built).
3. Tie DUT WP HIGH.
4. Tester D10 HIGH, reset tester: run normal tests plus `wp-check`.
5. Require tester green and visually confirm the DUT external D0 LED before
   enclosure assembly.

Tester onboard LED meanings:

```text
off    waiting for DUT voltage
blue   test running
green  every automatic check passed
red    failure or timeout
```

The external D0 LED and 330 Ω resistor remain a visual check. Green proves only
GPIO26 electrical readback, not emitted light. The EEPROM 100 nF decoupling
capacitor also remains an assembly-inspection item.

### 13.5 Tester ADC and diagnostic UART

The 10 kΩ/10 kΩ divider puts nominal DUT 3.3 V at about 1.65 V on tester ADC1.
The accepted ADC-code window is 1955-2140, corresponding to DUT 3.15-3.45 V
only when the tester 3V3/ADC reference is a calibrated 3.300 V. Measure the
known-good tester rail once and adjust `firmware/tester/src/config.h` if needed;
this is a relative screening measurement, not an independent precision
reference.

Tester D6/GPIO0 and D7/GPIO1 are free from the fixture and provide hardware
UART0 diagnostic logging at 115200 8N1:

```text
USB-UART RX  -> tester D6/GPIO0 TX
USB-UART TX  -> tester D7/GPIO1 RX (currently unused)
USB-UART GND -> tester GND
USB-UART VCC -> NOT CONNECTED
```

Example mode banners:

```text
SIGNAL-BOX TESTER 0.3.0 MODE=WP_ON D10=HIGH
SIGNAL-BOX TESTER 0.3.0 MODE=WP_OFF D10=LOW
```

The log reports DUT detection, averaged ADC code, DUT prompt detection, normal
run result, protected/WP result, overall result, and removal. Tester logging and
DUT logging both normalize newlines to CRLF.

### 13.6 Measurement lessons from this checkpoint

- A UT139C is a proper high-impedance DMM. Nevertheless, voltage readings on
  the tester's deliberately floating/high-impedance signal pins have no useful
  expected value; readings near 0.74 V there were ghost/leakage readings, not a
  valid logic-state test. Use powered DUT idle levels or continuity/resistance
  checks instead.
- With tester powered and no DUT, header pin 2 is pulled to 0 V by the divider;
  pins 3-6 are intentionally floating.
- If the DUT works standalone but gives one short external D0 pulse in the
  fixture, first verify header pin 2 -> D1 = 10 kΩ, pin 2 -> GND = 20 kΩ, and
  confirm the tester UART banner selected the intended D10 mode.
- The assembled corrected fixture produced green and visible D0 activity. The
  next operator should still validate both D10 positions and both protected
  workflows on real EEPROM data before running all units.

### 13.7 Production MCU decision — RP2350

Thirty Seeed RP2350 boards have been ordered. Continue rapid development and
fixture work with the known-good XIAO RP2040 boards, but **the final CTF DUT MCU
is RP2350**, not RP2040. Confirm the exact ordered Seeed board SKU, schematic,
pin compatibility, flash part, and exposed debug connections when the shipment
arrives; do not assume XIAO RP2040 register addresses, boot2, pin functions, or
UF2 details carry over.

The security goal is to stop a participant from solving firmware-resident flags
by reading the external flash and running `strings`. The intended RP2350 design
should evaluate and use its secure-boot, OTP-key, debug-lock, and encrypted-boot
features. Raspberry Pi's documented confidentiality path uses signed,
encrypted packaged-SRAM images that are decrypted into SRAM at boot; do not
assume ordinary external-flash XIP becomes confidential merely because secure
boot is enabled. Secure boot provides authenticity; encryption/OTP-backed key
handling provides flash confidentiality.

Production security requirements to design before burning any OTP:

1. Keep signing/encryption private keys outside the repository and establish a
   backed-up organizer key/restore procedure.
2. Build a signed and encrypted RP2350 image so raw QSPI reads expose ciphertext,
   while preserving the intended UART, EEPROM, and optical interfaces.
3. Decide which firmware flags are encrypted in the image and how they are
   materialized only at runtime. Never place their plaintext in an unencrypted
   flash section or external capture fixture.
4. Lock or disable SWD/debug access as appropriate for the participant threat
   model, while retaining a documented organizer recovery/reflash path.
5. Treat OTP programming, secure-boot enablement, key locks, and anti-rollback
   configuration as irreversible production operations. Develop and verify the
   complete sequence on sacrificial boards before applying it to the batch.
6. Test a raw-flash dump as an adversary and prove it does not disclose the
   firmware flags before accepting the security design.

The external 24FC64F remains intentionally participant-accessible for the
EEPROM challenge; its protected record and light XOR mechanic are separate from
RP2350 firmware confidentiality. The optical flag necessarily must be available
to the running MCU, making encrypted-at-rest firmware and locked debug paths
particularly important.

The existing RP2040 debug firmware, tester mechanics, EEPROM test reservations,
and UART result protocol remain the development baseline. Port the DUT side to
RP2350 after board arrival. The spare RP2040 tester can remain the fixture if
the final board preserves the six test-point electrical interface and 115200
UART protocol; otherwise revise only its physical mapping/protocol adapter.

### 13.8 Remaining work / exact resume point

No provisioning or participant challenge implementation has been written yet.
Resume at roadmap item 1 in section 12, with the RP2350 port/security design now
preceding production firmware:

1. Confirm the ordered Seeed RP2350 SKU and re-derive its pin map, flash layout,
   boot flow, register constants, UF2 packaging, and secure deployment process
   from vendor sources.
2. Prototype encrypted/signed boot, OTP key provisioning, debug locking, and
   recovery on sacrificial RP2350 boards; verify a raw flash dump reveals no
   firmware flag plaintext.
3. Build the 8 KiB EEPROM image generator and organizer writer/verifier while
   preserving `0x0ff0-0x0ff7` and `0x1ff0-0x1ff7`.
4. Exercise the unified tester in D10 LOW and D10 HIGH modes on real units,
   including induced WP failures and restore verification.
5. Port the debug/acceptance DUT firmware and its stable UART protocol to
   RP2350, then update the tester only if the six-pin electrical interface
   changes.
6. Implement the participant diagnostic shell, challenge flags, OOK protocol,
   five manifests, encoded capture fixtures, autosolves, and writeup.
7. Only after the production firmware exists, ensure the debug-only I2C scanner
   and manufacturing commands cannot appear in the shipped image.
