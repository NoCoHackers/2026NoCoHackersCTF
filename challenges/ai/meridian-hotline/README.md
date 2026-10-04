# Meridian AI Hotlines

One externally hosted application, three independent CTFd entries in category
`ai`. CTFd owns registration, submissions and scoring; Azure owns isolated
synthetic game records, AI interactions and phone transport. There is no CTFd
plugin, shared login, automatic score write or new challenge-host container.

## Proposed fixed points

| Entry | Manifest | Proposed value | Rationale |
|---|---|---:|---|
| MARA - Read the Fine Print | `challenge.yml` | 100 | One accessible document-disclosure insight. The source is already available to the AI; no scripting, special tool or warmup is required. |
| ROOK - Return to Someone Else | `challenge.rook.yml` | 200 | A short source/destination authorization chain: prepare an owned record, then exploit a different operation on the target. Starting IDs, capabilities and resulting records are visible. |
| VERA - Your Call Has Been Summarized | `challenge.vera.yml` | 300 | Stored-note injection must survive an AI handoff into a privileged billing action. Players inspect real review artifacts and iterate, but receive the workflow, editable note and three free hints. |

These are proposed values for Brandon's event-wide review, not automatic
normalization or guaranteed solve rates. Edit the manifest's `value` to tune
points; keep `type: standard`. Phone time and speech-recognition friction are
not reasons to add points. VERA is the hardest hotline, but the disclosed
workflow and free guidance keep it below a blind or scripting-heavy expert
chain. Do not force 100/300/500 simply to spread out this track.

### Comparison with the rest of the event

Calibration uses the current fixed values and organizer writeups for the
20 existing entries across eight bundles, not just this track's internal
easy/medium/hard labels.

| Hotline | Existing comparison | Published value | Reason for the comparison |
|---|---|---:|---|
| MARA | [Slithery Little Snake](../../web/slithery-little-snake/solution/writeup.md) and [Municipal Connectivity Test](../../pwn/municipal-connectivity-test/solution/writeup.md) | 100 each | A direct, discoverable trust-boundary mistake without blind inference or automation. |
| ROOK | [Boone's first lesson](../../pwn/boones-trail-guide/solution/writeup.md) and [I-25 Rampage](../../web/i-25-rampage/solution/writeup.md) | 200 each | One familiar injection/business-logic technique with modest context handling; the hotline adds two record operations, not a specialized scripting problem. |
| VERA | [Babs's Remembering Cauldron](../../pwn/babs-spellbook/solution/writeup.md) and [Boone's Old Dog, New Tricks](../../pwn/boones-trail-guide/solution/writeup.md) | 300 each | Second-order attacks: save data in one context and have it interpreted in another. VERA crosses an AI-to-AI privilege boundary, with visible handoffs for iteration. |

The event's 400-point blind-oracle/timing lessons, such as Babs's Silent Oracle
and Boone's Quiet Whistle, require inference or automation the hotlines do not.
The 500-point Old Town Accounts proprietor chain is a specialized historical
multi-stage exploitation task. Those are not appropriate comparators merely
because VERA is the hardest entry here.

All three hotline briefs disclose the exact objective and fixture identifiers;
all supply three free hints and an equal text route. That scaffolding lowers
the expected reasoning burden. VERA is consequently a guided, low-end 300:
revisit it if hints/workflow visibility change materially, not because the
voice provider has an inconvenient refusal or transcription error.

The connected-time design targets are MARA 2-3, ROOK 3-6 and VERA 6-10 minutes,
not measurements or mandatory call lengths. Browser preparation, note editing
and thinking can take longer off-call. Players can instead use the equivalent
text interface. The organizer has personally retrieved all three flags through
the practical walkthrough; that does not establish an event-wide solve rate.

## Public and private artifacts

Each folded `description: >-` contains the objective, direct service link and
first-step instructions. Each entry has three zero-cost hints and shares
`handout/player-guide.md`, which is safe to publish.

`solution/writeup.md` and the solver prompts are organizer-only spoilers.
Do not attach them to a CTFd challenge. Real flags appear only in the three
manifests, matching the existing Azure `FLAG_HOTLINE_MARA`, `FLAG_HOTLINE_ROOK`
and `FLAG_HOTLINE_VERA` values. Service credentials are not part of this bundle.
Do not rotate a live flag while importing it into CTFd.

The correct repository filenames are `challenge.yml` and `challenge.<id>.yml`,
not `challenge.yaml`. Keep each published `name` unchanged. If these entries
were previously created manually, coordinate their exact names with Brandon
before merging so the name-based sync updates rather than duplicates them.

## Verification and publication

The submitted manifests start **hidden**. Regular PR checks validate metadata
and run the offline cookie/CSRF/HTTP/referee fixtures:

```sh
tools/test-challenge.sh challenges/ai/meridian-hotline
```

Offline tests do not create `verification.json`, call a funded model, prove
live-model reliability or unlock publication. They do not print configured
flags as a pretend solve.

An organizer deliberately runs the genuine solvers against the approved
external origin before publishing. This consumes the hotline's persistent
model-call budget, but uses text so it does not place PSTN calls:

```sh
NOCO_EXTERNAL_LIVE=1 tools/test-challenge.sh challenges/ai/meridian-hotline
```

The live runner checks the earned flag for every entry and records
`verification.json` only after all three pass. The receipt binds the origin,
entry identities, versions and flag hashes, not the editable point values.
It is an organizer audit record, not a cryptographically authenticated
attestation. Review it with the actual command result. A failed run is not a
verified solve; do not manufacture a receipt or replace the solver with an echo.

Each solver creates a fresh private session, preserves cookie/CSRF handling,
checks authoritative completion, and stops on technical failures. Limits are
150 seconds per service and at most 3 MARA, 4 ROOK and 3 VERA chat requests.
VERA can initiate at most three reviews. The runtime can use up to four provider
calls per chat turn plus two per accepted review: a whole verification is
bounded by 46 model invocations, usually substantially fewer. Spending alerts
and the existing persistent budget remain the backstop.

If the runner names a failing service, diagnose that one rather than repeatedly
spending budget on the full set. For example, its wrapper can show the
controlled error message without revealing raw provider responses:

```sh
TARGET=https://ca-nocohackers-ctf-2026.blackmoss-cf337681.westus2.azurecontainerapps.io \
  NOCO_EXTERNAL_LIVE=1 challenges/ai/meridian-hotline/solution/solve-vera.sh
```

This is still a deliberately paid live attempt. A successful individual
diagnostic does not generate the all-entry receipt; rerun the full controlled
verification once the underlying issue is resolved.

After a genuine successful run, review and commit the receipt, change the
three `state` values to `visible`, and run the existing validation/name checks.
Visible external entries without a matching receipt fail validation.
Normal main-branch sync then registers the entries using the existing ctfcli
workflow. No CTFd configuration change is needed. Do not run sync while merely
reviewing this PR.

## Operations and limitations

The public number is **+1 (970) 292-7618**; extensions are **314 / 527 / 806**.
The existing Azure release must have `CONTENT_PACK=hotline` and matching flags.
This submission targets app implementation `99e65d6`; do not assume that commit
is deployed just because the documents exist.

The event ends `2026-10-16T00:00:00Z` (October 15 at 6 PM MDT).
Keep the app's `HOTLINE_EVENT_ENDS_AT` aligned. Intake must remain enabled
throughout turns and internal reviews; the Azure deploy script leaves it paused.
Game records are private browser sessions, not CTFd user/team accounts.

Existing defaults are 5 simultaneous calls, 600 event minutes, a 60-second
same-service redial cooldown and 5,000 provider invocations. Fifty players at
15-20 connected minutes each would require 750-1,000 minutes before extra retries;
review spending/capacity separately rather than silently raising limits.

Provider failures, unavailable capacity, STT errors and pairing problems are
operational issues, not attack resistance. The player guide explains the text
fallback, refresh controls, free hints and organizer escalation. No audio is
recorded. Redacted transcript retention is at most 48 hours; game artifacts
normally expire at event end plus 24 hours.
