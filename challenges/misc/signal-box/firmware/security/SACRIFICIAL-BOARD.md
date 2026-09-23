# Sacrificial XIAO RP2350 — baseline and first flash checkpoint

Operator attached the designated sacrificial board in BOOTSEL mode. The initial
identity/security baseline below was read using official picotool **2.3.1**,
without writes. Subsequently, the operator-approved signed plaintext recovery
UF2 was flashed and verified; see the checkpoint below. Later, the separately
authorized slot-0 hash-data-only write reported verified success in the operator's
transcript (handoff §13.22). **Hold before KEY_VALID; no permanent locks have been
written.** The baseline below is historical: rows `0x0080–0x008f` now contain their
reviewed hash encodings, not zeros. Preserve the hash-writer attempt latch; do not
rerun its original all-blank preflight as though the board were unprovisioned.

## Identity

| Field | Observed value |
|---|---|
| USB product | RP2350 Boot |
| VID:PID | `2e8a:000f` |
| USB serial | `9423D016AADE5950` |
| Chip ID | `0x9423d016aade5950` |
| Revision reported by picotool | **A4** |
| Package | QFN60 (RP2350A) |
| ROM git revision | `0xa8bfe860` |
| Current/default CPU | ARM |
| Available CPUs | ARM, RISC-V |
| Boot state | BOOTSEL |
| Flash devinfo | `0x0c00` |
| picotool flash-size estimate | 2048 KiB — matches board datasheet |
| Documented board flash capacity | **2 MB**, Seeed SKU 102010550 datasheet, pp. 3 and 5 |

Future device operations must select `--ser 9423D016AADE5950` and re-check
identity. USB address and Linux block-device names are transient, not identity.
The observed mount was `/run/media/bjames/RP2350` on `/dev/sdb1`.

`picotool info --debug` derives A4 from the ROM version byte. Its flash-size
field comes from `guess_flash_size()`, a flash-content repetition heuristic,
not a JEDEC/SFDP part identification. The operator supplied the
[Seeed SKU 102010550 datasheet](https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/8932/102010550.pdf):
page 3 says "2MB Flash" and page 5 lists "2MB Flash" for XIAO RP2350.
That is the capacity source, not the picotool heuristic. The RP2350 build and
UF2 validator now use **2 MiB** rather than the SDK's 4 MiB default.

The exact flash part and PCB revision remain uninspected; they are not blockers
for this offline prototype. Leave the lid intact. Use electronic identification
if later operations require part-specific flash commands. Debug-connector
access can be checked without requiring visual flash-chip identification.

## Effective security state

- `secure boot: 0`
- `debug enable: 1`
- `secure debug enable: 1`
- `CRIT0 = 0x000000`: neither CPU architecture disabled.
- `CRIT1 = 0x000000`: secure boot, secure-debug disable, all-debug disable,
  and glitch-detector enable are unset.
- `BOOT_FLAGS0 = 0x000000`: no BOOTSEL USB interface-disable or rollback-required
  bits set; OTP flash-devinfo override is not enabled.
- `BOOT_FLAGS1 = 0x000000`: no signing-key slots marked valid or invalid.

Selected OTP page-lock rows reported:

| Page | LOCK0 | LOCK1 |
|---:|---|---|
| 0 | `0x3f3f3f` | `0x151515` |
| 1 | `0x000000` | `0x040404` |
| 2 | `0x000000` | `0x040404` |
| 29 | `0x000000` | `0x000000` |
| 30 | `0x000000` | `0x000000` |
| 31 | `0x000000` | `0x000000` |

These are **observed values, not a programming recipe**. OTP is not globally
blank: existing page-0 and page-1/2 restrictions must be preserved and accounted
for. The initial query presented consolidated effective fields. A follow-up on
**2026-09-11 03:26 UTC** checked all 34 physical policy rows individually using
`otp get -c 1 -r -n` in that order and explicit row numbers. Every raw critical/
boot-flag copy and lock row matched this baseline.

The same serial-selected read-only follow-up checked all 64 physical rows in
signing page 2 and all 192 rows in candidate AES/salt pages 29–31: all were zero.
Only blankness counts were printed; no key-storage values were logged or saved.
Repeat these checks immediately before any approved programming; prior blankness
is not permission to overwrite newly occupied rows.

## Reproduce the bounded read-only checks

```sh
PICOTOOL=/path/to/picotool-2.3.1/picotool
"$PICOTOOL" info --debug --ser 9423D016AADE5950
"$PICOTOOL" otp get -n --ser 9423D016AADE5950 \
  CRIT0 CRIT1 BOOT_FLAGS0 BOOT_FLAGS1 \
  PAGE0_LOCK0 PAGE0_LOCK1 PAGE1_LOCK0 PAGE1_LOCK1 PAGE2_LOCK0 PAGE2_LOCK1 \
  PAGE29_LOCK0 PAGE29_LOCK1 PAGE30_LOCK0 PAGE30_LOCK1 PAGE31_LOCK0 PAGE31_LOCK1
```

The persistent sacrificial-key USB restore has now passed; see
[KEY-RECOVERY.md](KEY-RECOVERY.md). The revised policy is approved with unused-slot
revocation removed; see [PROVISIONING-PLAN.md](PROVISIONING-PLAN.md). This is not
programming authorization. Offline recovery/debug artifacts are now prepared;
see [RECOVERY-PROBES.md](RECOVERY-PROBES.md). The expanded encrypted USB restore
has passed per the operator transcript. Unprovisioned recovery tests now pass;
recovery under enforced trust, encrypted boot and physical debug tests remain
pending. The first signing-hash data artifact is prepared/reviewed offline; see
[SIGNING-HASH-STAGE.md](SIGNING-HASH-STAGE.md). No OTP stage is authorized.
**Do not provision from disposable
/tmp keys or load a combined example OTP JSON.**

## Approved plaintext recovery flash checkpoint

The final prepared snapshot's `recovery-flash.uf2` was loaded with verification,
without execution, after two matching, independently verified 2 MiB flash saves.
A full post-write readback matched all 61 UF2 blocks; bytes outside the four
covered 4 KiB erase sectors were unchanged. All 34 policy rows still matched.
Fresh pre-write checks also found the 256 candidate key-storage rows blank.

Private before/after images and audit:

```text
~/.local/share/noco-ctf-2026/device-backups/sacrificial-9423D016AADE5950-before-recovery-20260911T044241.489487Z/
```

The board was left in BOOTSEL after writing. In response to the subsequent
cold-start request, the operator reported normal LED behavior and UART status:
profile `recovery`, CRITICAL=0, DEBUGEN=0, DEBUGEN_LOCK=0x10f, runtime readback PASS.
This confirms application execution, not signature enforcement or SWD denial.
The running application has no USB stdio interface; operator BOOTSEL re-entry
is needed before another host device operation. I2C/EEPROM preflight failures
are expected without the carrier; investigate them if it is attached.
See [handoff §13.15](../../SIGNAL-BOX-HANDOFF.md#1315-operator-reported-recovery-boot-and-runtime-readback-pass).
No OTP changes or additional device operations accompanied this observation.

## Unprovisioned SRAM recovery round trip

Operator UART reports confirm flash `recovery` → signed SRAM `debug-closed` →
normal flash `recovery`, with CRITICAL=0, DEBUGEN=0 and DEBUGEN_LOCK=0x10f throughout.
Independent post-RAM checks found full 2 MiB flash unchanged, all 34 policy rows
unchanged and all 256 candidate key-storage rows still physically blank. No OTP
writes occurred; security enforcement remains disabled. See
[handoff §13.16](../../SIGNAL-BOX-HANDOFF.md#1316-unprovisioned-flashsramflash-recovery-round-trip-pass).

Sources: [picotool 2.3.1 implementation](https://github.com/raspberrypi/picotool/blob/2.3.1/main.cpp)
(`determine_chip_revision`, `guess_flash_size`, `info_guts`) and the pinned SDK
OTP register definitions linked in [README.md](README.md).
