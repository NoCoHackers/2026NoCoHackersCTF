# RP2350 security prototype — staged sacrificial provisioning

**Hold before KEY_VALID; no further OTP or encrypted-image writes are authorized.**
This directory contains image/backup preparation and a guarded one-shot hash-only
writer. The separately approved hash write now reports PASS (handoff §13.22);
do not rerun it or clear its attempt latch. In a
separately approved device stage, the signed **plaintext** recovery UF2 was
flashed and readback-verified on the sacrificial board. The operator subsequently
reported normal LED behavior and UART execution with the expected runtime controls.
This confirms recovery boot, not signature enforcement or physical debug denial.
Only slot-0 hash data has been programmed, per the operator's verification
transcript; no key activation, permanent locks, revocations or rollback changes
have been performed. The known-good wired DUT stays unlocked. See
[SACRIFICIAL-BOARD.md](SACRIFICIAL-BOARD.md) for the flash-backup checkpoint.

For a new computer, start with [the migration handoff](../../SIGNAL-BOX-MIGRATION.md).
It covers private state/tool preservation, backup gaps, path compatibility and
safe offline checks. Migration is not permission to repeat the hash write.

## Approved lifecycle

The operator approved **ARM-only post-event reuse**:

- Use signing keys specific to this event, never reused for another event,
  infrastructure, or unrelated devices. Keep private material outside this
  repository, including ignored directories, until deliberate post-event release.
- After the event, publish the signing private/public keys and a reuse kit with
  the encryption material and device salt mapping needed by the supported
  workflow, source, pinned tools, and build/sign/flash instructions.
- Secure boot remains enabled in OTP after release. Key publication lets
  participants authorize their own images; it does not restore factory state.
- RP2350 secure boot permanently disables RISC-V cores. This limitation was
  explicitly accepted. Debug/interface restrictions are separate decisions;
  signing-key possession cannot undo OTP bits. However, authenticated Secure
  firmware can override the debug-disable defaults through runtime DEBUGEN;
  post-event SWD reuse will be tested explicitly after a cold reset.
- Preserve a usable BOOTSEL update/recovery interface and demonstrate reuse on
  the sacrificial board before applying the design to the batch. The sacrificial
  interface/debug policy is approved; hardware acceptance and batch policy remain
  separate gates.

Signing uses a secp256k1 key pair. Encryption uses separate AES key material
and a per-device IV salt. The sacrificial OTP policy is approved; the production
policy remains to be reviewed. No production/event keys have been generated.
Initial host checks used disposable random material in a private
`/tmp/signal-box-security-lab-*` directory. **Never provision OTP from those
throwaway keys or rely on /tmp for backups.** Persistent, separate sacrificial
keys have now been created outside the repo and pass offline packaging checks.
The operator has completed the encrypted USB restore: all eight recovered files
matched, and recovered-key packaging passed signature/plaintext-marker checks.
See [KEY-RECOVERY.md](KEY-RECOVERY.md) for the transcript-based checkpoint and
receipt path. [PROVISIONING-PLAN.md](PROVISIONING-PLAN.md) records the approved
sacrificial policy, with unused-slot revocation removed, and staged recovery/reuse
tests. `otp_policy.py` prints its non-secret tables as review-only JSON, not an
executable/loadable recipe. [RECOVERY-PROBES.md](RECOVERY-PROBES.md) documents the
new recovery/debug variants, exact offline image/key binding and separate
37-file snapshot preparation. The operator has now completed its encrypted USB
restore and recovered-key rebuilds; see KEY-RECOVERY.md. Hardware acceptance,
reviewed staged write artifacts and separate programming approvals are still
required before any permanent operation. The unprovisioned flash/SRAM/flash
recovery round trip has passed; this does not establish recovery under enforced
trust.

## Signing-hash data artifact (offline only)

[SIGNING-HASH-STAGE.md](SIGNING-HASH-STAGE.md) documents the independently reviewed
first data-stage sidecar. `prepare_signing_hash.py` emits/checks exactly 32 digest
bytes for ECC rows `0x0080–0x008f`, bound to the original keys, restored snapshot,
completed recovery evidence and pinned tool. No executable device writer or
loadable OTP JSON is emitted, and no activation, revocation, lock or secret data
is included. `check_signing_hash.py` checks the mapping and all 65,536 ECC16
encodings with explicit-file, no-device picotool simulations.

The new four-file sidecar is separate from the unchanged 37-file snapshot. It
uses an explicit five-member backup profile (four artifact files plus their bound
journal), documented in [HASH-ARTIFACT-RECOVERY.md](HASH-ARTIFACT-RECOVERY.md).
The operator encrypted USB restore has passed; see KEY-RECOVERY.md. The guarded
hash-only writer passed source review, live read-only preflight and a separately
authorized operator-run hash write (handoff §13.22). The current hold is before
KEY_VALID. Eight-/37-file validators remain unchanged.
Preparation is **not** permission to program OTP.

The separate guarded `write_signing_hash.py` is documented in
[HASH-WRITE-PROCEDURE.md](HASH-WRITE-PROCEDURE.md). Its default workflow requires
an explicit mode: offline file checks, separately approved live read-only
preflight, or separately approved local-terminal hash-only programming. It has
one fixed write scope, fresh repeated checks, a per-board lease, a durable
no-retry latch, and sealed immutable executable/payload descriptors. Preparation
used no live modes; the subsequent authorized hash write reports verified success.
Preserve its permanent latch. The original all-blank preflight is no longer the
device baseline. Activation, revocation, locks and AES remain excluded.

The next stage's [KEY_VALID-only contract](KEY-VALID-STAGE.md) and public row
model (`key_valid_policy.py`) have passed source review and offline tests. They
model only three raw rows at `0x004b–0x004d`, each 0 → 1. No private activation
artifact, live writer or activation approval is supplied. Preserve the hash
writer's latch; the next stage must verify its programmed hash, not require it
blank. See handoff §13.23 for source findings and remaining gates.

## What the offline path demonstrates

The previously bench-tested diagnostic source can also be built as an SRAM
payload (`no_flash`) with version `0.2.0-rp2350-ram-prototype`. This is separate
from the ordinary XIP debug UF2 and does not alter that build's default behavior.

`package_probe.py`:

1. Requires an ARM ELF32 with SRAM entry point and SRAM load addresses, plus the
   diagnostic marker in a loadable segment. Rejects ordinary XIP, copy-to-RAM
   flash images, and non-probe applications.
2. Requires owner-only, off-repo `signing.pem`, `aes-share.bin` (128 bytes), and
   `iv-salt.bin` (16 bytes). The AES file is a saved four-way key share, not a
   32-byte raw AES key whose shares would be regenerated by picotool.
3. Uses **picotool 2.3.1** `encrypt --embed --sign` with the default embedded
   decryptor, not `--use-mbedtls`. No OTP JSON positional argument is supplied.
4. Packages the resulting SRAM image into a flash-addressed ARM Secure UF2,
   validates its block headers/addresses, and asks picotool to verify the
   embedded signature. The tool's `info` command is given a file, not a device.
5. Checks that the diagnostic plaintext marker is absent from the encrypted
   ELF/UF2 and reconstructed flash bytes, including across UF2 block boundaries.
6. Writes only to a new private off-repo output directory; never overwrites an
   existing release directory. Tool output from encryption is not echoed (the
   embedded-decryptor tool output was observed to contain non-UTF-8 bytes).

The only picotool commands the wrapper invokes are `version`, `encrypt`,
`uf2 convert`, and file-based `info`. It does not generate keys or export an
OTP permissions recipe. `inspection.txt` contains public image/signature
metadata, not private key material.

**Limits:** signature verification against an image's embedded key does not
prove that a device trusts that key. Marker absence is a useful regression
check, not a proof of complete confidentiality. No encrypted image has yet
booted on hardware; no OTP access-control or debug policy has been validated.
The application here contains no CTF flags.

## Reproduce the offline build

Requires the ARM GCC/newlib toolchain, CMake, Pico SDK **2.2.0**, and the official
[picotool 2.3.1 host release](https://github.com/raspberrypi/pico-sdk-tools/releases/tag/v2.3.1-0).
The plain debug port previously used picotool 2.1.1; its encryption interface
is older and must not be substituted here. The full production security stack
still needs a version/errata review before provisioning.

Set paths outside the repository. `KEY_DIR` must contain independently created
**lab-only** files with the names and permissions above. The output parent must
exist; `OUTPUT_DIR` itself must not exist. These commands only operate on files:

```sh
export PICO_SDK_PATH=/path/to/pico-sdk-2.2.0
export PICOTOOL_DIR=/path/to/extracted/picotool-2.3.1/picotool
export RAM_BUILD=/path/outside/repo/ram-probe-build
export KEY_DIR=/path/outside/repo/lab-keys
export OUTPUT_DIR=/path/outside/repo/new-offline-probe

cmake -S challenges/misc/signal-box/firmware/debug/rp2350 \
  -B "$RAM_BUILD" -DPICO_SDK_PATH="$PICO_SDK_PATH" \
  -Dpicotool_DIR="$PICOTOOL_DIR" -DSIGNAL_BOX_RAM_PROTOTYPE=ON \
  -DCMAKE_BUILD_TYPE=MinSizeRel
cmake --build "$RAM_BUILD" --parallel 4
python3 challenges/misc/signal-box/firmware/security/package_probe.py \
  --picotool "$PICOTOOL_DIR/picotool" \
  --input "$RAM_BUILD/signal-box-debug-rp2350.elf" \
  --key-dir "$KEY_DIR" --output-dir "$OUTPUT_DIR"
```

Output is `offline-encrypted-probe.uf2` with an accompanying `DO-NOT-FLASH.txt`.
It requires matching OTP material; do not copy it to an unprovisioned board.
The unencrypted SRAM build's own UF2 is also not a persistent flash application.
Use the ordinary default XIP build for the established electrical acceptance.

Host-only regression tests:

```sh
python3 -B -m unittest discover \
  -s challenges/misc/signal-box/firmware/security -p 'test_*.py' -v
```

Initial verification: 15 unit tests pass; the real SDK RAM build and picotool
packaging complete; picotool reports a verified signature and an SRAM load map
for the flash-packaged image; the plaintext probe marker is absent from the
reconstructed flash payload. No connected device was accessed.

## Gates before any permanent operation

1. Identify the sacrificial board unambiguously and record silicon/board
   revision, documented flash capacity, exposed SWD/RUN access, and applicable
   errata. The identified board is RP2350 A4; the supplied Seeed datasheet
   specifies 2 MB flash. See [SACRIFICIAL-BOARD.md](SACRIFICIAL-BOARD.md).
   No lid removal is required; defer electronic part identification until
   part-specific flash operations actually need it.
2. Review upstream decryptor, secure-boot enforcement, OTP layout and page
   permissions for the pinned tools. **Do not copy an example OTP JSON.** In
   picotool 2.3.1 source, `FIB_WORKAROUND` changes encryption storage to three
   pages with inverse/ECC data: shares at base/base+1, salt at base+2. CLI help
   still describes salt as on the next page. This discrepancy alone makes a
   version-specific source review necessary; no final page allocation is
   approved by this document.
3. Establish persistent off-repo event keys, per-device salt records, and
   tested organizer backups. Plan nonconflicting signing-key slots, key-page
   locks, debug restrictions, interfaces, and any rollback policy. Show the
   exact proposed OTP rows/bit transitions to the organizer for approval.
4. Use reversible RAM/flash experiments where possible before the approved
   sacrificial OTP sequence. Then prove cold encrypted boot and all intended
   UART/EEPROM/optical behavior under the actual lock policy.
5. Negative tests: raw-flash inspection, wrong-key/unsigned/tampered images,
   debug/OTP read attempts, and recovery from an erased or invalid application.
   Avoid leaving old plaintext firmware remnants in flash during final
   provisioning; a new encrypted image alone is not a whole-chip erase.
6. Demonstrate an authorized update from a host with only the prepared image,
   not private keys. Separately prove the post-event reuse kit can build/sign
   an unrelated ARM application and flash it under the final OTP policy.
7. Only then approve the batch procedure. Retest with the actual participant
   firmware once it exists; this debug probe is not a shipping challenge.

No OTP or security restrictions should be relaxed during the event merely to
make reuse easier. Instead, authorize arbitrary participant firmware after
key release while retaining the irreversible hardware policy.

## Source references

- [Pico SDK 2.2.0 OTP layout](https://github.com/raspberrypi/pico-sdk/blob/2.2.0/src/rp2350/hardware_regs/include/hardware/regs/otp_data.h):
  `CRIT1_SECURE_BOOT_ENABLE`, debug restrictions, and BOOTSEL interface bits.
- [Pico SDK RP2350 address map](https://github.com/raspberrypi/pico-sdk/blob/2.2.0/src/rp2350/hardware_regs/include/hardware/regs/addressmap.h):
  SRAM range used by the wrapper checks.
- [Seeed SKU 102010550 datasheet, pp. 3 and 5](https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/8932/102010550.pdf):
  2 MB flash, used as a 2 MiB build/validation limit. This overrides the
  [SDK XIAO board definition's](https://github.com/raspberrypi/pico-sdk/blob/2.2.0/src/boards/include/boards/seeed_xiao_rp2350.h)
  conflicting 4 MiB default.
- [picotool 2.3.1 documentation](https://github.com/raspberrypi/picotool/blob/2.3.1/README.md)
  and [implementation](https://github.com/raspberrypi/picotool/blob/2.3.1/main.cpp):
  signing, embedded encryption, packaging, and generated OTP layout.
- [Separate encrypted-bootloader example](https://github.com/raspberrypi/pico-examples/tree/master/bootloaders/encrypted):
  explicitly warns about its MbedTLS implementation's physical side-channel
  limitations. Its sample keys and OTP recipe are not this project's policy.
