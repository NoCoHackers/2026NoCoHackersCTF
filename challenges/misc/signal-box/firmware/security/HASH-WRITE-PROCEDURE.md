# Sacrificial slot-0 hash writer — review before live use

**Completed once under separate approval; HOLD before KEY_VALID.** The operator
reported `HASH_DATA_VERIFIED_HOLD_BEFORE_KEY_VALID` from the reviewed writer after
explicit hash-only authorization and local confirmation; see handoff §13.22.
This is operator-reported verification, not an additional assistant readback.
Preserve the attempt latch and journal; do not repeat this procedure or clear the
latch. The all-blank candidate baseline below describes the historical first-write
precondition, not the now-programmed device. No next-stage write is authorized.

`write_signing_hash.py` is limited to serial **9423D016AADE5950**, RP2350 A4,
ROM `a8bfe860`, and the exact restored §13.17 artifact. It has no configurable row,
length, key, raw-mode, offset, activation, revocation, lock, AES or reset option.
There is exactly one possible write command: ECC BIN input, start row `0x0080`,
32 bytes/16 rows, selected by serial. It never executes argv from JSON.

## Modes and permissions

- `--offline-check`: verifies files, key/artifact bindings and pinned tool using
  existing file-only helpers. **No device access.** This is the only mode used
  while preparing/reviewing the writer.
- `--preflight`: **live read-only** identity, policy, blankness and full-flash
  checks. Separate permission and operator BOOTSEL entry are required. It never
  prompts for writing and never creates an attempt latch.
- `--program-hash-only --ack-backup-restored`: **irreversible**. Requires separate
  explicit hash-data-only approval, all three streams attached to a real local
  terminal, and an exact typed confirmation after initial live checks. It runs
  fresh checks again after confirmation, not merely reusing a saved preflight.

The backup acknowledgment is an operator attestation, not machine proof of a
restore and not an approval token. Receipts are not opened or treated as
programming authority. See [KEY-RECOVERY.md](KEY-RECOVERY.md) for the supplied
operator evidence. Do not provide the typed confirmation through an agent tool,
pipe, argument, environment variable or simulated terminal.

Offline command (safe for this preparation stage):

```sh
python3 challenges/misc/signal-box/firmware/security/write_signing_hash.py --offline-check
python3 challenges/misc/signal-box/firmware/security/check_hash_writer.py
```

**Only after separately approved live use**, the operator must enter UART
`bootsel` (or physical BOOTSEL); normal debug firmware has no USB stdio interface.
Use single-line commands. Live modes are not implied by the offline command
above. Keep sole control of the board; do not run other picotool/SWD tools,
change wiring, suspend the laptop, unplug or power-cycle during a write.

## Before the one possible write

1. Revalidate the fixed sidecar, original/restored matching key pair, actual
   stored image signatures, reviewed row encoding and exact picotool hash.
   Source artifacts and their archives remain unchanged.
2. Durably publish the private state root (including syncing its parent) and
   acquire a nonblocking per-board filesystem lease. Concurrent instances of
   this wrapper cannot operate on the same board. This does **not** prevent
   unrelated programs or another physical operator from touching it.
3. Reject any existing attempt latch before programming. No override, reset,
   automatic retry or resume mode exists. Copy the 32-byte payload to a fresh
   owner-only run directory and freeze it read-only.
4. Require the exact BOOTSEL identity and unprovisioned defaults: ARM, both
   architectures available, secure boot=0, debug=1, Secure debug=1, expected ROM.
   Re-read all 34 individual raw policy rows and require all 256 candidate
   signing/AES/salt rows physically zero. ECC zero alone is insufficient.
5. Save and verify all 2 MiB of flash privately; require its hash to match the
   tested recovery image recorded in the completed round-trip journal. Repeat
   identity/raw state after the save.
6. Program mode displays the public signer fingerprint and asks for the exact
   phrase `PROGRAM HASH ONLY 9423D016AADE5950`. Cancellation, EOF or mismatch
   stops without a write. Revalidate working inputs and repeat the full live
   preflight afterward; no human wait follows these final checks.
7. Write/fsync the intent checkpoint and an exclusive, durable attempt latch
   **before** calling the one writer. Persist an armed/uncertain checkpoint with
   `write_may_have_occurred=true` before launch, so a crash during the call cannot
   leave the latest complete record claiming no possible write. Reject a final raw check older than ten
   seconds from its start, measured with Linux BOOTTIME so suspend expires it. This minimizes
   but cannot eliminate the gap between separate USB commands.
8. Copy and hash-check the payload and executable into Linux sealed memfds;
   prevent writes, growth and shrinking. The child executes and reads inherited
   descriptors via `/proc/self/fd`, never reopened mutable input paths. The data
   descriptor is exactly 32 bytes. Recheck the preflight deadline after sealing,
   immediately before spawn. Invoke only ECC BIN load at `0x0080` with the fixed
   serial. No parent timeout is imposed on the irreversible call. USB errors or
   interruption can leave partial state: never auto-retry. No insecure fallback
   is allowed if this host lacks memfd sealing/execution support.

## Verification and mandatory hold

The binary loader must exit zero, emit exactly one unambiguous `Verified OK`,
and emit no diagnostics. Pinned picotool can return zero on a mismatch, so exit
status is not enough. Its binary-load verification uses the ROM's ECC read path.

Then the wrapper independently checks:

- Exact predicted raw24 encodings for all 16 written rows, without correction or
  majority voting. Any different physical bit, including BRP/ECC bits, stops.
- The other 48 page-2 rows and all 192 candidate secret-page rows still zero.
- All 34 policy rows unchanged, including KEY_VALID/KEY_INVALID and the selected
  lock pairs for pages 0, 1, 2, 29, 30 and 31—not every device page.
- A separate `otp get -e` view of exactly those 16 rows. **This picotool path
  reads raw pages and checks parity in host software; it is not a second ROM
  ECC read.** Invalid-ECC warnings fail even if the displayed low 16 bits match.
- Full flash unchanged and final identity/raw state still matching.

Raw reads use `-c 1 -r -n --ser <exact-serial>` **before** the explicit row
addresses. The pinned parser can consume a trailing `--ser` as another row
selector, so it must not be appended after that repeatable group. Require one
value per requested row with complete coverage; reject stdout diagnostics even
if identity/values otherwise match. No raw key-page output is
printed or logged; unexpected values are suppressed. `otp get` internally reads
whole pages but only selected rows are displayed. Native stdout/stderr is not
reprinted on failure.

Success ends in **`HASH_DATA_VERIFIED_HOLD_BEFORE_KEY_VALID`**. This is data
verification only. **Do not activate the key, enforce signatures, disable debug,
lock pages, write AES/salt, reboot or provision another board as a continuation.**
Each later stage needs its own reviewed artifact, approval and tests.

## Journal, latch and failure handling

Private state lives under `~/.local/share/noco-ctf-2026/provisioning-attempts/`.
Each run keeps its frozen payload, full-flash snapshots and exclusive checkpoint
files. A successful read-only preflight still requires a new preflight during
program mode; it grants no authorization.

The per-board latch is `slot0-hash-9423D016AADE5950.attempt.json`. Once created,
it remains even if a later error happens before any bit is written. On any
failure after the native call might have started, the journal states that write
state is uncertain. A power loss can leave only the intent/latch; treat that as
uncertain too. Never infer untouched OTP from an error exit or missing PASS.
Do not delete/clear the latch or reuse a run directory to retry. Investigate
with a separately reviewed read-only plan first; a new attempt needs explicit
replanning. The wrapper has no automatic repair path.

The lease, latch and sealed inputs are safeguards on a trusted Linux host, not
defenses against a hostile administrator, interpreter or dynamic libraries.
`check_hash_writer.py` tests the actual sealed executable using only `version`
and an explicit-file OTP simulation; it never enumerates devices.

Device tests use simulated devices and mocked native processes; they do not
validate physical fuse programming. The public-source/board-ROM byte correspondence
remains unconfirmed. No write approval follows from passing these tests.
