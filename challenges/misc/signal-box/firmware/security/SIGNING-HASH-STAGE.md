# Slot-0 signing hash — offline data-stage preparation

**Artifact preparation does not authorize programming.** The separate guarded
hash writer has now been used once with explicit approval and local confirmation;
the operator reports verified success (handoff §13.22). Preserve the unchanged
sidecar and permanent attempt latch. **Hold before KEY_VALID; do not repeat the
hash write.** This artifact sets only signing-hash data. It does not mark a key
valid, enforce signatures, disable debug, revoke spare slots, write locks, or
install AES/salt data.

## Scope and files

`prepare_signing_hash.py` emits a **new four-file private sidecar**, outside Git:

| File | Meaning |
| --- | --- |
| `slot0-hash.ecc.bin` | Exactly 32 digest bytes, ECC input for 16 rows `0x0080–0x008f`. |
| `review.json` | Exact row expectations, bindings, proposed arguments and unsatisfied gates. **Not picotool JSON.** |
| `README.txt` | Warning and stop/readback rules. |
| `SHA256SUMS` | Exact three-member content manifest. |

No device writer is embedded in this sidecar. The separate guarded
`write_signing_hash.py` and its review boundaries are documented in
[HASH-WRITE-PROCEDURE.md](HASH-WRITE-PROCEDURE.md). The binary alone contains no
serial or approval gate. Never drag it to BOOTSEL or use ordinary `picotool load`
on it; live use of the guarded writer still requires separate approval.

The CLI pins the final restored snapshot and completed round-trip journal for
serial **9423D016AADE5950**; there is no alternate/disposable-bundle CLI option.
Original keys, the 37-file snapshot, its USB archive and the journal are read-only
inputs. Nothing copies private signing/AES/salt material into the sidecar.
The matching original key pair, manifest bindings, actual stored image signatures,
exact tool hash and completed recovery evidence are checked before publication.

```sh
SECURITY=challenges/misc/signal-box/firmware/security
python3 "$SECURITY/prepare_signing_hash.py" \
  --output-dir "$HOME/.local/share/noco-ctf-2026/provisioning-artifacts/slot0-hash-REVIEW-ID"
python3 "$SECURITY/prepare_signing_hash.py" \
  --check-dir "$HOME/.local/share/noco-ctf-2026/provisioning-artifacts/slot0-hash-REVIEW-ID"
```

The parent directory is created owner-only; a destination must be new. Failed
partial output stays private and is not acceptable for programming. The checker
reconstructs the entire expected record/payload, rather than trusting a rehashed
manifest. A source, tool, bundle or journal change invalidates the binding;
prepare a new sidecar after review, never rewrite the verified input snapshot.

## Encoding and independent offline check

Hash **X_BE32 || Y_BE32** from the matching secp256k1 key pair. Do not hash the
SEC1 `04` prefix, compressed point, PEM or DER wrapper. The file stores the raw
32 digest bytes, not its 64-character hex spelling. Row `i` receives
`digest[2*i] | digest[2*i+1] << 8` through the ROM's ECC16 input path.

The review record includes expected raw24 encodings for initially blank rows.
Parity follows pinned picotool `otp_calculate_ecc`; upper BRP bits are zero for
this fresh-row encoding. **Corrected ECC readback alone is insufficient**: raw
physical readback must also equal the prediction, with no extra/corrected bits.

The helper cross-checks the complete simulated 4096-row raw image using
`picotool otp dump` with an **explicit JSON file input**. Upstream's
`otp_dump_command::get_device_support()` returns `none` for that path; its
execution uses memory callbacks, not a device connection. It checks that only
the intended 16 rows change. The temporary JSON and whole-OTP simulation are
removed and are **not** published as loadable artifacts.

```sh
python3 "$SECURITY/check_signing_hash.py"
python3 -m unittest discover -s "$SECURITY" -p 'test_*.py'
```

The real-tool integration additionally compares all 65,536 possible ECC16 input
words with file-only picotool simulations. It uses no real keys or device reads.
This validates host encoding and row mapping, not physical fuse programming.

## Future write boundary — NOT executed by these tools

The proposed argument list lives in `review.json` for review, not execution.
It specifies ECC, numeric start row `0x0080`, the exact 32-byte BIN and the target
serial. BIN input otherwise defaults to **raw** mode: omitting ECC is unsafe.
No included OTP definitions, named-selector expansion, JSON loading, raw writes,
redundancy options, force options or automatic next-stage activation are allowed.

Pinned picotool 2.3.1 has two important limitations:

- Its binary OTP load reads back and prints `Verified OK`, but a mismatch can
  print a diagnostic and still return exit 0. **Exit status alone is not PASS.**
- Its JSON OTP load returns before that verification path. Generating a combined
  sealing/encryption JSON and loading it as a shortcut is prohibited.

Before any write: separately review the execution path and authorize **hash data
only**, verify a fresh encrypted backup/restore containing these new artifacts,
re-identify serial/A4/ROM, and re-read all 34 policy rows plus all 256 candidate
key-storage rows raw. Require physically blank target rows, not just ECC zero.
Generation and the historical recovery journal are **not** a live preflight.

After the data write: require the tool's positive verification message, then
independently read **each** of the 16 rows in ECC and raw modes with exact row
coverage. Compare both expected encodings. Check the remaining 48 page-2 rows
and all 192 secret-page rows remain blank, and every policy row is unchanged.
Keep raw-read option order `-c 1 -r -n` with explicit row addresses.
Stop on any partial write, disagreement or unexpected bit; do not retry, OR in
corrections, activate the key, enroll another slot or lock pages automatically.

**Hold before KEY_VALID.** Separate approval and verification are required for
activation and every subsequent stage in [PROVISIONING-PLAN.md](PROVISIONING-PLAN.md).
Unprovisioned recovery passing does not substitute for signed/unsigned/wrong-key/
tampered recovery tests under enforced trust or for physical SWD tests.

## Backup gate passed — write review/approval remain outstanding

The earlier 37-file encrypted restore remains valid and unchanged. This sidecar
is **not covered** by that archive. The explicit `--hash-artifact` backup profile
now archives its four files plus their bound recovery journal as five members,
without changing the eight-/37-file allowlists or the artifact producer.
See [HASH-ARTIFACT-RECOVERY.md](HASH-ARTIFACT-RECOVERY.md) for the local-terminal
backup and separate `restore_signing_hash.py` workflow. Keep the key archives;
this small archive contains no private keys. No sidecar regeneration is needed.

Host archive tests do not complete the operator gate. The operator has now
supplied a genuine encrypted USB restore transcript ending in `HASH ARTIFACT
RESTORE PASS` for this unchanged sidecar; see
[KEY-RECOVERY.md](KEY-RECOVERY.md) for archive and receipt paths. This completes
the backup gate only. The guarded writer's source review is documented separately;
no live preflight or hash-only write has been authorized or performed by that
preparation. Fresh physical checks and separate write approval remain mandatory.
The passphrase stayed local.

## Pinned public-source seams

Reviewed against picotool tag 2.3.1, commit
`2041936441b48a3cc53ae3da9e805229fe8f4e18`, `main.cpp`:

- `sign_guts_*`: generated `bootkey0` receives the digest bytes.
- `otp_calculate_ecc`: parity encoding for a fresh 16-bit row.
- `process_otp_json`: byte-array handling, ECC row sizes and sequence extent.
- `otp_dump_command`: explicit-file, no-device simulation branch.
- `otp_load_command`: `--ecc` / `--start_row`, binary readback and exit-status caveat.

The board ROM reports `a8bfe860`; exact correspondence to available public ROM
source is still unconfirmed. Do not convert host simulation into a claim of
hardware validation or security enforcement.
