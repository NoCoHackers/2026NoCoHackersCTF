# Signal Box — moving development to another computer

**On the new computer, read repository `AGENTS.md`, this note, then handoff §§13.22–13.23.**
This document records the move requirements; it does **not** create a migration
backup, verify a transfer, authorize device access or grant OTP programming
permission. No keys, archives, receipts or device state were accessed to write it.

## 1. Current state: do not repeat the hash write

| Item | State at handoff |
| --- | --- |
| Sacrificial DUT | Seeed XIAO RP2350, serial **9423D016AADE5950**, RP2350A A4/QFN60 |
| ROM identifier | `0xa8bfe860`; exact public-source/board-byte correspondence unconfirmed |
| Flash | **2 MiB**, installed signed plaintext `recovery` image |
| Last operation | Separately approved hash-only writer, operator-reported **`HASH_DATA_VERIFIED_HOLD_BEFORE_KEY_VALID`** |
| Programmed OTP | Slot-0 hash data, ECC rows **`0x0080–0x008f`** |
| Not programmed | KEY_VALID, signature enforcement, debug-disable policy, page locks, AES/salt, revocations, rollback |
| Spare slots / secret storage | Last verified blank by the operator-run hash writer |
| Last USB state | BOOTSEL; moving/powering the board invalidates assumptions about volatile state |
| Other hardware | Known-good wired DUT, batch and RP2040 tester remain untouched/unlocked |

Public signer fingerprint (not a private key):

`SHA256(X_BE32 || Y_BE32) = b8fbbab76f60c7226c7172025f325b3bcb19986df08ff177c605e0217abd80ce`

**Preserve the successful run and its permanent attempt latch. Never rerun the
hash writer, clear its latch, or treat all signing-storage rows as blank.**
The old unprovisioned recovery journal is historical evidence, not current OTP
state. Hash-only success does not prove signature enforcement or debug denial.

## 2. Critical gap: the existing USB archives are not a complete migration backup

The verified archives cover the original key bundle, prepared recovery bundle,
and the four-file hash artifact plus its **pre-hash recovery journal**. They do
**not** cover the later successful hash-write run or its permanent attempt latch.
They also do not carry the entire current Git working tree or pinned toolchain.

**Before retiring/wiping the old computer, securely transfer and verify the entire
private state tree, including `provisioning-attempts/`.** Keep the old machine and
all existing archives until the new machine's offline checks and migration
inventory comparison pass. A missing latch must not be interpreted as permission
to repeat an operation that already burned fuses.

The current backup helpers are exact-format validators, not general migration
archivers. Running `backup_sacrificial.sh` without arguments backs up the default
key bundle, **not everything**. Do not add arbitrary files to old bundles or
archives: that breaks their manifests/allowlists. Arrange a separate authenticated,
encrypted transfer (for example, verified-host-key SSH) or a separately reviewed
encrypted migration archive; no such transfer/archive has been made by this task.

## 3. Carry these three things separately

### A. The complete private repository working tree

Old checkout: `/home/bjames/ctf/2026NoCoHackersCTF`

At inspection:

- Branch: `signal-box`
- HEAD: `98a171061665fe5b841f31104ee55ae079ad0a81`
- Substantial work is **uncommitted**, including untracked RP2350/security files.

A fresh clone, `git bundle` alone, or `git diff` alone will **not** carry all this
work. Preserve the whole current worktree, its untracked source and Git metadata,
or first make an explicitly reviewed private source snapshot. No commit or push
was made for this migration note. Capture `git status --short` and HEAD when the
actual transfer occurs; compare on arrival. Preserve executable bits.

Important source locations:

- `challenges/misc/signal-box/SIGNAL-BOX-HANDOFF.md`
- `challenges/misc/signal-box/firmware/debug/` (including untracked `rp2350/`)
- `challenges/misc/signal-box/firmware/security/` (including all untracked files)
- Existing RP2040 debug/tester sources and the rest of this repository.

Keep the repository private: it contains event flags/solutions. Do not upload it
to public issues, gists, forks or registries. Keys remain **outside** the repository,
including its ignored directories, throughout transfer and extraction.

### B. The entire private state tree

Old root: **`/home/bjames/.local/share/noco-ctf-2026/`**

Transfer the whole tree rather than trying to reconstruct an allowlist from this
table. Entries below are the known important checkpoints, relative to that root:

| Path | Why preserve it |
| --- | --- |
| `keys/sacrificial-9423D016AADE5950/` | Original eight files: signing/private/public material, AES share, salt, probe and manifests |
| `recovery-bundles/sacrificial-9423D016AADE5950-prepared-20260911T042403.044323Z/` | **Final 37-file** restored snapshot, images and bindings |
| `recovery-bundles/sacrificial-9423D016AADE5950-prepared-20260911T041835.535047Z/` | Superseded snapshot: retain, do not mistake for final |
| `artifacts/sacrificial-9423D016AADE5950-initial/` | Earlier preserved packaged artifact |
| `provisioning-artifacts/slot0-hash-9423D016AADE5950-prepared-20260911T173747.602106Z/` | Unchanged reviewed four-file hash sidecar |
| `device-backups/sacrificial-9423D016AADE5950-before-recovery-20260911T044241.489487Z/` | Original/full-flash recovery checkpoint and audit |
| `device-backups/sacrificial-9423D016AADE5950-ram-recovery-20260911T163115.320929Z/` | Bound completed recovery round trip; `stage.json` must remain unchanged |
| `provisioning-attempts/slot0-hash-q5ytu_fj/` | Live read-only preflight checkpoint |
| **`provisioning-attempts/slot0-hash-v292yeja/`** | **Successful irreversible hash-write run, frozen payload, flash snapshots and checkpoints** |
| **`provisioning-attempts/slot0-hash-9423D016AADE5950.attempt.json`** | **Permanent no-retry attempt latch; retain unchanged** |
| `provisioning-attempts/slot0-hash-9423D016AADE5950.lock` | Wrapper lease file; retain, but an active OS lock is not transferable |
| `recovery-verifications/` and `hash-artifact-verifications/` | Historical scoped restore receipts; not transfer or write authorization |

Quiesce all tools before copying; do not copy during a write or while journals
are changing. Never run provisioning independently on both machines. Select one
active host after migration. Keeping a cold old-host copy is recovery protection,
not permission for a second writer.

Use private local Linux storage. Preserve directory mode **0700**, owner-only
files (normally **0600**) and stricter frozen-file modes such as **0400**. Ensure
the current operator owns the restored files. Verify a private per-file SHA256
inventory, membership and permissions on both computers; do not print private
contents or put the inventory inside a frozen allowlisted bundle.

Do not store plaintext private material on the exFAT USB, which cannot enforce
these ownership/mode rules. Only encrypted archives belong there. Archive
passphrases stay in Bitwarden and are entered locally—never in chat, command
arguments, environment variables, logs or plaintext files. No new secrets or
replacement signing keys should be generated to solve a migration problem.

### C. The exact pinned executable and reproducibility inputs

**Save the exact executable before `/tmp` is cleaned.** Version number alone is
not enough; existing artifacts bind its binary hash.

| Item | Old location / identity |
| --- | --- |
| Security picotool executable | `/tmp/signal-box-picotool-2.3.1/picotool/picotool` |
| **Executable SHA256** | **`eefcbd48c2c0fa825a8e2ea3e44239644194d79abff8eb082bc3914971e745e5`** |
| Public picotool source | `/tmp/signal-box-picotool-source-2DHfEu`, tag 2.3.1, commit `2041936441b48a3cc53ae3da9e805229fe8f4e18` |
| Pico SDK | `/tmp/signal-box-pico-sdk-2.2.0`, commit `a1438dff1d38bd9c65dbd693f0e5db4b9ae91779`; preserve required submodules |
| Earlier ordinary build tool | `/tmp/signal-box-picotool-2.1.1/picotool/picotool`; **not** the security/provisioning tool |
| Public ROM comparison copy | `/tmp/public-rp2350-rom-c6cdb171-bbbru2rf/`, ten files from commit `c6cdb1711f32c3e34faaebd58618a6d096dbd52e` |

Also retain useful build directories/logs until the new host is validated. Frozen
source ELFs/images are already in the 37-file bundle. Do not rebuild/reseal them
in place merely because the computer changed.

Store a durable copy of tools/source outside `/tmp` and outside key bundles;
recreate the expected paths on the new host before checks. Recompiling picotool
may change its hash even at the same version. Do not edit bindings, weaken hash
checks, or regenerate old artifacts to accept a replacement executable.

The inspected executable is **little-endian Linux ELF64 x86-64**. It directly
requires `libusb-1.0.so.0`, `libstdc++.so.6`, `libm.so.6`, `libgcc_s.so.1` and
`libc.so.6`. Its highest direct required version tags are `GLIBC_2.34`,
`GLIBCXX_3.4.29` and `CXXABI_1.3.9`; these are not a complete compatibility proof.
The old host reports Python **3.14.7** and glibc **2.43**—observations, not claimed
minimum requirements.

Use a compatible Linux x86-64 environment. Windows/macOS/ARM-native portability
has not been established. A Linux VM may be an option, but test file operations,
permissions and sealed-executable support offline first; no live USB passthrough
is needed for this migration validation. Linux memfd sealing/execution,
`/proc/self/fd`, `flock`, directory `fsync` and `CLOCK_BOOTTIME` are required by the
guarded writer. A failed compatibility check is a stop, not grounds for an
unsealed fallback.

Host dependencies include Python/PyYAML, Bash, OpenSSL, GnuPG, standard Linux
utilities (`findmnt`, `sha256sum`, etc.), libusb and the libraries above. Firmware
rebuilds additionally need CMake, Make and GNU Arm tools (`arm-none-eabi-gcc`,
`arm-none-eabi-readelf`). Do not assume matching tool names imply identical builds.

## 4. Paths are part of the existing evidence

Prefer the same username/home layout, particularly
`/home/bjames/.local/share/noco-ctf-2026/`; keeping the checkout at its old absolute
path is also the lowest-friction option. Helpers use `Path.home()`, and the hash
review/recovery audit includes absolute bundle paths. Existing USB restore helpers
also require **`/run/media/bjames/NOCO_BACKUP`**.

A different home path can break an otherwise byte-identical copy. Symlink tricks,
editing archived JSON, broad permission changes or bypassing validators are not
migration fixes. If preserving the layout is impossible, stop and prepare an
explicitly reviewed relocation/rebinding plan that preserves original evidence.
Do not rewrite the historical blank-state journal to describe the new device.

The existing restore tools are **verification drills**, not turnkey installation
onto an empty host: they compare against working bundles and remove temporary
plaintext after verification. A printed restore PASS does not mean a permanent
working tree was installed. If only encrypted archives remain, a separate bounded
bootstrap-recovery procedure is needed; do not improvise an unchecked extraction
or disable the reference comparisons.

## 5. Independent encrypted USB copies to retain

Survivor3.0 serial **070849E1D3A07968**, label **NOCO_BACKUP**, exFAT UUID
**FFEB-102B**, old mount **`/run/media/bjames/NOCO_BACKUP`**. Do not format or
repartition it. Device names such as `/dev/sdb` are transient; identify by serial
and filesystem UUID. All names below are relative to the USB root:

- Original eight-file archive, restored PASS:
  `noco2026-sacrificial-9423D016AADE5950-20260911T024539Z.tar.gz.gpg`
- Final 37-file archive, restored PASS:
  `noco2026-sacrificial-9423D016AADE5950-20260911T042729Z.tar.gz.gpg`
- Four hash files + pre-hash recovery journal, restored PASS:
  `noco2026-sacrificial-9423D016AADE5950-slot0-hash-v1-20260912T155955Z.tar.gz.gpg`
- Extra default key archive from a malformed multiline paste; retain, but **no
  restore PASS was claimed for this copy**:
  `noco2026-sacrificial-9423D016AADE5950-20260912T155834Z.tar.gz.gpg`

Historical receipts are documented in `firmware/security/KEY-RECOVERY.md`. None
covers the new computer or successful hash-write journal/latch. Confirm Bitwarden
access and account recovery before depending on these archives. Do not send the
archive passphrase to the assistant. Use single-line operator commands.

## 6. New-host acceptance: offline first, DUT disconnected

1. Verify the transferred repository, private inventory/permissions, exact tool
   hash and required paths. Keep the old copies. Do not run image preparation,
   manifest regeneration, restore installers or device commands as a shortcut.
2. From the repository root, run each of these **individual single-line commands**:

```sh
python3 -m unittest discover -s challenges/misc/signal-box/firmware/security -p 'test_*.py'
python3 tools/validate.py
python3 challenges/misc/signal-box/firmware/security/check_key_valid.py
```

Expected previous results: **133 host tests**, repository validation **4 bundles /
4 entries / 0 errors / 0 warnings**, and **8 SDK constants + 2 explicit-file
simulations PASS**. These alone do not verify the transferred private inputs.

3. After the private paths/tool are restored, these are also **file-only**:

```sh
python3 challenges/misc/signal-box/firmware/security/write_signing_hash.py --offline-check
python3 challenges/misc/signal-box/firmware/security/check_hash_writer.py
```

They validate the old unchanged artifact/key/recovery bindings and sealed-tool
operation without reading the board. The name `write_signing_hash.py` does not
make `--offline-check` a writer: **do not replace that mode with `--preflight` or
`--program-hash-only`**. Its original live blankness precondition is obsolete for
this now-enrolled hash. No current KEY_VALID live preflight exists yet.

4. Separately verify the transferred successful hash run and sticky latch against
   the old-host private inventory. The file-only commands above do **not** validate
   those new predecessor files. Record the new-host migration results accurately;
   do not relabel old restore receipts as new evidence.
5. Only after these checks should development resume. Any device connection,
   live preflight, recovery boot test or later irreversible stage needs its own
   appropriate authorization. A migration request is not that authorization.

No new-host checks or migration transfer have been performed while writing this
note. An error means stop and diagnose; never remove the hash latch, weaken
private/path checks or rerun a completed provisioning stage.

## 7. Hardware reminder for the move

Label the sacrificial DUT separately from the known-good wired DUT and RP2040
tester. Keep all disconnected during initial host validation. A genuine cold
cycle must remove fixture/UART backfeed; adapter **VCC stays disconnected**, and
DUT/tester 3V3 rails must not be joined.

UART is **3.3 V, 115200 8N1**: DUT D6/GPIO0 TX → adapter RX, D7/GPIO1 RX ← adapter
TX, common GND. UART device names will change on the new host. If later authorized,
UART `bootsel` enters ROM mode; the BOOTSEL disk does not need mounting for
picotool. Do not automatically issue `run`, `eeprom`, `protected-rw`, `wp-check`,
flash loads, reboot or OTP commands to prove the move worked.

## 8. Resume development here

The next task is **preparing** a private KEY_VALID-only artifact bound to the
preserved original keys, final recovery bundle, hash sidecar, actual successful
hash run/latch and exact tool. Then independently back up/restore it and
implement/review a separate guarded writer. None of that activation implementation
or backup exists yet.

The reviewed transition is three physical rows **`0x004b–0x004d`, each raw 0 → 1**,
12 padded raw transport bytes—not ECC and **never `0x010101`**. The second set copy
already establishes majority; partial state is not permission to retry. KEY_VALID
can affect signature-key parsing before global enforcement. Read
`firmware/security/KEY-VALID-STAGE.md` before designing any executor.

**Hold before KEY_VALID.** Signature enforcement, debug/route policy, root-page
protection, AES/salt, secret locks and hardware acceptance remain later separately
approved stages. No spare-slot revocation; permanent ARM-only post-event reuse and
event-specific key publication are accepted policy, not permission to burn ahead.
Participant firmware, EEPROM provisioning, five scored flags/manifests and
independent optical decoding also remain unfinished.

### Paste into a fresh assistant session

> Read AGENTS.md, challenges/misc/signal-box/SIGNAL-BOX-MIGRATION.md, and
> SIGNAL-BOX-HANDOFF.md §§13.22–13.23. This is a new-host migration: first assess
> and verify copied files/tools offline, without device access. Sacrificial serial
> 9423D016AADE5950 already has its slot0 hash programmed; KEY_VALID remains at the
> pre-activation hold. Preserve the successful slot0-hash-v292yeja run and permanent
> hash-attempt latch. Do not rerun the hash writer, rewrite frozen bundles/journals,
> bypass path/tool checks, expose secrets or assume existing USB archives contain
> the latest run/latch. New KEY_VALID artifact/writer preparation is the next
> development task, not authorization to activate or change any other fuse.
