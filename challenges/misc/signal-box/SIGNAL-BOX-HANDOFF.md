# SIGNAL-BOX HANDOFF — implementation notes & gotchas for the rewrite

**Moving computers:** read [SIGNAL-BOX-MIGRATION.md](SIGNAL-BOX-MIGRATION.md) first.
It lists the uncommitted source, private state, exact tool and path requirements.
The verified USB archives do not include the successful hash-write run/latch;
no migration transfer or new-host verification has been performed yet.

> **CURRENT AGENT: START WITH SECTION 13.23.** Slot-0 hash write reports PASS;
> KEY_VALID offline model/spec reviewed, no activation writer/artifact yet. HOLD before KEY_VALID. ARM-only reuse
> with event-key publication is approved. Section 13.9 records the wired-unit
> fixture and cold-start acceptance. Section 13 records
> the existing RP2040 fixture, the production-security decision in §13.7,
> and the remaining roadmap in §13.8.
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
remain unbuilt. The ordered boards have arrived and are confirmed as **Seeed
XIAO RP2350**. RP2040 XIAOs remain the known-good development/tester platform;
the event DUT will use RP2350. The initial debug port is in §13.9.

**Tally of the bring-up saga: 6 firmware bugs, 0 hardware faults, 1 bad
instrument (a "multimeter" that was an active load). No EEPROM, XIAO, resistor,
breadboard, or wire was ever actually broken.**

---

## 1. Mission

Bare-metal firmware for the "OTSC-86" hardware CTF unit: RP2040 XIAOs are the
current known-good development platform, while the final event units will use
the newly arrived Seeed XIAO RP2350 boards (debug port in §13.9) with the
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

The thirty ordered boards have arrived; the operator confirms **Seeed XIAO
RP2350**. Continue fixture work with the known-good XIAO RP2040 boards, but
**the final CTF DUT MCU is RP2350**, not RP2040. The challenge-pin mapping and
initial debug build are recorded in §13.9. The fitted flash part, board revision,
schematic/debug-access details, and secure deployment design still need review
before production security work. Do not assume XIAO RP2040 register addresses,
boot2, pin functions, or UF2 details carry over.

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
7. **Approved post-event reuse policy:** use event-specific signing keys and
   deliberately publish the private/public keys after the event, with the
   encryption material, device salt mapping, and tooling needed by the supported
   reuse workflow. Never reuse these keys for other events or infrastructure.
   The operator accepts ARM-only reuse: RP2350 secure boot permanently disables
   RISC-V. OTP enforcement remains after publication; stock unsigned UF2s are
   not automatically usable. Preserve and test a BOOTSEL recovery/update path
   and the reuse kit under the final OTP policy before provisioning the batch.

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

1. Initial XIAO RP2350 debug bring-up is complete on one wired unit (§13.9):
   UART TX/RX, visual external LED, EEPROM, both tester WP modes, and cold-start
   final acceptance pass. Next confirm the fitted flash part, board revision,
   debug-access details, and secure deployment process before any irreversible
   operation.
2. Prototype encrypted/signed boot, OTP key provisioning, debug locking, and
   recovery on sacrificial RP2350 boards; verify a raw flash dump reveals no
   firmware flag plaintext.
3. Build the 8 KiB EEPROM image generator and organizer writer/verifier while
   preserving `0x0ff0-0x0ff7` and `0x1ff0-0x1ff7`.
4. Both tester WP modes now pass on the first RP2350 unit. Still exercise
   induced WP failures and restore verification before batch acceptance.
5. Repeat the proven debug/acceptance sequence on each assembled RP2350 unit
   (§13.9). Its stable UART protocol and six-pin mapping are preserved; the
   tester remains RP2040. One unit's pass does not accept the batch.
6. Implement the participant diagnostic shell, challenge flags, OOK protocol,
   five manifests, encoded capture fixtures, autosolves, and writeup.
7. Only after the production firmware exists, ensure the debug-only I2C scanner
   and manufacturing commands cannot appear in the shipped image.

### 13.9 XIAO RP2350 arrival — initial wired-unit bring-up complete

The operator confirms the shipment is **XIAO RP2350**. The initial organizer
DUT port is `firmware/debug/rp2350/`; read its [build and first-boot
instructions](firmware/debug/rp2350/README.md) before flashing. Operator bench
results now confirm UART, LEDs, standalone EEPROM tests, both fixture WP modes,
and a cold-cycle final-mode repeat on one wired unit below.
Do not program OTP or lock anything.

The used pads match the old DUT: D0=GPIO26, D4/D5=GPIO6/7 (I2C1),
D6/D7=GPIO0/1 (UART0). GPIO25 is an active-low **yellow** user LED rather than
blue. D3 does **not** match RP2040 (GPIO5 instead of GPIO29), so leave the
existing tester on its RP2040. The six test-point electrical interface and
UART fixture result labels are unchanged.

The RP2350 build uses Pico SDK **2.2.0**, `seeed_xiao_rp2350`, and
`rp2350-arm-s` startup/linker/image tooling. It does not reuse the RP2040 boot2
or UF2 packager. The application remains the shared `debug/src/debug.c` with
small platform branches for SIO function selection, pad isolation, TIMER0,
and startup narration. SDK runtime configures clocks/ticks before main;
`SYS_CLK_HZ=125000000` preserves the existing UART/I2C divisors. The old
RP2040 custom clock sequence is unchanged.

Build output:

```text
firmware/debug/build-rp2350/signal-box-debug-rp2350.uf2
```

Expect three yellow 100 ms blinks, a brief solid phase, then UART at 115200
8N1 with `SIGNAL-BOX DEBUG 0.2.0-rp2350`,
`BOOT BOARD=XIAO_RP2350 CLOCK_INIT=PICO_SDK`, and eventually `debug> `.
Unlike the RP2040 3/1/2/3 narration, these blinks occur **after SDK clocks are
initialized**; an early SDK clock hang has no stage-specific blink marker.
The standalone UART adapter must be disconnected before using the fixture to
avoid two transmitters driving DUT RX.

Verification completed on the build host:

- RP2350 CMake build and RP2040 debug/tester Makefile builds pass with
  `arm-none-eabi-gcc 15.2.0`; all three ELFs have no unresolved symbols.
- Official picotool **2.1.1** recognizes the RP2350 UF2 as `rp2350-arm-s`,
  board `seeed_xiao_rp2350`, SDK 2.2.0, with an image-definition block.
  SDK UF2 output contains ARM Secure family `0xe48bff59` plus its RP2350
  compatibility block; the RP2040 images retain `0xe48bff56`.
- Static review confirms the 125 MHz clock definition reaches SDK compilation,
  PLL divisors remain 6/2, TIMER0 gets a 1 MHz tick, pad isolation is released,
  and fixture commands/EEPROM restore paths remain shared.
- The RP2040 boot2 checksum remains `0x15c0cc98`.

"ARM Secure" here means Cortex-M33 execution state, **not enabled secure boot
or confidentiality**. The image is unsigned, unencrypted XIP with no security
provisioning operations. This does not satisfy §13.7's production requirements.

Operator-reported bench checkpoint with `0.2.0-rp2350`:

- Bare board showed the UART banner, three yellow boot blinks, and
  `PREFLIGHT_LED_GPIO26 PASS`; typed `help` returned the command list, proving
  UART RX as well as TX. Bare-board I2C failures were expected without wiring.
- The apparent carrier-attached boot failure was resolved by correcting the
  operator's pinout/wiring. No firmware change was needed. Do not record this
  as a flash, EEPROM, or MCU defect.
- `eeprom`: `EEPROM_WRITE`, `EEPROM_RESTORE`, and `EEPROM_RW_RESTORE` all PASS
  at scratch address `0x0ff0`, length 8.
- `protected-rw`: `PROTECTED_WRITE`, `PROTECTED_RESTORE`, and
  `PROTECTED_RW_RESTORE` all PASS at `0x1ff0`, length 8, in the WP LOW workflow.
- `wp-check`: `EEPROM_WP_HIGH`, `PROTECTED_RESTORE`, and `WP_CHECK` all PASS
  at `0x1ff0`, length 8, after the WP HIGH step. Protected writes were blocked.

- `led`: the operator visually confirmed external D0 LED activity. This is a
  visual light-output check, not an independently decoded optical capture.
- Existing RP2040 tester `0.3.0`, `MODE=WP_ON D10=HIGH`: DUT detection,
  `POWER ADC=0x07FC`, `POWER PASS`, `DUT_UART PROMPT_PASS`, `RUN PASS`,
  `WP_CHECK PASS`, and `OVERALL PASS`. The RP2350 DUT therefore passes the
  complete automatic final-mode fixture sequence without tester changes.

- Existing RP2040 tester `0.3.0`, `MODE=WP_OFF D10=LOW`: DUT detection,
  `POWER ADC=0x07F7`, `POWER PASS`, `DUT_UART PROMPT_PASS`, `RUN PASS`,
  `PROTECTED_RW PASS`, and `OVERALL PASS`. Both automatic fixture WP modes
  now pass on the RP2350 DUT without tester changes.

- Cold-start final-mode repeat, following the full power-disconnect procedure:
  tester `0.3.0`, `MODE=WP_ON D10=HIGH`, `POWER ADC=0x07FB`, `POWER PASS`,
  `DUT_UART PROMPT_PASS`, `RUN PASS`, `WP_CHECK PASS`, and `OVERALL PASS`.
  The unit is back in the WP HIGH workflow.

Initial RP2350 debug bring-up is complete on this wired unit. These operator
results do not establish batch acceptance, independently measured UART/I2C
waveforms, optical byte decoding, or successful induced-failure recovery.
Production firmware, EEPROM provisioning, and security work remain unbuilt.

**Exact next action:** plan the RP2350 signed/encrypted-boot and organizer
recovery prototype in §13.7. Confirm the fitted flash part, board revision, and
debug-access details; establish backed-up off-repo keys and a staged procedure
for a sacrificial board before any OTP write or permanent lock. Keep the known-
good bring-up unit and the batch unlocked while that design is validated.

### 13.10 Offline security prototype and approved post-event reuse

The operator has a sacrificial board ready and explicitly accepts ARM-only
post-event reuse through event-specific key publication (§13.7). This approves
that lifecycle design, **not an OTP bit map or a permanent programming action**.

See [firmware/security/README.md](firmware/security/README.md) for the offline
build and the gates before provisioning. Added:

- `SIGNAL_BOX_RAM_PROTOTYPE=ON` on the existing RP2350 CMake build: builds the
  shared debug source as a `no_flash` SRAM payload with version
  `0.2.0-rp2350-ram-prototype`. Default XIP debug builds remain unchanged.
- `firmware/security/package_probe.py`: pins picotool **2.3.1**, requires a
  diagnostic SRAM ELF and owner-only off-repo key material, embeds/signs the
  encrypted payload, and converts it to a flash-addressed UF2. Validates ELF
  and UF2 layout, verifies the embedded signature, and checks the plaintext
  probe marker is absent even across UF2 block boundaries. Outputs go to a new
  private directory outside the repo. No key generation, device commands, or
  OTP JSON generation are implemented.
- 15 host regression tests covering malformed/non-RAM/non-probe inputs,
  in-repo keys/symlinks, key size/permissions, tool version, overwrite refusal,
  cross-block plaintext leakage, the 2 MiB flash boundary, signature failure,
  incomplete-output handling, and the offline command set.

A real SDK **2.2.0** RAM build and picotool **2.3.1** packaging pass with
throwaway lab keys. picotool reports a verified signature and flash-to-SRAM
load map. The diagnostic marker is absent from encrypted ELF/UF2 and
reconstructed flash bytes. Temporary lab files are under a private
`/tmp/signal-box-security-lab-*`; those keys are disposable and must **never**
be programmed into OTP or treated as backed-up event keys.

This proves offline packaging only. No encrypted image has been flashed or
booted; no OTP, debug restriction, anti-rollback setting, or security lock has
been changed. Signature verification uses the embedded public key, not a
board's OTP root. Marker absence does not prove confidentiality. All actual
production flags remain unimplemented.

Read-only sacrificial-board identification is now complete: USB serial
`9423D016AADE5950`, RP2350A **A4**, QFN60, ROM gitrev `0xa8bfe860`. Secure boot
is off, both debug modes are enabled, and no signing-key slot is marked valid
or invalid. Existing OTP page locks are not all zero; preserve them. Full
baseline and remaining checks: [firmware/security/SACRIFICIAL-BOARD.md](firmware/security/SACRIFICIAL-BOARD.md).
The operator supplied the [Seeed SKU 102010550 datasheet](https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/8932/102010550.pdf):
pages 3 and 5 explicitly specify **2 MB flash** for XIAO RP2350. Picotool's
2048 KiB estimate agrees but remains a content heuristic. The build now sets
both linker and C-header flash capacity to **2 MiB**, and UF2 validation rejects
blocks beyond that boundary, overriding the SDK's conflicting 4 MiB default.
The flash chip is under a lid; no lid removal or visual part identification is
required for this prototype. No key-storage contents were dumped.

Persistent sacrificial keys now exist at
`~/.local/share/noco-ctf-2026/keys/sacrificial-9423D016AADE5950/` (directory 0700,
files 0600). The eight-file bundle contains private/public signing keys, exact
AES share, device salt, diagnostic RAM ELF, metadata, README, and integrity
manifest. Real signed/encrypted packaging with these keys passes. These are
separate from disposable /tmp keys and are **not production/event credentials**.

The operator has Bitwarden without attachments and chose an encrypted USB
archive with its passphrase stored in Bitwarden. With explicit authorization,
the Survivor 3.0 USB (serial `070849E1D3A07968`) was reformatted GPT/exFAT as
`NOCO_BACKUP`, UUID `FFEB-102B`, mounted at `/run/media/bjames/NOCO_BACKUP`.
Write/read testing passed; the RP2350 was untouched. The encrypted archive
`noco2026-sacrificial-9423D016AADE5950-20260911T024539Z.tar.gz.gpg` is now present
on that USB (78240 bytes). After fresh-passphrase validation, the operator ran
`restore_sacrificial.py` and supplied the successful terminal transcript:

- GPG decrypted/authenticated the USB archive.
- All eight restored files matched the working bundle and passed integrity checks.
- Recovered keys rebuilt a signature-verified encrypted probe; plaintext marker absent.
- `RESTORE PASS`; private plaintext staging removed; no flash/OTP writes.

The helper reported receipt
`~/.local/share/noco-ctf-2026/recovery-verifications/20260911T031003.491333Z-9423D016AADE5950.json`.
This checkpoint uses the operator's terminal transcript, not an independent
re-read of that receipt. The 26 combined packaging/recovery unit tests also
pass. See [firmware/security/KEY-RECOVERY.md](firmware/security/KEY-RECOVERY.md).

The host-side backup/restore gate is complete. The exact control/data policy
proposal and its next approval/artifact gates are now in §13.11. Neither
`RESTORE PASS`, LGTM, nor permission to proceed with planning authorizes burning
OTP. Keep the known-good bring-up unit and batch unlocked.

### 13.11 OTP policy approved without spare-slot revocation — no programming

Two independent public-source research lanes checked key layout and debug/USB
recovery semantics. The consolidated proposal is
[firmware/security/PROVISIONING-PLAN.md](firmware/security/PROVISIONING-PLAN.md).
`firmware/security/otp_policy.py` exports its non-secret tables as review-only
JSON; it reads no keys/devices and is deliberately not a picotool load recipe.
The organizer approved the policy with unused-slot revocation removed. This is
policy approval, not authorization to skip artifact/backup gates or write OTP.

Fresh serial-selected preflight on **2026-09-11 03:26 UTC** confirmed A4,
ROM `0xa8bfe860`, disabled secure boot and enabled debug. All 34 physical policy
rows matched the baseline. All 64 physical rows in signing page 2 and 192 rows
in candidate pages 29–31 were zero. Only blankness counts were reported; no
key-storage values were saved or printed. No flash/OTP writes occurred.
Picotool raw-read options are order-sensitive: use `-c 1 -r -n`, and reject
unexpected/missing rows rather than silently accepting parser surprises.

Approved design's final raw control words (execution still subject to staged gates):

- CRIT1 `0x040–0x047`: `0x5` each, reached through signature-only `0x1` first.
- BOOT_FLAGS0 `0x048–0x04a`: `0x082000` each; close ROM UART/OTP boot, preserve
  USB MSD/PICOBOOT, flash boot and authenticated SRAM recovery.
- BOOT_FLAGS1 `0x04b–0x04d`: `0x1` each; use slot 0 only. Leave slots 1–3
  blank/inactive, with no KEY_INVALID bits programmed. Root-page write locks
  already prevent unauthorized enrollment and still prevent future key rotation.
- PAGE2_LOCK1 `0xf85` and PAGE1_LOCK1 `0xf83`: `0x151515` each, from `0x040404`.
- PAGE29/30/31_LOCK1 `0xfbb/0xfbd/0xfbf`: `0x3d3d3d` each.
- Preserve all LOCK0 rows, page 0, CRIT0, rollback counters and glitch-detector
  fuse settings for this first sacrificial policy; not a production fault-
  resistance attestation.

Important correction: OTP `DEBUG_DISABLE` defines the default, but trusted
Secure software can override it using runtime `OTP_DEBUGEN=0x10f` after a cold
reset. `DEBUGEN_LOCK` is resettable runtime state, not an OTP fuse. The event
image must keep debug overrides closed/locked; a private signed post-event
image can reopen SWD. This still needs hardware proof. RISC-V disable from
secure boot remains permanent. Never publish an event-key-signed unlocker early.

Key-data details are in the proposal: public hash is SHA256 of big-endian
X||Y without SEC1 prefix; digest bytes pack little-endian into 16 ECC rows.
AES-256 share words are interleaved. Picotool 2.3.1's FIB workaround uses pages
29–31, including full 24-bit physical complements, with salt at base+2. The
second research lane's README-derived next-page salt statement was superseded
by the first lane's direct source/decryptor verification. No invented padding
writes or combined generated OTP JSON should be applied.

The offline recovery/debug preparation and expanded backup helpers are now
implemented; see §13.12 for the exact pending operator action. Only after the
updated encrypted backup/restore and artifact review consider separately approved staged writes:
verified hash → validity → signed boot/recovery proof → debug/route proof →
root integrity locks → verified secret rows → secret-page locks → encrypted
boot and negative/recovery/reuse tests. No actual writer is implemented here.
The public source revision could not be matched to board ROM gitrev; do not
claim a full ROM audit or hardware security acceptance from this proposal.
Use the recorded serial for all device operations and repeat raw preflight
immediately before any approved write. The batch remains unlocked.

### 13.12 Recovery/debug images prepared — new USB backup/restore pending

Implemented the approved host-side preparation step; no device commands or OTP
writes were performed. [RECOVERY-PROBES.md](firmware/security/RECOVERY-PROBES.md)
contains the reproducible build, signing and backup commands.

Three opt-in SDK 2.2.0 ARM SRAM builds now exist under
`firmware/debug/build-rp2350-{recovery,debug-closed,debug-reopen}/`:

- Recovery and closed set DEBUGEN=0; reopen sets DEBUGEN=0x10f. All lock/read-check
  implemented bits and reject Non-secure OTP peripheral access. The earliest
  runtime initializer is retained and first in the actual ELF preinit table.
  Failure spins with interrupts disabled, before ordinary UART/application work.
- UART status reports only public runtime values, not claims of physical SWD
  denial. A profile-only `bootsel` command provides the warm ROM handoff test.
- Default RP2350 and RP2040 debug/tester builds remain independent and pass;
  default debug ELFs contain no new profile marker. Reopen needs an explicit
  private-artifact build acknowledgment; invalid/non-SRAM modes are rejected.

The public-source reviewer established that the default embedded decryptor
locks debug overrides before key use, but does not clear/check their inherited
values. Consequently reopen is **plaintext signed only** and needs a cold reset.
The encrypted path explicitly rejects reopen input. The installed picotool
executable contains the exact upstream default loader ELF; that provenance check
is not a complete executed-path/hardware audit. Application hooks run after
CRT setup and any decryptor. Hardware default/debug/warm-memory tests remain open.

`prepare_recovery.py` now makes a separate owner-only snapshot from the original
persistent sacrificial keys. `recovery_images.py` creates six signed UF2s (three
roles, separately sealed flash and SRAM variants) plus the signed encrypted
closed UF2. It validates embedded signer fingerprints against the backed-up key
pair, UF2 ranges/roles, signed load maps, vectors/entry/stack, and encrypted
canary absence. Flash variants clear SRAM then copy into it; direct SRAM variants
do not clear their own source. Never load a `-flash.elf` directly as a RAM image;
use reviewed UF2s for future approved device operations.

The **final prepared snapshot** is:

```text
~/.local/share/noco-ctf-2026/recovery-bundles/sacrificial-9423D016AADE5950-prepared-20260911T042403.044323Z/
```

All 37 files passed preparation and revalidation with the real sacrificial keys.
The original eight-file working bundle and old encrypted USB archive are
unchanged. An earlier preparation at `20260911T041835.535047Z` was preserved
privately but superseded by the final reviewed fail-stop build; use the final
path above, not a guessed/latest glob.

The snapshot includes source/sealed ELFs, seven UF2s and inspections, original
keys/data, original and expanded manifests, approved policy/frozen plan and
exact image/key/tool bindings. There is **no loadable OTP JSON or device writer**.
It is not a completed post-provisioning recovery kit.

Validation: **48 host unit tests PASS**; real picotool integration with disposable
keys prepared a 37-file archive, restored all files, reverified actual UF2
signatures and rebuilt all images without changing originals. All three profile
builds and three rejection gates pass, as do RP2040 debug/tester, default RP2350,
repository validation (4 bundles / 4 entries / 0 errors / 0 warnings), shell syntax
and whitespace checks. These are host checks, not physical security acceptance.

**Prepared snapshot backup command (completed in §13.13):**

```sh
bash challenges/misc/signal-box/firmware/security/backup_sacrificial.sh \
  "$HOME/.local/share/noco-ctf-2026/recovery-bundles/sacrificial-9423D016AADE5950-prepared-20260911T042403.044323Z"
```

Enter the Bitwarden-stored passphrase locally. The script prints the exact
`restore_sacrificial.py --prepared --bundle-dir ... <USB-archive>` command; run
it locally too. Require all **37 files** and all rebuilt images to pass, with
private staging removed. The helpers retain eight-file legacy restore support;
its earlier PASS is not evidence for the new snapshot. The expanded USB restore
was pending at preparation time and is now recorded separately in §13.13.

After the new restore passes, review exact staged write artifacts and proceed
only with separately approved device stages from PROVISIONING-PLAN.md. Preserve
serial selection and repeat preflight. No irreversible action is authorized by
this host preparation, and the known-good unit/batch remain unlocked.

### 13.13 Expanded USB restore passed — first hardware test awaits approval

Operator-supplied terminal output confirms GPG authentication/decryption, an
exact **37-file** match, successful rebuilding of six signed recovery/debug
images plus the encrypted closed probe, and removal of private restore staging.

```text
Archive:
/run/media/bjames/NOCO_BACKUP/noco2026-sacrificial-9423D016AADE5950-20260911T042729Z.tar.gz.gpg
Receipt:
~/.local/share/noco-ctf-2026/recovery-verifications/20260911T042845.174674Z-9423D016AADE5950.json
```

This verifies the final `prepared-20260911T042403.044323Z` snapshot, not the
superseded preparation. Evidence is the operator transcript; no receipt/private
file read was attempted. No artifact or policy change is implied by this
progress update. No flash/OTP operations occurred.

**First device stage (subsequently approved and written in §13.14):** on
serial **9423D016AADE5950**: confirm identity/state, save its complete 2 MiB flash
to private host storage, then load the snapshot's **signed plaintext
`recovery-flash.uf2`** and cold-test UART/LED behavior. Confirm the 3.3 V UART
connection before expecting a console result; leave adapter VCC disconnected.
This replaces application flash but must not program OTP, flash the encrypted
probe, run EEPROM write tests automatically, or touch the known-good DUT/batch.
Do not substitute the `-flash.elf` or unsigned CMake UF2 for the reviewed UF2.

Later stages still require exact reviewed write artifacts, fresh preflight,
separate approvals and hardware tests from PROVISIONING-PLAN.md. The restore
PASS completes the host backup gate; it does not authorize those stages.

### 13.14 Signed plaintext recovery flashed — cold-boot observation pending

The operator explicitly authorized the first device stage. Target was selected
by **9423D016AADE5950** throughout. Fresh checks reconfirmed RP2350A A4, ARM,
ROM `0xa8bfe860`, BOOTSEL, secure boot disabled and default debug enabled. All 34
raw policy rows matched the baseline; all 64 signing-page and 192 AES/salt-page
rows were physically blank. Snapshot contents, picotool executable hash, actual
UF2 signer, role and flash-to-SRAM load map were revalidated before writing.

A complete **2 MiB** flash backup was saved twice independently with picotool
`save -r 0x10000000 0x10200000 -v ... -t bin --ser ...`. Both saves passed device
verification, and the two files matched byte-for-byte. The duplicate read file
was removed after comparison; the original backup, logs and audit remain private:

```text
~/.local/share/noco-ctf-2026/device-backups/sacrificial-9423D016AADE5950-before-recovery-20260911T044241.489487Z/
  flash-before.bin
  flash-after-recovery.bin
  stage.json
  ...private verification logs...
```

A conservative check initially stopped after the first save because it expected
`Verified OK`. Pinned save source prints `  OK` after `Verifying`; its wording
was checked before proceeding. There were no flash writes before both backup
reads were verified. Do not bypass verification just to match the wrong phrase.

Loaded the **unchanged final snapshot's `recovery-flash.uf2`** using
`picotool load -v <UF2> --ser 9423D016AADE5950`. No `-x`, force, ignore-partitions,
erase-all or OTP options were used. Picotool load verification passed. A separate
full-flash save/readback verified all **61 UF2 blocks / 15,616 payload bytes**
(`0x10000000–0x10003d00`, end exclusive). Flash outside the four covered 4 KiB
erase sectors was unchanged. All 34 policy rows still matched afterward.

**Last observed state:** still BOOTSEL, secure boot=0, debug default unchanged.
The application has **not** been executed by this stage. No OTP data, validity,
critical flags or page-lock fuses were programmed. The encrypted and debug-reopen
images were not flashed; the known-good DUT and RP2040 tester were untouched.
The only enumerated serial port was a Flipper (`/dev/ttyACM0`); no assumption was
made that it was configured/connected as a DUT UART bridge, and it was not opened.

**Requested operator check (results now recorded in §13.15):** fully remove
power/backfeed, then power the
sacrificial board without holding BOOT. Observe the yellow LED startup blinks.
Connect/use a 3.3 V UART at 115200 8N1: DUT D6/GPIO0 TX → adapter RX;
D7/GPIO1 RX ← adapter TX; GND common; adapter VCC unconnected. Prevent adapter TX
or fixture power from backfeeding the DUT during the cold cycle.

Request the startup and/or `status` output and LED observations. Expect profile
`recovery`, DEBUGEN=0 and DEBUGEN_LOCK=0x10f; CRITICAL remains zero under the
unprovisioned baseline. Bare-board EEPROM/I2C preflight failures are expected if
no carrier is attached. Do not run `run`, `eeprom`, `protected-rw` or `wp-check`
automatically. At this checkpoint observations were pending; see §13.15 for the
operator response. Booting this signed image does **not** prove signature
enforcement or physical debug denial: those fuse policies are still disabled.
Do not proceed to OTP without exact write-artifact review and separate approval.

### 13.15 Operator-reported recovery boot and runtime readback PASS

In response to the requested cold-start check, the operator reported “LED looks
ok” and supplied this UART `status` evidence:

```text
SECURITY PROFILE=recovery
SECURITY CRITICAL=0x00000000 DEBUGEN=0x00000000 DEBUGEN_LOCK=0x0000010F
SECURITY runtime-readback=PASS physical-debug-test=REQUIRED
STATUS CLOCK_INIT=PICO_SDK SYS_HZ=125000000 TIMER=TIMER0
RESULT PREFLIGHT_LED_GPIO26 PASS
```

This confirms execution of the signed plaintext recovery image and the intended
runtime override/lock values. LED behavior is operator-reported; no independent
power-cycle instrumentation or physical SWD test was performed. CRITICAL=0 means
secure boot and the permanent debug-disable policy are still off. DEBUGEN=0 is
not physical debug denial under that baseline. No OTP writes occurred.

The same output reported I2C idle failure, scan map 0x00, EEPROM address/ACK
failures and last abort 0. These are expected without the EEPROM/carrier and do
not invalidate the boot result. If a carrier is attached, treat them as a wiring/
power/pull-up problem to investigate before any fixture or EEPROM write tests.
Do not claim this bare-board result as wired-fixture acceptance.

**Exact next proposed action:** obtain approval for a signed SRAM-only recovery
test using the already-backed-up `debug-closed-ram.uf2`. Its different role marker
(`debug-closed`, versus the installed flash image's `recovery`) is essential to
distinguish successful SRAM execution from a fallback flash boot. Validate its
signer and SRAM-only targets; do not use the clearing `-flash.elf`/UF2 as a RAM
image. The test must leave flash and OTP unchanged; verify flash preservation
and return to normal flash boot afterward.

The running application has no USB stdio/reboot interface. After approval,
request operator UART `bootsel` (or physical BOOTSEL entry), then identify the
same serial before any RAM load. No RAM load, reboot command, flash write,
private-file read or OTP operation was performed when recording this UART
response. Exact OTP write-artifact review and separate stage approval remain
mandatory before enrolling the trust root.

### 13.16 Unprovisioned flash/SRAM/flash recovery round trip PASS

The operator approved the RAM-only recovery test, entered UART `bootsel`, and
confirmed the drive reappeared. Serial-selected preflight reconfirmed A4/ARM,
ROM `0xa8bfe860`, secure boot=0 and default debug enabled. All 34 policy rows
matched; 256 candidate signing/AES/salt rows remained physically blank.
A verified full 2 MiB flash read matched the earlier recovery-flash checkpoint.

The final prepared snapshot's `debug-closed-ram.uf2` was revalidated against its
manifest, bound signer and pinned tool hash. Its 61 blocks occupy only
`0x20000000–0x20003d00` (end exclusive), with an in-place SRAM load map and no
whole-SRAM clear. Issued exactly `picotool load -v -x <RAM-UF2> --ser
9423D016AADE5950`: RAM readback verification passed and the execute request
returned exit 0. No offset, force, partition override, erase or OTP command was
used. No flash/OTP writes were requested.

Private baseline and stage journal:

```text
~/.local/share/noco-ctf-2026/device-backups/sacrificial-9423D016AADE5950-ram-recovery-20260911T163115.320929Z/
  flash-before-ram.bin
  flash-after-ram.bin
  flash-before.save-log.txt
  flash-after.save-log.txt
  ram-load-execute.log
  stage.json
```

The operator subsequently reported “Drive available”; the captured UART status
was supplied afterward, as recorded below. Re-selected the same serial and completed read-only
post-checks: a verified full 2 MiB read matches `flash-before-ram.bin`
byte-for-byte; all 34 policy rows match and all 256 candidate key rows remain
physically blank. Preservation checks PASS. Board identity, ROM and unprovisioned
security state are unchanged, and it remains in BOOTSEL. No additional RAM load,
reboot, flash write or OTP operation accompanied these checks.

The operator then supplied the captured `status`:

```text
SECURITY PROFILE=debug-closed
SECURITY CRITICAL=0x00000000 DEBUGEN=0x00000000 DEBUGEN_LOCK=0x0000010F
SECURITY runtime-readback=PASS physical-debug-test=REQUIRED
```

The distinct `debug-closed` marker, combined with the unchanged installed
`recovery` flash image, confirms SRAM execution rather than fallback to flash.
SRAM execution and preservation checks PASS. EEPROM/I2C failures in that trace
have the same bare-board caveat as §13.15. Recording the UART evidence involved
no additional device operation.

After the requested normal power cycle without BOOT, the operator supplied:

```text
SECURITY PROFILE=recovery
SECURITY CRITICAL=0x00000000 DEBUGEN=0x00000000 DEBUGEN_LOCK=0x0000010F
SECURITY runtime-readback=PASS physical-debug-test=REQUIRED
```

This confirms return from the volatile SRAM image to installed flash. The
unprovisioned round trip **flash recovery → SRAM debug-closed → flash recovery**
passes, with independently checked flash and OTP-baseline preservation. The
private journal records `UNPROVISIONED_RECOVERY_ROUND_TRIP_PASS`; the two execution
observations are operator UART transcripts, not host-side physical measurements.
The sacrificial board is now operator-reported running flash profile `recovery`.
No new device command or OTP operation accompanied recording this final result.

**Next action at this checkpoint (preparation completed in §13.17):** prepare
and review exact per-stage OTP write artifacts,
starting with signing-key hash data only, before requesting permission for any
irreversible write. No loadable OTP recipe/writer has yet been implemented.
Preserve slot-0-only activation with no revocations, the backed-up key material,
serial selection, raw preflight and staged order from PROVISIONING-PLAN.md.
Do not treat recovery success or prior test approvals as authorization to burn
OTP or install AES secrets. Repeat authenticated recovery and negative tests
under enforced trust before later secret provisioning. Signature enforcement,
physical debug denial/reopening and encrypted hardware boot remain untested;
CRITICAL=0 confirms their OTP security policy is still off.

### 13.17 Slot-0 hash artifact prepared/reviewed offline — backup/write gates remain

The operator authorized offline artifact preparation, **not OTP programming**.
Added `firmware/security/prepare_signing_hash.py`, its 15 host tests,
`check_signing_hash.py` and `SIGNING-HASH-STAGE.md`. The first stage deliberately
contains only the 32 SHA256(X_BE32 || Y_BE32) digest bytes for ECC input rows
`0x0080–0x008f`. No KEY_VALID/KEY_INVALID, CRIT, boot flag, lock, counter or AES/salt
writes are included. No executable device writer or loadable OTP JSON is emitted.

Prepared and separately rechecked the real persistent-key sidecar:

```text
~/.local/share/noco-ctf-2026/provisioning-artifacts/slot0-hash-9423D016AADE5950-prepared-20260911T173747.602106Z/
  slot0-hash.ecc.bin    # exactly 32 bytes; ECC16 input, NOT raw24 or firmware
  review.json          # exact expectations/bindings; NOT picotool JSON
  README.txt           # holds and verification warning
  SHA256SUMS
```

The four files are owner-only under a new private directory. Original eight-file
keys, the restored 37-file snapshot and the completed round-trip journal were
hashed before/after and remained byte-for-byte unchanged. Existing USB backups
were not modified. No secrets or row values were printed. Native picotool use
was file-only; there were no device, serial, flash, RAM-load, reboot or OTP-write
commands during preparation.

The CLI fixes the restored snapshot and completed recovery evidence, rechecks
original/snapshot key identity, actual stored image signatures and the pinned
tool hash, then reconstructs the full review record on validation. It checks
fresh-row raw24 expectations against an explicit-file picotool OTP simulation,
including zeros outside the target extent. The simulation files are temporary;
no whole-OTP binary is retained in the sidecar.

Validation/review:

- **63 host tests PASS**, including 15 new focused fixture tests.
- **Real-tool integration PASS** for slot-0 byte order/extent and all **65,536**
  ECC16 encodings. The first exhaustive fixture used numeric row 0, which maps
  to a named register; JSON object fields were misinterpreted and rejected.
  Corrected that synthetic fixture to an unnamed region `0x0100`, 2048 words per
  chunk. The actual slot-0 simulation passed from the outset. No device was used.
- Independent protocol and fail-closed code reviewers found no outstanding
  blocking/high/medium source findings. Workflow
  `8e456798-7bda-4b23-8085-6b5087eb75d4`; child runs
  `3164a8ef-992a-4ad6-ab99-b29c20634d5b` and
  `acfcf82d-7aa6-4294-a5e1-46a8f4dd2bc1`. Review was source-only; parent ran tests.
- Pinned picotool binary OTP load can print a mismatch yet exit 0; JSON OTP load
  skips that verification path. Future execution must require positive tool
  verification plus independent exact ECC/raw readbacks, never exit status alone.

**Next action at this checkpoint (support added in §13.18):** design/test an
explicit encrypted backup/restore format for these new artifacts without weakening the existing eight-/37-file
allowlists. The current four-file sidecar is **not covered** by the earlier USB
archive and cannot be passed to the existing key-bundle backup helper. If helper
source changes alter its bound producer hashes, prepare a new sidecar after
review and preserve this one as superseded; do not edit either verified input
bundle. Obtain an operator restore PASS before seeking hash-only write approval.

No live preflight or programming authorization is encoded by preparation.
Exact execution-path review, fresh serial/A4/ROM and raw baseline/physical-
blankness checks remain mandatory before any write. Hold after independently
verified hash data, before KEY_VALID. Keep spare slots blank/inactive with no
revocations; do not jump to activation, locks, AES or batch provisioning.

### 13.18 Hash-artifact backup support tested — operator encrypted restore pending

The operator authorized adding/testing host-side backup support, not device or
OTP operations. Added `restore_signing_hash.py`, `test_restore_signing_hash.py`,
`check_hash_backup.py` and `HASH-ARTIFACT-RECOVERY.md` under `firmware/security/`.
`backup_sacrificial.sh --hash-artifact <exact-sidecar>` explicitly selects the
new `slot0-hash-v1` profile. Default eight-/37-file validation is unchanged;
there is no auto-detection, merged allowlist or change to their validators.

The new encrypted archive contains **five flat regular files**: the unchanged
four-file sidecar plus `recovery-round-trip.json`, a copy of its bound journal.
The helper freezes and validates a private local copy before streaming to GPG;
only ciphertext reaches USB. It contains no private keys or flash dump, so keep
the old key archives. No artifact regeneration was needed: producer-source
bindings still pass for the exact §13.17 directory.

Restore authenticates through GPG before bounded extraction (256 KiB limits),
compares four artifact files, then verifies using the **restored** fifth journal,
preserved key pair and file-only picotool checks. It does not need the live
journal. After cleanup, it publishes a scoped receipt in
`~/.local/share/noco-ctf-2026/hash-artifact-verifications/`; that receipt explicitly
does not claim key-archive recovery, hardware acceptance or programming approval.

Review findings addressed:

- Atomic, no-clobber receipt publication follows write/flush/fsync of a private
  pending file. Directory-sync or final-status-output errors after publication
  report that a receipt exists rather than falsely claiming none was created.
  Failure/collision tests cover those paths. A FATAL always means stop.
- Archive publication uses `mv -nT`, so a destination directory appearing during
  passphrase entry cannot silently receive the temporary ciphertext.

Validation: **88 host tests PASS**; real local archive/stream/extract/compare,
restored-journal and ECC revalidation PASS; original artifact, eight-/37-file
bundles and journal unchanged; private integration staging removed. Real
`--list-files` output is exactly the five expected names. Repository validation
passes (4 bundles/4 entries, zero errors/warnings); shell syntax passes.
Source-only reviewers: workflow `642c78b0-5667-4f0b-93d7-e5e387e5e4fc`, runs
`c9df97f4-b7e7-41fd-9c35-09ec9047726f` and
`34e8eddf-16a0-4ba0-9845-3cd3482908f3`, with follow-up
`8486f8df-9b85-4268-b0d3-1a9ac01de16d`. Parent ran the tests and addressed the final
low-severity output-error edge with an injected-failure test.

**Requested operator action (completed in §13.19):** run in their own terminal:

```sh
bash challenges/misc/signal-box/firmware/security/backup_sacrificial.sh --hash-artifact \
  "$HOME/.local/share/noco-ctf-2026/provisioning-artifacts/slot0-hash-9423D016AADE5950-prepared-20260911T173747.602106Z"
```

Use the Bitwarden passphrase locally. Run the exact `restore_signing_hash.py`
command printed for the newly created archive. Request final PASS lines, never
the passphrase. Require exit zero and `HASH ARTIFACT RESTORE PASS` with no FATAL.
The local integration did **not** encrypt or read/write USB and does not satisfy
this operator gate. No new encrypted archive or operator restore receipt exists
from these tests; do not invent an archive timestamp or claim the gate passed.

After operator restore PASS, exact future writer/command review and separate
hash-data-only write approval plus fresh physical preflight remain required.
No live device, serial, RAM-load, flash, reboot or OTP operations occurred in
this support stage. The board remains last reported running flash `recovery`;
secure-boot/debug-disable fuse policies are still off.

### 13.19 Operator hash-artifact encrypted USB restore PASS

The operator supplied successful backup and restore transcripts for the exact
unchanged four-file sidecar from §13.17 and its bound recovery journal:

```text
Encrypted USB archive:
/run/media/bjames/NOCO_BACKUP/noco2026-sacrificial-9423D016AADE5950-slot0-hash-v1-20260912T155955Z.tar.gz.gpg
Operator-reported receipt:
~/.local/share/noco-ctf-2026/hash-artifact-verifications/20260912T160235.789837Z-9423D016AADE5950.json
```

GPG reported AES256.CFB decryption with one passphrase. The helper reported:

```text
PASS: four recovered artifact files match; the fifth file is their verified bound journal.
PASS: restored hash data rederived from preserved keys; exact scope and offline ECC checks passed.
HASH ARTIFACT RESTORE PASS. Private plaintext staging removed.
```

This completes the **operator hash-artifact backup/restore gate**, alongside the
previously completed key-backup gates. Evidence is the supplied terminal
transcript; the assistant did not open the receipt, archive or private inputs
when recording it. No new key-archive restore, device test or OTP operation is
implied. The receipt itself explicitly disclaims programming authorization.

An earlier multiline paste split the arguments and ran the default key-backup
mode, creating an additional archive ending `20260912T155834Z.tar.gz.gpg`. It
was not the hash-artifact archive and no restore PASS was reported for that
extra copy. Preserve it and the older verified archives; the subsequent
single-line command selected the correct five-file profile. Prefer single-line
commands or separate shell assignments for the next operator instructions.

**Next action at this checkpoint (completed in §13.20):** prepare/review the bounded hash-only execution procedure
or writer, without issuing live programming commands. Its scope must remain
32 ECC-input bytes at rows `0x0080–0x008f`, using the restored artifact, pinned
tool and exact serial. No executable device writer has yet been implemented.
Obtain separate explicit hash-data-only write approval after review, then repeat
fresh A4/ROM/serial, all raw policy and candidate-storage blankness preflight.
Require positive tool verification plus independent exact ECC/raw readbacks;
hold before KEY_VALID, all other controls/locks and AES. Backup success is not
permission to burn OTP. No OTP writes occurred in this checkpoint.

### 13.20 Guarded hash-only writer prepared/reviewed — no live use yet

The operator authorized preparation/review only. Added
`firmware/security/write_signing_hash.py`, `test_write_signing_hash.py`,
`check_hash_writer.py` and `HASH-WRITE-PROCEDURE.md`. Existing artifact producers,
key validators, the restored four-file artifact and its verified five-file USB
backup remain unchanged. No regeneration or repeat backup is required solely
for this separate writer implementation.

Supported modes are explicit: `--offline-check` (files only), `--preflight`
(separately authorized live reads), and `--program-hash-only` (separate irreversible
write approval, backup acknowledgment and all streams on a real local terminal).
Program mode also requires a typed public confirmation after initial preflight.
Do not feed it through a pipe, tool, argument, environment variable or simulated
terminal to bypass the operator confirmation boundary.

The writer permits only 32 ECC-input bytes at `0x0080–0x008f` on the fixed
A4/ROM/serial. It revalidates the restored artifact/key/tool binding, acquires a
nonblocking per-board lease, checks identity/34 raw policy rows/256 blank storage
rows, and verifies full flash against the tested recovery checkpoint. After
confirmation it repeats working-input and live checks. Before its single native
write it durably publishes an exclusive sticky attempt latch plus an armed,
explicitly uncertain checkpoint. No retry/override or next-stage activation exists.

Private live-run journals would live in
`~/.local/share/noco-ctf-2026/provisioning-attempts/`; the one-shot latch is
`slot0-hash-9423D016AADE5950.attempt.json`. No real run journal, latch or live flash
snapshot was created by this preparation. A stale final check or failed write
must not trigger automatic retry or latch removal.

Independent review findings fixed and regression-tested:

- `--ser SERIAL` must precede OTP `get`'s repeatable row selectors; retain
  `-c 1 -r -n` first. Trailing device options can otherwise become selectors.
- Reject native stdout warnings/errors even when identity fields or values look
  valid. Positive binary-load `Verified OK` is required, not exit zero alone.
- Sync the new state-root parent and run-directory entry before native access;
  durable latch/armed state precedes the irreversible call.
- Seal validated executable **and** exact-size payload copies in Linux memfds.
  The child executes/reads inherited `/proc/self/fd` handles, not mutable paths.
  There is no insecure fallback if host memfd execution/sealing is unavailable.
- Carry the BOOTTIME deadline into transport and recheck after sealing, just
  before spawn. Machine suspend expires it; scheduling/USB gaps remain inherent.
- `otp get -e` is raw-page reading plus host parity checking, not another ROM
  ECC read. The binary load's own verification uses the native ECC path. Check
  exact raw24 bits, the separate host-parity view, selected policy/lock rows,
  untouched spare/secret rows and full flash; hold before KEY_VALID.

Validation: **121 host/simulated-device tests PASS**. The real restored artifact
passed offline checks with both live entry points explicitly blocked; all input
hashes were preserved. Actual pinned picotool also ran through a sealed executable
FD for `version` and an explicit-file OTP simulation, with exact slot-0 mapping
PASS. Those commands select no-device operation. No physical BIN write, live
preflight, GPG operation or private receipt read occurred.

Review workflow `ad83cb50-8313-45fa-ad1e-df78eacda9aa`; original child runs
`302f56f5-2e7c-4011-8d6f-002f5fa46b51` and
`84bed00b-2674-4716-bb5d-30c0f2a2f654`; follow-ups
`85c6e567-ef01-4780-b850-a6c70ea4a53d` and
`a4b841ff-ec81-46db-b2c6-7d413090b6f7` closed all reported blockers. Reviews were
source-only; parent ran tests. Trusted host/runtime, working filesystem durability
and exclusive physical bench control remain assumptions. Public-source/board-ROM
byte correspondence and physical fuse behavior remain unverified.

**Next action at this checkpoint (completed in §13.21):** ask permission for live **read-only preflight**, then have
the operator enter UART `bootsel` and confirm the drive. Only after that permission
may the assistant run this single-line command:

```sh
python3 challenges/misc/signal-box/firmware/security/write_signing_hash.py --preflight
```

Do not run program mode or a direct `picotool otp load` as a continuation.
Read-only success still requires separate explicit hash-data-only write approval
and a new preflight in program mode. No KEY_VALID, other controls, locks, AES,
revocations or batch operations are authorized.

### 13.21 Authorized live read-only hash preflight — PASS, no OTP writes

The operator explicitly approved read-only preflight and then reported that the
BOOTSEL drive appeared without mounting it. Mounting is unnecessary: picotool
uses the USB interface directly. Ran only the reviewed writer's `--preflight`
mode, without program mode, backup acknowledgment or confirmation bypass.

The command exited 0 and reported **`READ_ONLY_PREFLIGHT_PASS`**. Its private run
journal and verified flash snapshot are under:

`~/.local/share/noco-ctf-2026/provisioning-attempts/slot0-hash-q5ytu_fj/`

The successful path verified:

- Fixed restored artifact, signing-key and pinned executable bindings.
- Serial `9423D016AADE5950`, RP2350 A4, ARM, ROM `a8bfe860`, BOOTSEL and
  unprovisioned secure-boot/debug defaults.
- All 34 individual raw policy rows match the baseline; all 256 candidate
  signing/secret-storage rows remain physically blank.
- A verified full 2 MiB flash save matches the completed recovery round-trip
  checkpoint; identity and raw policy/blankness checks pass again afterward.

These are live wrapper results, not simulated-device or operator-only evidence.
No OTP/flash writes, activation, locks, AES, revocations or reboot were requested.
Read-only mode creates its private audit files but no attempt latch. The DUT was
left in BOOTSEL; no filesystem mount was needed. No encrypted archive or private
restore receipt was opened. Frozen source bundles and the bound recovery journal
were not modified.

**Next action at this checkpoint (completed in §13.22):** obtain separate explicit approval for the irreversible
hash-data-only stage: exactly 32 ECC-input bytes / rows `0x0080–0x008f` on this
sacrificial serial. No write authorization has yet been given. Only afterward
provide the reviewed single-line program-mode command for the operator's real
local terminal. Program mode must repeat fresh checks and typed confirmation;
this read-only PASS is not a reusable write authorization or freshness token.
Never automate the confirmation or use a direct picotool command to bypass the
writer. Success must hold before KEY_VALID; no other stage or board is authorized.

### 13.22 Separately authorized hash-data-only write — operator-reported PASS

After the live read-only PASS, the operator explicitly approved the irreversible
32-byte / 16-row hash-only write on serial `9423D016AADE5950`. The assistant
provided the reviewed single-line command for the operator's own real terminal;
it did not execute program mode or automate confirmation. The operator supplied
this completed transcript:

```text
Target: 9423D016AADE5950, A4, ROM a8bfe860. IRREVERSIBLE HASH DATA ONLY.
32 bytes / 16 ECC rows 0x0080–0x008f; no KEY_VALID, other controls, locks or AES.
Public signing-key SHA256(X||Y): b8fbbab76f60c7226c7172025f325b3bcb19986df08ff177c605e0217abd80ce
Type exactly 'PROGRAM HASH ONLY 9423D016AADE5950' to request this one write: PROGRAM HASH ONLY 9423D016AADE5950
HASH_DATA_VERIFIED_HOLD_BEFORE_KEY_VALID. Private journal: /home/bjames/.local/share/noco-ctf-2026/provisioning-attempts/slot0-hash-v292yeja
STOP here. No activation, debug policy, locks, AES, reboot or next-stage writes.
```

This is **operator-reported wrapper verification**, not a separate assistant
readback. No new device commands or private journal/receipt reads were performed
when recording it. The wrapper's successful path requires fresh repeated
preflight, positive binary-load verification, exact 16-row raw24 encoding and
host-parity checks, unchanged 34 policy rows, 48 remaining page-2 rows and 192
candidate secret-page rows still zero, and full 2 MiB flash preservation.

**The blank-candidate baseline is now historical.** Slot-0 hash rows
`0x0080–0x008f` now have their exact reviewed encodings; they are not expected
physically blank. Slot 0 remains inactive (`KEY_VALID=0`), secure boot/debug fuse
policy is unchanged, and slots 1–3/secret-storage rows remain blank. Hash data
alone does not enforce signatures or establish confidentiality/debug denial.

Preserve the private run above and the permanent per-board attempt latch:
`~/.local/share/noco-ctf-2026/provisioning-attempts/slot0-hash-9423D016AADE5950.attempt.json`.
Do not rerun the hash writer, delete/reset its latch, regenerate the frozen
sidecar to reflect device state, or reuse its all-blank preflight for the next
stage. The original bundles and recovery journal remain historical bound inputs.

**Next action at this checkpoint (offline model/spec completed in §13.23):** prepare/review a separate slot-0 KEY_VALID-only stage,
with the now-programmed hash checked exactly and all other policy/storage
invariants preserved. That preparation is not activation permission. No KEY_VALID,
signature enforcement, debug policy, page lock, AES/salt, revocation, reboot or
batch operation is authorized as a continuation. Every later irreversible stage
requires separate explicit approval and fresh physical preflight. Hold here.

### 13.23 KEY_VALID-only investigation/model reviewed — no live stage yet

The operator requested preparation/review, not activation. Added
`firmware/security/KEY-VALID-STAGE.md`, `key_valid_policy.py`,
`test_key_valid_policy.py` and `check_key_valid.py`. This is a **public review
model and stage contract**, not a private bound artifact or live writer. It does
not access the successful hash journal, original keys, private restore receipts,
board, or attempt latch. Original hash producers/writer and frozen inputs remain
unchanged. No KEY_VALID live preflight, programming, flash write or reboot ran.

Exact model: BOOT_FLAGS1 rows `0x004b`, `0x004c`, `0x004d`, each raw24 **0 → 1**.
The proposed transport is three padded little-endian raw words, **12 bytes**,
not ECC. It is modeled only in memory; no loadable BIN was retained. JSON output
is explicitly non-loadable review metadata, with authorization, live preflight,
private predecessor binding and artifact preparation all false.

The before/after projections each cover **290 exact raw rows**: 34 policy rows,
16 already-programmed hash rows and 240 blank other candidate rows. Exactly
three values change. The public hash expectation comes from the §13.22 operator
transcript; this is not a new private-key binding check or independent readback.
Every partial three-copy pattern is rejected, even when the majority is already1.

Important review findings:

- **Never use `0x010101`**: that would set slot0 validity AND invalidation, plus a
  DOUBLE_TAP_DELAY bit. Correct RBIT-3 encoding repeats raw1 across three rows.
- The second set copy establishes majority1. The transaction can tear; any partial
  state must stop without auto-retry/completion, revocation or latch deletion.
- Raw BIN verification still has picotool's exit-zero mismatch defect; the printed
  mismatch row is buffer-relative and padding is compared. Positive verification
  AND complete physical postchecks remain mandatory.
- Public comparison ROM parses supported signatures and rereads BOOT_FLAGS1/key
  hashes even with global signature enforcement off. **KEY_VALID is not inert until
  secure boot or cold reset.** Actual signature enforcement is a separate decision.
- Corrected a header-only inference: the comparison ROM ANDs the partition-table
  signature flag with secure mode; it does not independently enforce signatures
  with secure boot disabled on that path. Already-parsed/verified state can persist;
  a warm reboot and a true cold reset are not interchangeable acceptance evidence.

Public ROM inspection copies are at
`/tmp/public-rp2350-rom-c6cdb171-bbbru2rf/`, from commit
`c6cdb1711f32c3e34faaebd58618a6d096dbd52e`. Parent verified all ten downloaded
files' Git blob hashes against the pinned public API tree. Relevant source:
`varm_blocks.c:238–267,472–488,811,845–850,1112–1202`,
`varm_flash_boot.c:573–619`, `varm_boot_path.c:1356–1359`,
`varm_launch_image.c:408–422`, `varm_otp.c:342–346,402–408,429–478`,
`varm_apis.c:68–81`. This does **not** establish byte correspondence to the board's
`a8bfe860`, or on-board KEY_VALID behavior. No public query contained challenge
internals; only the public upstream repository/commit was fetched.

Validation: **133 host tests PASS**, including 12 new tests and 13,920 single-bit
mutation cases across both 290-row models. **8 SDK constant checks and 2 real
explicit-file picotool simulations PASS**; each simulation checks all4096 raw
rows for exact three-copy mapping and extent. Only `version` and explicit-input
`otp dump` were invoked; no-device mode, no actual BIN-load exercise. Temporary
simulation files were removed. No new backup/restore or predecessor validation
is claimed. Existing 121 tests continue to pass.

Review workflow `0f3b7087-b307-43e1-b89a-5f53443d1c92`, reviewer
`5ac13e02-dcd1-4df3-8e71-b7e9f72db60f`, follow-up
`3904d32c-39a1-424b-85b6-181bd1180535`: source-only review found no blocker in the
model/checker, and resolved the bounded public-ROM questions. Parent ran tests;
reviewer did not access hardware or private evidence. Actual-board behavior and
all remaining live-use gates are still unverified.

**Exact next action:** prepare a separate private activation artifact bound to
the restored keys/recovery/hash files and actual successful hash journal/latch;
then independently back up/restore it and implement/review a separate guarded
KEY_VALID-only writer. Follow `KEY-VALID-STAGE.md`, preserving the old hash
writer/latch and using the now-programmed hash, not blankness, as predecessor.
No activation is authorized. After those gates, obtain separate explicit
KEY_VALID-only approval and repeat fresh physical checks. Hold before all later
signature-enforcement/debug/root-protection/secret stages.
