# Offline recovery/debug probes — not hardware accepted

The sacrificial policy is approved **without spare-slot revocation**. This step
prepares images and a new private backup snapshot; it does not program OTP,
flash a board, change the existing eight-file key bundle, or overwrite old USB
archives. Keep all signed lab artifacts private, especially debug-reopen.

## Firmware variants

All three are ARM Secure `no_flash` applications using SDK 2.2.0. They retain the
existing diagnostic UART/fixture behavior and public RAM-prototype marker.
`SIGNAL_BOX_SECURITY_PROFILE=none` remains the default: normal RP2350 electrical
bring-up and the RP2040 debug/tester paths do not include the new runtime code.

| Profile | Runtime override | Packaging |
|---|---|---|
| `recovery` | DEBUGEN=0, lock implemented bits | Plaintext signed flash and SRAM variants |
| `debug-closed` | DEBUGEN=0, lock implemented bits | Plaintext signed flash/SRAM and signed encrypted flash |
| `debug-reopen` | DEBUGEN=0x10f, lock implemented bits | **Plaintext signed only**, private cold-start reuse test |

`security_profile.c` registers the first SDK runtime initializer (`00001`), before
SDK ROM-state reset and clocks. It disables interrupts, writes/read-checks the
override, locks/read-checks all implemented bits, and rejects Non-secure access
to the OTP peripheral. A mismatch spins without reaching UART/application code.
This hook is **after CRT copying/BSS setup and after any embedded decryptor**.
A failed inherited-lock check may produce no banner; recover with a genuinely
cold power cycle, including removal of UART/fixture backfeed.

After ordinary UART initialization, `status` prints the role and public
CRITICAL/DEBUGEN/DEBUGEN_LOCK values. `runtime-readback=PASS` is not SWD or secure
boot acceptance: before the OTP debug-disable flag is set, zero overrides do
not disable the factory-enabled debugger.

The profile-only `bootsel` command drains UART for at most 100 ms and requests
ROM USB BOOTSEL with both interfaces retained. This enables the warm-handoff
memory-retention test; it does not prove SRAM is sanitized. No arbitrary-memory
or OTP read/write command has been added. The recovery probe demonstrates signed
execution and fixture operation; it is **not** an OTP provisioning agent.

## Embedded-loader review result

Pinned picotool 2.3.1's default loader locks DEBUGEN_LOCK **before** guarded OTP
reads/decryption and uses hardened lock readback. It does not clear or check
DEBUGEN itself: it freezes inherited overrides and relies on cold-reset OTP
defaults. Consequently an encrypted reopen application cannot reopen debug.
Never enable the upstream `ALLOW_DEBUGGING` loader configuration, which contains
a plaintext-to-flash diagnostic path after failed chaining.

The installed release executable was checked to contain the exact upstream
2.3.1 default `enc_bootloader.elf` (public source commit
`2041936441b48a3cc53ae3da9e805229fe8f4e18`), SHA-256:

```text
9ce3c424d61226225d2c1f5b80a8854f15174b09dd447e58e4439240b274fb3d
```

This is an embedded-file provenance check, not a complete executed-path or
hardware audit. The private snapshot binds the actual picotool executable hash.
Rebuilding the loader requires SDK >=2.2.1; that is separate from the application
SDK 2.2.0 pin. This step neither rebuilds nor customizes the loader.

## Build and offline integration

From the repository root, using the already installed tools:

```sh
D=challenges/misc/signal-box/firmware/debug
for profile in recovery debug-closed debug-reopen; do
    cmake -S "$D/rp2350" -B "$D/build-rp2350-$profile" \
        -DPICO_SDK_PATH=/tmp/signal-box-pico-sdk-2.2.0 \
        -Dpicotool_DIR=/tmp/signal-box-picotool-2.1.1/picotool \
        -DSIGNAL_BOX_RAM_PROTOTYPE=ON \
        -DSIGNAL_BOX_SECURITY_PROFILE="$profile" \
        -DSIGNAL_BOX_ACK_PRIVATE_DEBUG_REOPEN=ON
    cmake --build "$D/build-rp2350-$profile" --parallel 4
done
python3 -B challenges/misc/signal-box/firmware/security/check_recovery_builds.py
```

The explicit acknowledgment is required to build reopen. **Do not flash the
unsigned CMake UF2 outputs.** Host signing/encryption below uses picotool 2.3.1,
not the ordinary build's picotool 2.1.1.

`check_recovery_builds.py` checks the ELF's first runtime-init pointer, then uses
new disposable keys to prepare a snapshot, exercise bounded archive extraction,
compare all restored files and rebuild all seven UF2s. Temporary test keys are
removed; persistent keys, USB, GPG passphrases and hardware are not accessed.
This test is not a substitute for the encrypted USB restore using real lab keys.

## Prepare the persistent-key snapshot

```sh
python3 -B challenges/misc/signal-box/firmware/security/prepare_recovery.py
```

This helper internally reads the original off-repo sacrificial bundle, verifies
it, and creates a new owner-only timestamped directory beneath:

```text
~/.local/share/noco-ctf-2026/recovery-bundles/
```

It never regenerates AES shares/salt or rewrites the original key directory.
It emits no key bytes or passphrases to stdout. Failures leave only private
partial output; the backup validator will reject an incomplete snapshot.

The **37-file** prepared allowlist contains:

- Original seven data/key files, original manifest as `ORIGINAL-SHA256SUMS`, and
  a new full-bundle `SHA256SUMS` (the original `probe.elf` remains historical).
- Three new source ELFs and six separately sealed ELF/UF2/inspection triples.
- Encrypted closed ELF/UF2/inspection files.
- Approved `policy.json`, a frozen `PROVISIONING-PLAN.md`, `binding.json`, and
  `BUNDLE-README.txt` containing the no-flash/private-artifact warning.

The binding includes device/purpose, SHA256(X_BE32||Y_BE32) signing fingerprint,
source/plan/policy/original-manifest identities and exact picotool executable
hash. The public PEM is checked against the private key; every image's embedded
signer is checked against that fingerprint, not merely against itself.

Flash variants are sealed with `--clear`, then relocated to flash storage; the
ROM load map copies the authenticated application to SRAM. Direct SRAM variants
are **separately sealed without whole-SRAM clearing**, avoiding an unproven
clear-over-in-place-source case. Their lack of clearing is recorded explicitly:
keep them private and do not claim warm-memory confidentiality from them.
Use only the reviewed UF2s in future approved hardware stages. The sealed ELF
files retain SRAM physical addresses; a `-flash.elf` name describes its intended
UF2 storage, not permission to load that clearing ELF directly into SRAM.

The helper verifies signatures, role markers, ARM Secure UF2 headers, unique
block addresses, 2 MiB flash/SRAM bounds, load maps, vectors and entry/stack
addresses. It also checks absence of the plaintext canary in encrypted outputs.
It emits **no loadable OTP JSON**, activation/lock recipe, rollback metadata or
device command. Exact staged write artifacts remain a separate review gate.

## Back up and restore — passphrase stays in your terminal

Use the exact snapshot directory printed by preparation:

```sh
bash challenges/misc/signal-box/firmware/security/backup_sacrificial.sh \
    /absolute/path/to/the/prepared-snapshot
```

This validates the complete allowlist, owner permissions, manifest and binding,
then streams encrypted output to the UUID-checked NOCO_BACKUP USB. It prints the
exact expanded restore command, equivalent to:

```sh
python3 challenges/misc/signal-box/firmware/security/restore_sacrificial.py \
    --prepared --bundle-dir /absolute/path/to/the/prepared-snapshot \
    /run/media/bjames/NOCO_BACKUP/noco2026-sacrificial-9423D016AADE5950-TIMESTAMP.tar.gz.gpg
```

Retrieve the passphrase from Bitwarden locally. Do not paste it into chat,
arguments, environment variables or files. Restore authenticates GPG before
extraction, checks all 37 members, revalidates bindings and signatures on the
actual restored UF2s (not merely saved inspection text), and rebuilds six signed
UF2s plus the encrypted closed UF2 using recovered keys and the exact reviewed
tool. Private staging is removed before a public success receipt is written.

The original eight-file backup remains supported by the old no-argument backup
and non-`--prepared` restore invocation. Do not mistake its earlier PASS for
verification of this new snapshot. Neither format's restore PASS authorizes
flashing or OTP writes.

## Remaining gates

The operator completed the expanded encrypted USB restore at
**2026-09-11 04:28 UTC**: all 37 files and recovered-key image rebuilds passed;
private staging was removed. [KEY-RECOVERY.md](KEY-RECOVERY.md) records the archive,
receipt and transcript-based evidence. Next review exact per-stage write
artifacts, signed image hardware behavior, real
SWD denial/reopening, warm SRAM exposure and BOOTSEL recovery. The first approved
signed plaintext recovery UF2 load/readback has passed after a verified 2 MiB
backup. The operator subsequently reported normal LED behavior and UART profile
`recovery` with CRITICAL=0, DEBUGEN=0 and DEBUGEN_LOCK=0x10f. Recovery execution
passes; signature enforcement and SWD denial are not established by that output.
See [SACRIFICIAL-BOARD.md](SACRIFICIAL-BOARD.md).
No signing-root
fuses, debug-default fuses, page locks or other OTP data have been programmed.
See [PROVISIONING-PLAN.md](PROVISIONING-PLAN.md) for the staged approval holds.
