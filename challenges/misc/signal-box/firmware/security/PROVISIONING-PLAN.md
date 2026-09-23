# Sacrificial RP2350 OTP policy — approved design, execution gated

**Status: organizer approved the policy with unused-slot revocation removed.**
Slots 1–3 remain blank and inactive; no KEY_INVALID bits will be programmed.
This approval does not waive artifact/recovery/backup gates or authorize OTP
writes or encrypted-image flashing.
This specifies the non-secret row values and required sequencing for the one
sacrificial XIAO RP2350 A4, serial **9423D016AADE5950**, ROM gitrev `0xa8bfe860`.
It is not batch authorization. Offline image/binding preparation is documented
in [RECOVERY-PROBES.md](RECOVERY-PROBES.md). Exact staged write artifacts, the
updated verified backup and hardware acceptance remain gates before irreversible
work; no device writer is included in the preparation tools.

`otp_policy.py` prints the public tables as deliberately non-picotool JSON. It
imports only `json`, reads no files or devices, and includes no keys. **Do not
pass that output, or a combined example/generated OTP JSON, to `picotool otp load`.**
Nine policy tests cover exact baseline matching, monotonic transitions,
redundancy, preserved routes/rows, absence of slot revocation, disjoint data regions and
staging. Fifteen row/field constants were also
cross-checked directly against the pinned SDK header. These checks do not
substitute for fingerprint binding, approval, or any hardware acceptance gate.

## 1. Gates already passed

- Known-good wired RP2350 debug bring-up, both RP2040 tester WP modes, and a
  cold-start final-mode pass are recorded in the handoff. This is separate from
  security acceptance of the sacrificial board.
- Persistent sacrificial keys were generated outside Git; the operator restored
  the encrypted USB archive and all eight files matched. Recovered-key packaging
  passed signature and plaintext-marker checks. Receipt path is in
  [KEY-RECOVERY.md](KEY-RECOVERY.md); evidence is the operator's transcript.
- Fresh read-only preflight on **2026-09-11 03:26 UTC**, selected by full USB
  serial: A4/ROM identity matched; all **34 physical policy rows** matched the
  recorded baseline, including independent critical/boot-flag copies.
- All **64 physical rows of signing-key page 2** and **192 physical rows of
  candidate pages 29–31** were zero. Only blankness counts were reported; no
  key-storage row values were printed or saved. This was the pre-enrollment
  baseline, not a permanent assertion. After the hash write (§13.22), verify exact
  enrolled slot0 raw encodings plus blank spares/secret rows instead. Never reuse
  the all-blank expectation for KEY_VALID; see [KEY-VALID-STAGE.md](KEY-VALID-STAGE.md).

### Read-only CLI gotcha

With picotool 2.3.1, keep raw-read options in documented order:
`otp get -c 1 -r -n --ser <serial> <explicit-physical-rows>`.
Putting `-r` before `-c 1` was observed to treat `1` as another row selector and
ignore the intended options. A reader must require exactly the requested rows
and one raw value per row, not silently accept extra/missing output. No write
command has been tested or authorized by this observation.

## 2. Approved policy and irreversible consequences

- Enforce signatures using **slot 0 only**. Leave slots 1–3 blank and inactive;
  do not program KEY_INVALID bits. Root policy/hash page write-protection already
  prevents enrollment of an attacker's key, so explicit spare-slot revocation
  is unnecessary for the intended flag-extraction threat. Those page locks also
  prevent later legitimate key enrollment: this change does not preserve key
  rotation. Post-event reuse still relies on publishing the event signing key.
- Disable all debug **by default**. Keep BOOTSEL USB MSD and PICOBOOT available
  for authenticated recovery, and retain authenticated SRAM boot. Do not enroll
  OTP debug-authentication keys.
- Disable unused **ROM UART boot** and **OTP boot** routes. This does not disable
  the challenge's ordinary UART console, nor does it disable OTP storage/access
  for the trusted decryptor or provisioning tools.
- Write-protect root policy/hash pages; AES/salt pages allow Secure reads only,
  with no Non-secure or BOOTSEL user access.
- Leave page 0, every LOCK0 row, anti-rollback policy/counters, architecture-choice
  bits, and glitch-detector fuse settings unchanged for this first prototype.
  This is not an invasive/fault-attack resistance claim. Reassess production
  policy before sealing any batch units; locked prototype policy is not tunable.
- Secure boot **permanently disables RISC-V**. Publishing signing/encryption
  material after the event permits new authorized ARM images, not a factory reset.

### Important correction: debug can be reopened by trusted firmware

SDK `OTP_DEBUGEN` explicitly permits Secure software to override the disable
conditions. Setting all implemented bits (`0x10f`) can override `DEBUG_DISABLE`.
`OTP_DEBUGEN_LOCK` locks those runtime override bits until **processor cold
reset**; it is not a lifetime OTP lock.

The event image must retain `DEBUGEN=0` and lock its implemented bits early,
without granting Non-secure access to OTP/debug control. A separately signed
post-event ARM image can set `DEBUGEN=0x10f` after a cold reset and reopen debug.
**This path is documented but not yet hardware-tested.** Never distribute a
working event-key-signed debug unlocker or plaintext-dumping recovery image
before the event ends; without anti-rollback it remains a replay candidate.
The sacrificial test key is distinct from the eventual event key.

Writing zero to DEBUGEN does not disable an otherwise enabled factory debugger:
the OTP debug-default flag must also be effective. Picotool's `secure debug
enable` display reports the individual Secure-only fuse, not the combined
hardware/debug-override result. Test actual debug access; do not infer it from
one printed field. Debug-authentication keys do not undo CRIT1 disable flags.

## 3. Exact non-secret control rows

All indices below are **OTP row numbers, not MCU byte addresses**. Raw rows carry
24 bits. CRIT1 repeats a whole word across eight rows; BOOT_FLAGS0/1 each repeat
whole words across three rows. LOCK1 instead has three low-byte copies within
one raw row. Preserve these different redundancy schemes.

Values assume the freshly verified baseline; any difference requires a new
review, not an automatic OR/ignore-already-set operation.

| Purpose | Physical rows | Baseline | Proposed transitions / final raw word |
|---|---|---:|---:|
| CRIT1 signature enforcement + debug default | `0x040–0x047` (8 rows) | `0x000000` each | `0x000001`, then `0x000005` each |
| BOOT_FLAGS0 unused ROM routes | `0x048–0x04a` (3 rows) | `0x000000` each | `0x082000` each |
| BOOT_FLAGS1 key 0 only; no revocations | `0x04b–0x04d` (3 rows) | `0x000000` each | `0x000001` each |
| PAGE2_LOCK1, signing hashes | `0xf85` | `0x040404` | `0x151515` |
| PAGE1_LOCK1, critical policy | `0xf83` | `0x040404` | `0x151515` |
| PAGE29_LOCK1, AES share first half | `0xfbb` | `0x000000` | `0x3d3d3d` |
| PAGE30_LOCK1, AES share second half | `0xfbd` | `0x000000` | `0x3d3d3d` |
| PAGE31_LOCK1, salt | `0xfbf` | `0x000000` | `0x3d3d3d` |

Decoded final flags:

- CRIT1 `0x5`: `SECURE_BOOT_ENABLE=1`, `DEBUG_DISABLE=1`.
  `SECURE_DEBUG_DISABLE=0` is sufficient because all-debug disable subsumes it.
- BOOT_FLAGS0 `0x082000`: `DISABLE_OTP_BOOT` bit 13 and
  `DISABLE_BOOTSEL_UART_BOOT` bit 19 only. USB-disable bits 17/18, SRAM-window
  disable bit 21, flash-disable bit 12, OTP-enable bit 14, and rollback-required
  bit 11 all remain zero.
- BOOT_FLAGS1 `0x1`: `KEY_VALID=1`, `KEY_INVALID=0`. Only slot 0 is activated;
  slots 1–3 stay blank/inactive and no slots are revoked.
  **Do not write `0x010101` as a substitute for KEY_VALID redundancy.**
- LOCK1 `0x151515`: Secure/Non-secure/BOOTSEL user access all read-only.
- LOCK1 `0x3d3d3d`: Secure read-only, Non-secure inaccessible, BOOTSEL user access
  prohibited. `LOCK_BL` is enforced by ROM software advancing hardware software
  locks; it is not an independent hardware secrecy boundary.

Unchanged: CRIT0 rows `0x038–0x03f`; page-0 locks `0xf80=0x3f3f3f` and
`0xf81=0x151515`; LOCK0 rows `0xf82`, `0xf84`, `0xfba`, `0xfbc`, `0xfbe` all zero.
No write to any other policy/lock row is part of this proposal.

## 4. Key-dependent rows — derive privately, never paste into chat

Use the exact restored sacrificial files. Production credentials are out of
scope. Do not regenerate key shares or salt as a provisioning convenience.

| Selector | Physical rows | Data | Encoding |
|---|---|---|---|
| `bootkey0` | `0x080–0x08f` | 32-byte signing-public-key hash | 16-bit data + ECC per row |
| `29:0` | `0x740–0x75f` | AES share bytes 0–63 | ECC, 32 rows |
| `29:32` | `0x760–0x77f` | Corresponding physical complements | raw 24-bit, 32 rows |
| `30:0` | `0x780–0x79f` | AES share bytes 64–127 | ECC, 32 rows |
| `30:32` | `0x7a0–0x7bf` | Corresponding physical complements | raw 24-bit, 32 rows |
| `31:0` | `0x7c0–0x7c7` | Salt bytes 0–15 | ECC, 8 rows |
| `31:32` | `0x7e0–0x7e7` | Corresponding physical complements | raw 24-bit, 8 rows |

No padding writes to `0x7c8–0x7df` or `0x7e8–0x7ff`. There are 16 signing-data
rows and 144 secret-data/complement rows, not 256 bytes of arbitrary raw keys.

### Byte-order rules

Picotool hashes **X_BE32 || Y_BE32**: two fixed-width, big-endian secp256k1
coordinates (64 bytes), without the SEC1 `0x04` prefix. Do not hash PEM/DER/SPKI
or a compressed point. SHA-256 digest bytes are stored unchanged; ECC row i
contains `digest[2*i] | (digest[2*i+1] << 8)`.

The 128-byte four-way share represents an **AES-256** key. Its words are
interleaved: effective key word i is XOR of share words `4*i` through `4*i+3`,
not four consecutive 32-byte arrays. Preserve the exact original share file.

Pinned picotool 2.3.1 enables `FIB_WORKAROUND`: if E is the physical normal
ECC-encoded row, its inverse is `(~E) & 0xffffff`, including ECC and the two high
BRP bits. A raw transport row occupies four bytes (low three carry the 24-bit
value, fourth is padding). It is not ECC(~data), nor merely a 22-bit complement.
Use the pinned tool's emitted layout and independently cross-check public test
vectors; do not invent an alternative encoder. Check physical normal/inverse
complements as well as logical ECC readback.

## 5. Staging and hold points — no one-shot provisioning

Every numbered irreversible gate requires the approved exact artifacts and a
fresh identity/state check. Do not continue after unexpected values, readback
failure, power interruption, or a failed recovery test. Retain private audit
logs; picotool OTP operations can print secret input values.

### A. Prepare without changing OTP

1. Bind the public fingerprint and data artifacts to the restored files and
   exact device serial. Split data, activation, and page-lock artifacts.
   Picotool's generated `seal` JSON combines hash, validity and activation;
   `encrypt` JSON combines secrets and locks. Neither is an ordered transaction.
2. Build/review three signed lab artifacts: a plaintext recovery probe (not an
   OTP programming agent), a debug-closed probe, and a private debug-reopen probe.
   The new variants implement/read-check early application debug controls and
   reject Non-secure OTP peripheral access; see RECOVERY-PROBES.md. The embedded
   loader locks debug before key use but freezes inherited overrides, so reopen
   must be plaintext signed and cold-started. Keep the original backed-up ELF
   historical, and place the new variants in a separate prepared snapshot.
   Review the loader's key wiping/software locks and test hardware behavior.
3. Test the unsigned/unprovisioned board's basic ability to boot the signed
   plaintext recovery image. This is not proof of enforcement, but catches
   image/transport mistakes before a fuse is burned. Back up its complete 2 MiB
   flash before approved replacement/erase tests.
4. Add this reviewed policy, exact artifacts, image identities and recovery
   instructions to a new encrypted recovery snapshot. Update both backup and
   restore allowlists/limits/manifests and repeat the verified USB restore.

### B. Enroll and prove trusted boot — no AES secrets yet

5. Program **only** slot-0 hash data; independently verify ECC, raw rows and the
   expected public fingerprint. Leave policy/hash page write locks unchanged
   during initial controlled bring-up so an enrollment failure can be assessed
   before further restrictions.
6. Set KEY_VALID bit 0 in all three rows; verify copies. Only then set
   SECURE_BOOT_ENABLE in all eight CRIT1 rows. This is the ARM-only commitment.
7. Cold boot the signed recovery image; prove valid signed flash and RAM helpers
   work and unsigned/wrong-key images cannot execute. Keep lab AES material off
   the device while debug and root-policy writes remain available.

### C. Prove recovery/debug defaults, then protect the trust root

8. Close the two unused ROM routes (`BOOT_FLAGS0=0x082000`) and set DEBUG_DISABLE
   (`CRIT1=0x5`). Cold-test real SWD access, USB recovery, and the signed private
   debug-reopen image. Restore the debug-closed image and cold-cycle again.
   Do not expose the board to participants during these controlled test windows.
9. After those tests pass, verify BOOT_FLAGS1 is still `0x1` in all three
   physical copies: only slot 0 valid, no invalidation bits. Verify slots 1–3
   remain physically blank. Do not make another BOOT_FLAGS1 write. Protect
   page 2, then page 1 with the stated LOCK1 values. Read back all raw redundant
   lock bits. These steps prevent later key enrollment and changes to those
   policy pages, including future fuse tuning.
10. Prove signed recovery/updates still work and root-page writes are prohibited
    under the final root policy. Only now is it appropriate to install AES data.

### D. Install verified encrypted-boot material

11. Write secret normal/inverse rows in a controlled bench session and verify
    privately before locking: every raw row, ECC view, physical complement, and
    exact share/salt match. Do not send output or raw OTP JSON to chat or Git.
12. With all intended data/LOCK0 choices complete, apply PAGE29/30/31 LOCK1
    restrictions. Verify all three byte copies of each raw lock word. BOOTSEL
    readback of protected contents must then fail; loss of that host access is
    expected, not a reason to weaken locks.
13. Load the signed/encrypted probe and cold-test it. Its protected page data
    remains Secure-readable for boot; the embedded decryptor software-locks key
    pages after initialization and all three pages before handing off. Secure
    read-only by itself is not enough without root integrity and debug policy.

## 6. Acceptance matrix before any batch deployment

| Test | Required outcome |
|---|---|
| Valid signed encrypted flash boot | Cold boot, UART/LED and later wired fixture tests pass |
| Unsigned/wrong-key/tampered payload or signature | No execution canary, through flash **and RAM/reboot** paths |
| RISC-V image | Cannot execute under secure boot |
| OTP key/salt reads and writes via BOOTSEL | Denied under final locks |
| Root hash/policy/lock modification | Denied; potentially destructive negative writes require explicit separate approval |
| SWD cold attach/rescue/reset, both cores | No application memory/halt access in event mode; a visible RP-AP alone is not failure |
| Warm BOOTSEL transition after decryption | Public SRAM reads disclose no retained plaintext, keys or salt |
| Raw 2 MiB flash dump | Encrypted application data; no flag/canary plaintext or prior plaintext remnants |
| Erased/corrupt/interrupted application update | Physical BOOTSEL accepts authorized recovery, then encrypted boot works |
| Signed update from a host without private keys | Prepared compatible update loads and boots |
| Post-event reuse simulation with lab credentials | Rebuilt ARM application boots; signed cold-start debug override restores SWD |

BOOTSEL remaining accessible is necessary but not sufficient: ROM SRAM transfer
capability is not permission to execute arbitrary Secure code. Exercise actual
available EXEC2/reboot-to-SRAM services, not just rejection of legacy EXEC.
Bound all addresses/lengths; peripheral/debug-register writes must not become
an alternate control path. Do not accept transport success alone as code execution.

The current debug console has no firmware-triggered BOOTSEL command. Add a
reviewed test path if needed for warm-handoff coverage; do not claim that test
passed from a cold unplug/replug. Require an actual SWD instrument for debug
acceptance, not just OTP flag readback.

Signed boot does not stop denial-of-service via physical flash damage. Normal
metadata/decryptor bytes remain visible. This plan targets the intended simple
flash/debug extraction routes, not a proof against invasive physical attacks.
A4 mitigates several A2 issues but is not tamper-proof; keep the tool's FIB layout.

## 7. Remaining blockers and evidence sources

**Policy approved with unused-slot revocation removed.** Offline preparation now
builds and checks recovery/debug images and binds them to the restored key pair.
The expanded encrypted USB restore passed per the operator transcript; see
[KEY-RECOVERY.md](KEY-RECOVERY.md). The first slot-0 hash data-only artifact has
now been prepared and independently reviewed offline; see
[SIGNING-HASH-STAGE.md](SIGNING-HASH-STAGE.md). Its separate five-file encrypted
USB restore has now passed per the operator transcript in KEY-RECOVERY.md.
The guarded hash-only writer has also passed source review; see
[HASH-WRITE-PROCEDURE.md](HASH-WRITE-PROCEDURE.md). After live read-only preflight,
the separately authorized operator-run hash write reported verified success
(handoff §13.22). **Hold before KEY_VALID.** Preserve its attempt latch; slot-0
hash rows are no longer blank. The [KEY_VALID-only model/contract](KEY-VALID-STAGE.md)
has passed source review and offline checks (§13.23), without device/private
predecessor access. **Still blocked on:** a bound activation artifact and verified
backup/restore, separate guarded writer review, explicit next-stage approvals and
fresh physical checks, remaining staged artifacts and hardware recovery/debug/boot
acceptance. The first authorized signed plaintext recovery flash write and
readback have passed, with a verified full-flash backup. In response to the
cold-start request, the operator reported normal LED behavior and UART recovery
execution with the expected runtime controls. The subsequent unprovisioned
flash `recovery` → signed SRAM `debug-closed` → flash `recovery` round trip also
passed, with full-flash and OTP-baseline preservation checked independently of
the operator UART execution reports. Repeat recovery under enforced trust later.
Signature enforcement, physical SWD denial/reopening and encrypted hardware boot
remain untested, with OTP security flags still off. No OTP stage has been executed. See
[SACRIFICIAL-BOARD.md](SACRIFICIAL-BOARD.md). The byte-for-byte relation between public ROM source and board
ROM gitrev `a8bfe860` is unconfirmed (public commit lookup did not resolve it).
Hardware tests remain mandatory; do not substitute a different public commit
for attested board ROM bytes.

Primary sources checked independently in two public-source research lanes:

- [SDK 2.2.0 OTP data rows/fields](https://github.com/raspberrypi/pico-sdk/blob/2.2.0/src/rp2350/hardware_regs/include/hardware/regs/otp_data.h):
  row numbers, redundancy, key-valid-before-secure-boot requirement, locks.
- [SDK 2.2.0 runtime OTP registers](https://github.com/raspberrypi/pico-sdk/blob/2.2.0/src/rp2350/hardware_regs/include/hardware/regs/otp.h):
  DEBUGEN override and cold-reset DEBUGEN_LOCK semantics.
- [picotool 2.3.1 main.cpp](https://github.com/raspberrypi/picotool/blob/2.3.1/main.cpp#L6004-L6116):
  exact FIB layout/lock generation; [signing activation JSON](https://github.com/raspberrypi/picotool/blob/2.3.1/main.cpp#L6239-L6268).
- [picotool key serialization](https://github.com/raspberrypi/picotool/blob/2.3.1/bintool/bintool.cpp)
  and [crypto wrapper](https://github.com/raspberrypi/picotool/blob/2.3.1/bintool/mbedtls_wrapper.c):
  coordinate encoding, curve, and SHA-256.
- [picotool 2.3.1 embedded decryptor](https://github.com/raspberrypi/picotool/blob/2.3.1/enc_bootloader/enc_bootloader.c):
  salt at base+2, guarded reads and software locks. Its actual source overrides
  stale README/CLI wording that places salt immediately after the key page.
- [Public ROM NSBOOT dispatcher](https://github.com/raspberrypi/pico-bootrom-rp2350/blob/c6cdb1711f32c3e34faaebd58618a6d096dbd52e/src/nsboot/nsboot_async_task.c)
  and [NSBOOT entry policy](https://github.com/raspberrypi/pico-bootrom-rp2350/blob/c6cdb1711f32c3e34faaebd58618a6d096dbd52e/src/main/arm/varm_nsboot.c):
  USB command constraints, OTP page policy, memory handoff. Corroborating source,
  not proof of exact target ROM implementation.
- [Official A4 security discussion](https://www.raspberrypi.com/news/rp2350-a4-rp2354-and-a-new-hacking-challenge/).
