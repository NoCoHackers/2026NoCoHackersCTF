# Slot-0 KEY_VALID — offline stage review

**No KEY_VALID programming or live preflight is authorized.** The operator's
§13.22 transcript reports a successful hash-data-only write. It does not authorize
activation. This investigation prepares a public row model, tests and the next
stage's contract—not a writer, loadable artifact, private predecessor validation
or backup receipt. The board and the hash writer's permanent latch are untouched.

## Exact proposed transition

Target remains sacrificial **9423D016AADE5950**, RP2350 A4, ROM `a8bfe860`.
Only these three physical rows may change:

| Physical row | Register | Before raw24 | After raw24 |
| --- | --- | --- | --- |
| `0x004b` | BOOT_FLAGS1 | `0x000000` | `0x000001` |
| `0x004c` | BOOT_FLAGS1_R1 | `0x000000` | `0x000001` |
| `0x004d` | BOOT_FLAGS1_R2 | `0x000000` | `0x000001` |

This is **RBIT-3 whole-row repetition**, not ECC and not byte-triplication.
The in-memory raw transport model is exactly **12 bytes**: three little-endian
32-bit words valued 1, each with zero high-byte padding. A packed nine-byte raw24
file, six-byte ECC file, extra row or nonzero padding is unacceptable.

**Never use `0x010101`.** It would set KEY_VALID bit 0 **and KEY_INVALID bit 0**
plus a DOUBLE_TAP_DELAY bit. Invalidation overrides validity. The intended value
is plain raw **1 in each row**, with every other bit unchanged at zero.

The row model lives in `key_valid_policy.py`. It prints only a review proposal;
`authorized_for_programming`, `live_preflight_performed`,
`private_predecessor_binding_verified` and `loadable_artifact_prepared` remain
false. It has no live mode, subprocess calls or private input reads. Its validation
of a caller-supplied map is not proof of how that map was acquired.

## The new predecessor is not blank

The completed hash stage changed `0x0080–0x008f`. Expected raw encodings must be
rederived from the preserved key/recovery/hash artifacts, not accepted merely
because a named ECC view decodes to the right hash. The public transcript gave:

`SHA256(X_BE32 || Y_BE32) = b8fbbab76f60c7226c7172025f325b3bcb19986df08ff177c605e0217abd80ce`

The offline model uses that public fingerprint as an expectation, **not an
independently checked private-key/journal binding**. Its exact before/after
projection covers 290 rows:

- All **34** original policy rows, with only the three target copies changing.
- All **16** programmed hash rows, exact raw24 including ECC/BRP bits, unchanged.
- Remaining **48** signing-storage rows and **192** secret-storage rows, all blank.

Future live validation must check every target copy independently. Named-field
majority decoding or corrected ECC data cannot substitute for exact physical
coverage. Raw selectors must follow `--ser SERIAL`; use the reviewed
`-c 1 -r -n` option ordering. Reject duplicate/missing rows and diagnostics.
The old hash writer's all-blank preflight must not be reused or loosened.

## Irreversibility and partial state

The write is **not atomic**. Once two copies contain bit 0, a bitwise majority
already decodes it as 1, even if the third write fails. One or two programmed
copies are both failed/incomplete stage outcomes. Do not automatically retry,
finish the third copy, repair bits, revoke a key or clear a latch.

The physical validity bits cannot be cleared back to zero. Revocation is a
different irreversible operation and is excluded. Preserve the existing hash
attempt latch; any future activation writer needs its own distinct durable latch
under the same per-board exclusion mechanism. It must publish an armed/uncertain
checkpoint before a native write and never treat exit zero as success alone.

## What this stage does not prove

KEY_VALID marks slot 0 as eligible in signing-key matching when KEY_INVALID is
clear. It does **not** set CRIT1.SECURE_BOOT_ENABLE, disable RISC-V, disable debug,
change ROM routes, lock any page, install AES/salt or modify rollback policy.
All those controls remain at their prior values.

Do not infer that KEY_VALID-only is completely boot-behavior-neutral, or that its
effects wait until a cold reset. Public ROM source separately parses signature
key matches and decides whether signatures are required. Parsed-image state and
boot context must be distinguished from fresh physical OTP reads. A later
separately authorized acceptance plan must distinguish immediate readback,
new image parsing/launch, warm restart and genuine cold-start behavior; this
stage must not automatically reboot or execute any image.

The [comparison ROM commit](https://github.com/raspberrypi/pico-bootrom-rp2350/tree/c6cdb1711f32c3e34faaebd58618a6d096dbd52e)
is `c6cdb1711f32c3e34faaebd58618a6d096dbd52e`, **not attested board bytes** for
`a8bfe860`. In this source:

- Supported signature parsing calls key matching without a `sig_required` gate
  (`varm_blocks.c:472–488`); the matcher rereads BOOT_FLAGS1 twice and conditionally
  reads the enabled hash (`238–267`). KEY_VALID is therefore not parser-inert.
- Image signature requirements use the scan context's secure mode, with the
  covering-partition case handled separately (`varm_flash_boot.c:573–619`).
  Cryptographic signature verification is gated by `sig_required`
  (`varm_blocks.c:1112–1169`). Key matching is not signature enforcement.
- The partition-table signature requirement also ANDs its OTP flag with secure
  mode (`varm_boot_path.c:1356–1359`); header wording alone must not be used to
  claim independent enforcement while secure boot is zero.
- Previously parsed/verified blocks retain state (`varm_blocks.c:811,845–850`).
  Fresh OTP reads during a new parse do not imply revalidation of old contexts.
  The reboot API excludes the processor cold-reset domain (`varm_apis.c:68–81`).

Public-source analysis and simulated tests are not on-board behavioral acceptance. Signature enforcement and authenticated-recovery/negative boot tests
remain separate later stages, before secrets.

## Requirements before a future writer may be used

1. Validate and bind the preserved original keys, final 37-file recovery bundle,
   restored hash sidecar and tool. Read/validate the actual successful hash run
   `slot0-hash-v292yeja` and its permanent latch under a separately scoped
   preparation operation; bind their exact bytes and the hash writer's source
   digest. A success-looking filename or operator transcript alone is insufficient
   as the future executable artifact's predecessor check. Do not mutate them.
2. Publish a separate owner-only stage artifact outside Git with the exact
   12-byte raw payload and non-loadable review metadata. Include predecessor and
   recovery-image bindings. Independently back up and restore this new artifact;
   previous archive receipts do not cover files that did not exist then.
3. Implement and independently review a separate guarded KEY_VALID-only writer.
   Reuse the proven safety principles, **not the hash writer's ECC command or
   blank-hash assumption**: fixed serial/A4/ROM, exact raw before/after states,
   verified full 2 MiB flash, sealed executable/payload descriptors, parent/root
   directory durability, separate sticky latch, local confirmation, repeated
   preflight and a BOOTTIME deadline rechecked at the transport boundary.
4. Obtain separate explicit **KEY_VALID-only write approval**, then perform fresh
   physical identity and exact predecessor checks. A previous preflight PASS
   is not a freshness token. No automatic program-mode invocation is allowed.
5. Require unambiguous positive raw binary-load verification, then independent
   exact physical readbacks of all 290 selected rows and full-flash preservation.
   Pinned picotool can print `Mismatch` yet exit zero; its reported mismatch row
   is buffer-relative. Padding also participates in byte comparison. Neither
   exit status nor majority value proves complete three-copy success.
6. Hold at **KEY_VALID verified, before signature enforcement**. No activation
   implementation, permission or success is supplied by this document. Every
   later irreversible stage needs separate review, approval and preflight.

## Repeatable offline checks

These commands do not access the DUT or private predecessor inputs:

```sh
python3 challenges/misc/signal-box/firmware/security/key_valid_policy.py
python3 challenges/misc/signal-box/firmware/security/check_key_valid.py
```

The second checks eight SDK constants and uses the sealed local picotool 2.3.1
executable for `version` plus two **explicit-file** OTP simulations. Temporary
named-register/field JSON fixtures are deleted and never published as write
recipes. This tests raw layout/extent, **not the live BIN programming path**.
The local executable is snapshotted for consistency; matching it to the restored
private bundle remains a separate required binding check.

`test_key_valid_policy.py` covers all eight zero/one copy patterns, rejection of
all partial states, every single-bit change in both 290-row projections (13,920
mutations), old-blank predecessor rejection, wrong encodings/padding/coverage,
policy drift, proposal non-authorization, explicit-file commands and cleanup.

## Source references

- Pico SDK 2.2.0 `otp_data.h`: CRIT1.SECURE_BOOT_ENABLE lines 362–369;
  BOOT_FLAGS1/R1/R2 and KEY_VALID/KEY_INVALID lines 679–785.
- SDK `pico/bootrom.h` lines 645–660: prefix writes on failure and raw padding.
- Picotool 2.3.1 `main.cpp` lines 9263–9278: RBIT majority display;
  9444–9514: BIN extent/verification; 10421–10434: command return handling.
- Public comparison ROM `src/main/arm/varm_blocks.c`: fresh key matching and
  signature parsing/verification; `varm_flash_boot.c`: parsed-block verifier;
  `varm_launch_image.c`: launch constraints. Exact caller analysis is recorded
  with the review result in handoff §13.23; it does not establish board equivalence.
