# Sacrificial key recovery — USB restore verified

**No OTP writes are authorized by this document.** Persistent sacrificial-test
keys exist, and the operator's terminal transcript confirms successful full USB
restore and recovered-key packaging verification. All eight files matched the
working bundle, the restored keys rebuilt a signature-verified encrypted probe,
and the plaintext marker remained absent. Private staging was removed.
Production/event credentials have not been generated.

## Working bundle

Owner-only directory (`0700`), files `0600`, outside the repository:

```text
~/.local/share/noco-ctf-2026/keys/sacrificial-9423D016AADE5950/
  signing.pem       secp256k1 private key, sacrificial tests only
  public.pem        corresponding public key
  aes-share.bin     exact 128-byte four-way AES key share
  iv-salt.bin       16-byte salt for this board
  probe.elf         diagnostic SRAM payload, not a shipping challenge
  metadata.json     device identity, purpose, tool versions, creation timestamp
  README.txt        recovery context and restrictions
  SHA256SUMS        hashes of the seven other files
```

Never regenerate or overwrite these keys in place. They are independent of the
old disposable `/tmp/signal-box-security-lab-*` keys and must not become the
production/event keys. The manifest detects accidental corruption, not malicious
replacement. It and all secret files stay outside Git.

The initial encrypted probe from these persistent keys is under:

```text
~/.local/share/noco-ctf-2026/artifacts/sacrificial-9423D016AADE5950-initial/
```

Its signature and plaintext-canary checks pass, but it must not be flashed
before OTP/recovery review. The reusable RAM ELF is included in the bundle so
restored keys can be tested with picotool 2.3.1 without depending on a disposable
build directory. The firmware was built with SDK 2.2.0 and a 2 MiB flash limit.

## Independent backup destination

The operator uses Bitwarden without file attachments. Store a long, randomly
generated **archive passphrase** in a private Bitwarden Secure Note, not in chat,
a shell command argument, an environment variable, or a file beside the archive.
This passphrase is separate from the firmware signing/encryption keys.

The operator explicitly authorized reformatting the former Windows-installer
USB. It is now a GPT/exFAT backup drive:

- Drive: Survivor 3.0, serial `070849E1D3A07968`, 123964751872 bytes.
- Filesystem label: `NOCO_BACKUP`; UUID: `FFEB-102B`.
- Current mount: `/run/media/bjames/NOCO_BACKUP`.
- Write/read test passed; temporary test file removed.
- The RP2350 BOOTSEL drive was not modified.

**The USB filesystem itself is not encrypted.** Only encrypted GPG archives go
there. Plaintext keys and recovery staging remain in private directories on the
working machine. After verification, keep the USB separately and unplugged when
not needed. Losing both vault access and the archive passphrase prevents restore;
maintain Bitwarden account recovery separately from this USB.

## Create the encrypted backup in your own terminal

1. Generate a long random passphrase in Bitwarden and save it in a private item
   such as `NoCo CTF 2026 — sacrificial backup passphrase`.
2. From the repository root, run:

   ```sh
   bash challenges/misc/signal-box/firmware/security/backup_sacrificial.sh
   ```

3. Enter/confirm the passphrase at GPG's local terminal prompts. Do not send it
   to the assistant. The helper requires a real terminal, checks the mounted
   filesystem UUID, checks the bundle manifest, and archives only the eight
   expected files. GPG uses symmetric AES-256; it does not use a personal GPG
   signing key. No plaintext tar archive is written to USB.
4. On success, the helper prints the timestamped `.tar.gz.gpg` path. It syncs
   the filesystem and will not overwrite an older backup. A failed encryption
   leaves no final-named archive; its temporary ciphertext file is removed.

The script deliberately bypasses user GPG options and symmetric passphrase
caching. It never receives the passphrase through arguments or environment.
Its fixed board identity, working path, and USB UUID make it an operator helper
for this checkpoint, not a general production backup utility.

## Restore gate before OTP

Creating an archive is not enough. This gate has now passed: the operator
restored **from the USB** using the local GPG prompt and supplied the successful
terminal transcript. Repeat this procedure whenever the recovery bundle changes.
The verified archive is:

```text
/run/media/bjames/NOCO_BACKUP/noco2026-sacrificial-9423D016AADE5950-20260911T024539Z.tar.gz.gpg
```

Run in your own terminal from the repository root:

```sh
python3 -B challenges/misc/signal-box/firmware/security/restore_sacrificial.py \
  /run/media/bjames/NOCO_BACKUP/noco2026-sacrificial-9423D016AADE5950-20260911T024539Z.tar.gz.gpg
```

The helper defaults to `/tmp/signal-box-picotool-2.3.1/picotool/picotool`;
use `--picotool /path/to/picotool` if the pinned tool is elsewhere. It requires
a real terminal and prompts through GPG without caching the passphrase. It
performs these checks:

- Decrypt to a private local staging directory and require successful GPG
  integrity/authentication verification before extracting any archive members.
- Validate member names/types; extract only the expected regular files, with
  owner-only permissions. Never extract keys onto the exFAT USB.
- Verify `SHA256SUMS`, then compare the recovered files with the working bundle.
- Repackage the recovered `probe.elf` using the recovered keys and pinned
  picotool 2.3.1; require a verified signature and absent plaintext marker.
- Record successful restore evidence before proposing permanent OTP changes.

Successful output ends with `RESTORE PASS`. A timestamped receipt is saved under
`~/.local/share/noco-ctf-2026/recovery-verifications/`. It contains archive hash,
identity, tool version, and check results, not secrets. Private staging files
are removed after success or failure (normal deletion, not secure erasure).
No plaintext is written to USB and no device/OTP command is invoked. Archive
and member sizes are bounded, and symlinks, traversal, duplicate/missing files,
stale bundles, and manifest mismatches are rejected. Recovery tests cover these
guards; combined packaging/recovery unit tests currently total 26.

## Recorded restore evidence

The operator supplied `RESTORE PASS` and both preceding verification results:
all eight files matched, then recovered-key encrypted packaging passed signature
and plaintext-marker checks. The helper reported this receipt:

```text
~/.local/share/noco-ctf-2026/recovery-verifications/20260911T031003.491333Z-9423D016AADE5950.json
```

This checkpoint is based on the operator's terminal transcript; it proves the
host-side recovery workflow, not boot acceptance under an OTP policy. No flash
or OTP writes were performed by the restore helper.

[PROVISIONING-PLAN.md](PROVISIONING-PLAN.md) contains the organizer-approved
policy with unused-slot revocation removed, staged programming order and device
recovery/reuse tests. [RECOVERY-PROBES.md](RECOVERY-PROBES.md) now describes the
built lab variants and a separate 37-file prepared snapshot with exact image/key
bindings and the frozen policy. The helpers support its expanded allowlist and
size limits while retaining compatibility with the initial eight-file backup.
The expanded backup/restore has now passed separately, as recorded below.
Policy approval does not authorize programming. Keep older timestamped archives
and the original working key bundle; neither snapshot is a complete
post-provisioning recovery record.

## Expanded snapshot restore — operator-confirmed PASS

The operator supplied a successful `--prepared` restore transcript for:

```text
Working snapshot:
~/.local/share/noco-ctf-2026/recovery-bundles/sacrificial-9423D016AADE5950-prepared-20260911T042403.044323Z/
Encrypted USB archive:
/run/media/bjames/NOCO_BACKUP/noco2026-sacrificial-9423D016AADE5950-20260911T042729Z.tar.gz.gpg
Public receipt:
~/.local/share/noco-ctf-2026/recovery-verifications/20260911T042845.174674Z-9423D016AADE5950.json
```

GPG authenticated/decrypted the archive; all **37 files** matched the working
snapshot and integrity checks passed. Recovered keys rebuilt six signed
recovery/debug images and the encrypted closed probe. The helper reported
`RESTORE PASS. Private plaintext staging removed.` No flash or OTP writes occurred.

Evidence is the operator's terminal transcript; the receipt and private files
were not independently opened by the assistant. This completes the expanded
host backup/restore gate, not device boot/debug/recovery acceptance. Exact
staged write artifacts and separately authorized hardware tests remained pending
at that checkpoint; see handoff §13.16 onward for subsequent recovery tests.

## Separate hash-artifact backup — operator restore PASS

The first slot-0 hash data artifact has since been prepared and reviewed. Its
four files plus their bound recovery journal use a distinct `slot0-hash-v1`
five-member archive. `backup_sacrificial.sh --hash-artifact <exact-sidecar>`
selects it explicitly; `restore_signing_hash.py` handles its separate receipt.
See [HASH-ARTIFACT-RECOVERY.md](HASH-ARTIFACT-RECOVERY.md).

The original eight-/37-file validators, key bundles and verified archives are
unchanged. The current sidecar also remains unchanged and does not need
regeneration. This small archive contains **no private keys**; retain both old
key archives. The operator has now supplied a successful encrypted USB restore
transcript for this profile:

```text
Archive:
/run/media/bjames/NOCO_BACKUP/noco2026-sacrificial-9423D016AADE5950-slot0-hash-v1-20260912T155955Z.tar.gz.gpg
Receipt (operator-reported):
~/.local/share/noco-ctf-2026/hash-artifact-verifications/20260912T160235.789837Z-9423D016AADE5950.json
```

All four artifact files matched, their archived fifth journal validated, hash
rederivation/offline ECC checks passed, and the helper reported `HASH ARTIFACT
RESTORE PASS. Private plaintext staging removed.` Evidence is the terminal
transcript, not an independent assistant read of private files. This completes
the artifact-backup gate, not a new key-archive restore or OTP authorization.
See handoff §13.19 for this gate and §13.20 for the subsequent guarded writer's
source review. Separate hash-only write approval and fresh physical preflight
remain required; writer preparation performed no live device operations.
