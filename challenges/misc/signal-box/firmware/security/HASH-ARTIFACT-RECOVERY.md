# Signing-hash artifact backup — separate five-file profile

**Host-only. No device or OTP operations.** The `slot0-hash-v1` profile is
explicitly separate from the unchanged eight-file initial and 37-file prepared
key formats. It does not replace either key archive and does not authorize OTP.

## What is backed up

The archive contains exactly these five flat regular files:

```text
slot0-hash.ecc.bin
review.json
README.txt
SHA256SUMS
recovery-round-trip.json
```

The first four are the unchanged reviewed artifact. The fifth is a frozen copy
of the recovery journal whose hash is already bound by `review.json`. Including
it avoids relying on the only host copy of that evidence. No signing private
key, AES share, salt, flash dump or new loadable OTP JSON is included.

The new helper freezes these files into private local staging, verifies the
copy, and streams a gzip tar to GPG. Only ciphertext reaches USB. Existing
`prepare_recovery.py`, `restore_sacrificial.py`, their allowlists and the artifact
producer are unchanged; the current reviewed sidecar need not be regenerated.

## Run locally, never through an agent tool

Use the Bitwarden-held passphrase in your own terminal. Never place it in chat,
arguments, environment variables or files. Mount the existing `NOCO_BACKUP`
exFAT USB (UUID `FFEB-102B`) at its established path first.

```sh
SECURITY=challenges/misc/signal-box/firmware/security
ARTIFACT="$HOME/.local/share/noco-ctf-2026/provisioning-artifacts/slot0-hash-9423D016AADE5950-prepared-20260911T173747.602106Z"
bash "$SECURITY/backup_sacrificial.sh" --hash-artifact "$ARTIFACT"
```

The script creates a new timestamped ciphertext archive beginning
`noco2026-sacrificial-9423D016AADE5950-slot0-hash-v1-`. It does not overwrite earlier
archives and prints the **exact restore command** for that new archive. Run that
printed command in the same local terminal. Its shape is:

```text
python3 .../restore_signing_hash.py --artifact-dir <exact-sidecar-directory> <new-USB-archive>
```

Do not pass the sidecar to the default key-bundle mode, and do not pass this
five-file archive to `restore_sacrificial.py`. Both wrong-profile paths reject
rather than guessing or relaxing file allowlists.

## Restore acceptance

`restore_signing_hash.py`:

1. Requires a local TTY for restore, the exact private artifact directory, the
   correct USB identity, profile prefix and bounded ciphertext size.
2. Authenticates/decrypts through GPG **before extraction**. The shared decryptor
   caps output at 256 KiB; decompressed tar size is separately capped at 256 KiB.
3. Extracts exactly five bounded regular, nonsparse files into private local
   staging. Unknown/duplicate/missing members, traversal and links are rejected.
4. Compares the four restored artifact files byte-for-byte with the working
   sidecar. Revalidates them using the **restored journal**, the preserved key
   pair, actual stored image signatures, pinned tool and file-only ECC simulation.
   The live journal is not a restore dependency.
5. Rechecks the encrypted archive hash and removes staging. It writes/flushes/
   syncs a private pending receipt, publishes it atomically without replacing an
   existing file, then syncs the private receipt directory under
   `~/.local/share/noco-ctf-2026/hash-artifact-verifications/`.

Success reports **`HASH ARTIFACT RESTORE PASS`** and exits zero. The receipt records
five restored files, four artifact comparisons, the bound journal and rederived
hash checks. It explicitly says no key archive was restored, no hardware was
validated and programming is not authorized. This receipt cannot substitute for
the earlier key-restoration gate or for fresh device preflight. A pending
`.partial` file is not a successful receipt. If directory synchronization fails
**after** publication, the helper reports that a receipt exists but does not
print its final PASS; investigate and rerun before proceeding. A later terminal
output error also reports the published state and exits nonzero. Treat any FATAL
as a stop, even if a PASS line appeared before an output failure.

Keep the existing key archives alongside this one. Verification requires the
preserved/recovered working key bundles and four-file sidecar at the pinned
locations. This is a restore-verification helper, not an automatic installer for
a host that has lost all working directories; reconstruct those inputs from the
separate archives in a controlled recovery session first.

## Offline tests versus the operator gate

```sh
python3 -m unittest discover -s "$SECURITY" -p 'test_*.py'
python3 "$SECURITY/check_hash_backup.py" --artifact-dir "$ARTIFACT"
```

The integration command exercises real working inputs and real file-only
picotool checks through a locally generated five-file archive, extraction,
comparison and restored-journal validation. It verifies source preservation and
cleans up its private staging. It **does not** encrypt, read/write USB, test a
passphrase or produce an operator restore receipt. A genuine operator-encrypted
USB backup and `HASH ARTIFACT RESTORE PASS` are required separately; the operator
has now completed that gate for the unchanged reviewed sidecar (see below).

Even after that PASS, exact writer/command review, separate **hash-data-only**
write approval, fresh serial/A4/ROM and raw baseline/physical-blankness preflight,
and independent ECC/raw readbacks remain mandatory. Hold before KEY_VALID.

## Operator-confirmed restore

The operator restored
`noco2026-sacrificial-9423D016AADE5950-slot0-hash-v1-20260912T155955Z.tar.gz.gpg`
from the designated USB and supplied `HASH ARTIFACT RESTORE PASS`: all four
artifact files matched, the fifth bound journal validated, hash rederivation and
offline ECC checks passed, and plaintext staging was removed. The transcript
reported receipt `20260912T160235.789837Z-9423D016AADE5950.json` in the private
hash-artifact-verifications directory. No receipt or private file was opened by
the assistant. See [KEY-RECOVERY.md](KEY-RECOVERY.md) for exact paths. No OTP
programming or additional device-stage authorization follows from this PASS.
