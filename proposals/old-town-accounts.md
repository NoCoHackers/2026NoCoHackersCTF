# Old Town Accounts — design document

Status: implemented and validated in `challenges/misc/old-town-accounts`.
Caldera redistribution and aggregate-container threat-model sign-offs were
received from the organizer on 2026-10-03; awaiting PR review. This document
records the design decisions, feasibility evidence, and accepted residual
risks; the manifests and generated deployment are authoritative for shipping.

## At a glance (maps to the challenge-proposal template)

- **Working title:** Old Town Accounts (three scored entries; see *Scoring*)
- **Category:** `misc` — it's a retro-computing escape room,
  not modern web exploitation; deployment is still `kind: web`)
- **Difficulty:** hard (a handful of solves) — the event centerpiece, intended
  2–3 hours for an experienced player
- **The idea:** a PDP-11 emulator running recovered UNIX V4 hosts a fictional
  accounting ledger. Three flags: recover a clerk credential from a forensic
  disk handout and log in; escape the ledger application into an unprivileged
  shell; escalate to root via a documented historical flaw in early UNIX.
- **How it runs:** `web` (browser terminal on a subdomain) plus a static
  downloadable handout
- **Anything unusual:** per-player emulated machines with reconnectable
  sessions. This is new infrastructure for the event — a session gateway plus
  a trusted instance manager, sized 5–20 instances. See *Session architecture*.

## Narrative

> While walking your dog through Lions Park after dark, you're approached by a
> cloaked figure. Your dog goes quiet.
>
> The figure holds out a battered disk cartridge.
>
> "The key to that which you seek."
>
> You take it. Before you can ask what that means, your dog pulls hard on the
> leash. When you look back, the figure is gone.
>
> A yellowed label on the cartridge reads:
>
> **OLD TOWN ACCOUNTS — NIGHT COPY**
> **DO NOT RECONCILE**
>
> Beneath it, in fresher ink:
>
> **Your account is still open.**

The player learns the cartridge is the night backup of an accounting system
that is somehow still online. Each stage answers part of "why is my account
still open, and what is it being charged?" The proprietor's books (stage
three) reveal who collects. The intended payoff — the ledger records debts
owed in **years of life, not dollars** — is an open question awaiting final
sign-off.

## Scoring

One bundle, three independently scored manifests, per the repo's
multi-manifest convention:

| entry | working name | flag |
|-------|--------------|------|
| `challenge.yml` (primary) | The Night Clerk | login to the live ledger |
| `challenge.ledger-escape.yml` | Off the Books | unprivileged shell |
| `challenge.proprietor.yml` | The Proprietor's Copy | root |

Whether later entries are hidden in CTFd until earlier solves is a
presentation choice, not a security boundary (all three ship at once).

## Stage 1 — The Night Clerk (initial access)

**Handout:** a bootable RK05 disk image (the "cartridge") — a separate
historical backup, *not* a copy of the live challenge disk. Players may boot
it in their own emulator or carve the filesystem directly; becoming root on
their local copy is expected and harmless by design.

The cartridge contains a former night clerk's home directory, ledger
application configuration with a recoverable credential, and archived operator
messages establishing which account still exists. The credential is recovered
by filesystem exploration and correlation — not password cracking, not a
guessing game. Exactly one reasonable answer once the evidence is connected.
The final chain is: E. Bell's desk note gives the rule; `night.conf` names the
shared `clerk` role and October watch register; the archived close message says
account 0317 remains open; the register maps 0317 to the lower-case watchword
`lantern`. The stock source trees are overwritten before deletion so carving
the forensic image cannot reveal the later uid flaw.

**The live service:** connect via browser terminal to the ledger machine,
log in as the recovered clerk, land directly in the ledger application (not a
shell — otherwise stage 1 and stage 2 collapse into one milestone).

**Flag one** accompanies the **Nightly Balance Report**: the nightly totals
don't match, and the unmatched payment (a $25 entry to account 0317 — the
player's own) points at an account with no recorded holder. Flag one is on
the live service, never on the handout.

The handout also carries an older operator manual establishing the original
workflow; the live system's Technical Bulletin 7 describes what changed.

## Stage 2 — Off the Books (application escape)

The ledger is a real program running inside UNIX V4. Five commands:
account inquiry, journal entries, reconcile batch, print report, operator
notices.

Discovery chain:

1. **Something doesn't balance.** The Nightly Balance Report (post-login,
   with flag one) flags the unmatched payment to account 0317.
2. **The interface has a history.** Investigating that payment's journal
   entry exposes a retired report designation and a "reprint entry" action
   that prompts for a report type. *This prompt is the gate:* it does not
   exist on the main menu, so the escape input is unreachable without doing
   the investigation.
3. **The machinery is legible.** Operator notices reference Technical
   Bulletin 7, readable through an operator-reference option. The bulletin
   explains how reports are processed and contains an annotated listing of
   the report helper — a few readable lines of period shell showing the
   report designation substituted, unquoted, into a command. It documents
   normal system behavior; it does not announce a vulnerability.
4. **The escape.** The player enters `M;sh /dev/ttyN;exit` at the report
   type prompt (station line N is taught by the operator manual). V4's
   shell re-scans substituted parameters for metacharacters, so the
   processor line splits on the `;`; the injected `sh /dev/ttyN` opens
   the terminal device itself as its command file — an interactive
   (promptless) shell as the night clerk. The `;exit` tail keeps the
   line's trailing argument from derailing the chain — a discovered
   detail that is part of the puzzle. Shell metacharacter injection into
   a glue script is period-authentic for 1974 and remains true about
   software today.

**Privilege boundary:** the escaped shell has exactly the clerk's own uid and
group. No privilege jump — root is stage three. Setuid binaries (`login`,
`su`) cannot exec from script contexts on V4, so the shell cannot shortcut
to root either.

**Flag two** is the clerk's mailbox: an unread message from the proprietor,
readable from the shell (login even announces "You have mail."). A weaker
one-shot variant also works — `M;cat /usr/clerk/mailbox;exit` — code
execution without a session, which keeps the stage solvable at two depths.

**Undocumented alternate path:** if the compose-notice feature drops into
`ed` and V4's `ed` supports a shell escape, that works too. Left in as a
bonus for players who know period editors; documented nowhere; CI tests only
the intended path.

**Stage boundary that must hold:** the proprietor's books (stage three) are
a file owned by root, readable by group 0 only, mode 0400 — unreadable from
the stage-two shell. That boundary is what makes stage three the historical
flaw rather than a footnote.

## Stage 3 — The Proprietor's Copy (root)

**Spike-verified chain** (on-guest, end to end):

1. The shell source is world-readable in `/usr/source/` — reading
   `s2/sh.c` reveals the superuser test `(getuid() & 0377) == 0`, and the
   kernel stores the uid in a byte, so **any uid ≡ 0 (mod 256) is root**.
2. `/etc/passwd` is mode 666 — the office's account list, which
   "everyone keeps current" (period-plausible sloppiness; deliberate
   engineering). From the escaped shell the clerk runs `ed /etc/passwd`
   interactively (v4's shell has no `>>` append; ed is the way) and adds
   `owner::256:256::/tmp:` — an existing directory, since v4 `mkdir`
   prompts for confirmation.
3. Sign off. The ledger exits, **getty respawns on the terminal's own
   line**, and the player logs in as `owner` — the terminal's own login
   performs the setuid; no script-context setuid games needed.
4. A `#` root prompt. `cat /proprietor` — the books. Flag three.

The boundary held at every step: the clerk shell could not read
`/proprietor` (mode 400 root), could not exec setuid binaries, and
`setuid`/`setgid` syscalls are privileged — the passwd/login path is the
only door, and it is exactly the documented historical flaw.

Per the repo's ground rules, this runs against a system we own inside a
sandboxed emulator; the flaw is public historical record and the target is
entirely fictional.

## Session architecture

```text
player browser ── HTTPS/WSS ── hardened challenge container (uid 10001)
                              │  cookie gateway + trusted pool manager
                              │
                   pool of OpenSIMH processes
                   (private RK05 copies and loopback-only DLI ports)
```

The implemented bundle deliberately uses no Docker socket. The repository's
challenge deployment contract creates one hardened service per bundle, so the
gateway owns the emulator children inside that service rather than giving a
public-facing component Docker control. The guest's root privilege exists only
inside PDP-11 emulation; the outer container remains unprivileged, read-only,
capability-free, and resource-capped. A simulator-process escape could cross
sessions within this one service, so per-instance host containers remain a
possible infrastructure hardening follow-up rather than a shipping dependency.
The organizer explicitly accepted this OpenSIMH process-escape and cross-session
risk on 2026-10-03.

- **Access:** server-issued session cookie — host-only, `Secure`, `HttpOnly`,
  `SameSite=Strict`, bounded lifetime. Returning with the cookie reconnects
  to the same machine. "Start machine" allocates; **Reset machine** reuses
  the existing allocation; closing the browser disconnects the terminal but
  not the emulator. Players are warned the cookie identifies the browser, and
  how sessions are managed (see *No persistence*).
- **Pool:** **5 initial instances**, growing on demand to **20 total**
  (assigned + ready). Never auto-shrink during the event.
- **Reclamation at cap:** reclaim the least-recently-active instance idle
  ≥ 6 hours; wipe and reprovision before reassignment. If none qualifies,
  show the player exactly:
  > no avaliable PDP/11 instances, reach out to the organizers on the NoCo Hackers CTF channel

  (typo "avaliable" is in the agreed copy — confirm before shipping).
- **Activity = player terminal input only** (not guest output, heartbeats, or
  open tabs). Allocation and reclamation are atomic — no double-assignment,
  no exceeding the cap. Expired-session owners returning later get a clear
  "your machine was reclaimed" notice.
- **No persistence:** progress does not survive container restarts or
  deploys. This is stated plainly to players; they can take notes and repeat
  steps (the whole investigation is repeatable after reset).
- **Security:** guest root ≠ container/host root. Emulator console is never
  exposed; only the guest terminal. DLI listeners bind loopback. All repo
  hardening applies unchanged (`read_only`, `cap_drop: ALL`,
  `no-new-privileges`, resource caps, no outbound network), and no component
  has Docker control. At a full non-reclaimable pool, allocation returns the
  agreed 503 page rather than overloading the host.

## Flag handling

Repo rules apply without exception: flags live only in manifests, source uses
`__FLAG__` / `__FLAG_<ID>__` tokens, and per-instance disk copies get flags
provisioned at runtime. No flag ever touches an image layer — including the
handout cartridge, which contains **no flags and no later-stage secrets**.
The implemented master reserves one unique 128-byte space-padded slot for each
token. The trusted pool code validates the three `noco{...}` environment values and
atomically replaces those slots in the private RK05 copy without resizing the
filesystem. Missing/malformed flags, duplicate/missing slots, or a flag literal
already present in the master are fatal startup errors.

## Testing plan (CI must pass all of this)

- Autosolve per scored entry, as with every runnable challenge:
  - stage 1: boot handout logic + scripted login + capture flag one;
  - stage 2: scripted journal → bulletin → injection → shell → read mail;
  - stage 3: scripted escalation → read proprietor's books.
- Boundary tests: no ledger menu path reaches the mailbox or proprietor's
  file; the stage-two shell cannot read the proprietor's file.
- Handout test: the distributed cartridge contains no flags and no
  later-stage secrets, verified by scanning the image bytes.
- Lifecycle tests: reconnect preserves the guest; reset reprovisions;
  concurrent allocations never double-assign; 6-hour reclamation;
  capacity message at cap.
- Resource measurement: CPU/memory per emulator instance at idle and under
  use, to size the pool before the event.

## Remaining organizer decisions

1. Narrative payoff: "debts owed in years of life" — awaiting sign-off.
2. CTFd visibility gating between the three entries — presentation choice.

Caldera redistribution/attribution and the aggregate-container threat model
were approved by the organizer on 2026-10-03. Category `misc`, the intentionally
misspelled capacity message, and three
500-point dynamic entries are now fixed in the bundle.

## Feasibility spike (must pass before puzzle details are frozen)

Spike artifacts live outside the repo (`/tmp/pdp11-spike`) until they earn a
place in the bundle. Results below as of 2026-09-28; details in
`/tmp/pdp11-spike/NOTES.md`.

1. **Emulator choice and build — DONE.** Mainline OpenSIMH (`open-simh/simh`,
   commit 87eb7d5, V4.1-0) builds cleanly with `make pdp11`; no fork or
   patches required for console work. The workshop's PiDP-11 fork is only
   needed for its DC/DL multiplexer count; mainline `dci`/`dli` suffice.
2. **UNIX V4 image provenance and redistribution rights — DONE; organizer
   sign-off received 2026-10-03.** The production and handout images were rebuilt from
   the original tape (SHA-256 `43e912bb7a5fcc5f421eac30cf87b9e01417f547b248ce5f902fad14eb87b8a2`),
   not a workshop derivative. The Caldera license and required acknowledgment
   ship with the handout.
3. **Automated boot — DONE.** Scripted boot via SIMH `expect`/`send` in the
   ini (no stdin plumbing): ROM `k` → `unix` → login prompt in **~1.2 s**,
   scripted root login and command execution verified against the workshop
   image. Two operational gotchas, both solved: (a) the workshop kernel
   **panics (dumps `ka6`/`aps`) unless `tc`, `dci`, and `dli` devices exist**
   — keep them enabled (even one attached line each) in every config;
   (b) SIMH stdout is block-buffered on a pipe — run the emulator on a pty
   or apply the workshop's `unbuffered_console` patch.
4. **V4 shell semantics — DONE.** `;`, `|`, and `>` all verified working on
   the guest — the stage-two injection primitive is real. `/bin` inventory
   confirms the Thompson-shell ecosystem: control flow via separate
   `/bin/if` and `/bin/goto` commands, period-authentic for the ledger's
   menu loop.
5. **`ed` shell escape — DONE, IT WORKS.** `!date` from inside V4's `ed`
   executes the command. The alternate stage-two path is real; keep it
   undocumented.
6. **Mail spool — DONE.** Mailboxes live at `/usr/<user>/mailbox`; reading
   shows a `From <sender> <date>` header and prompts `Save?` when done.
   Flag-two placement confirmed.
7. **Group-ID flaw — DONE, verified end to end.** The flaw is login-time:
   `getuid()` returns a packed word (uid high byte, gid low byte), the
   superuser test checks only the low byte, and login's parsing of the
   passwd numeric fields truncates to bytes — so any uid/gid ≡ 0 (mod 256)
   is root. Verified: appended `owner::256:256::/usr/owner:` to
   `/etc/passwd`, logged in, got `#`. Also verified: `setuid(256)` and
   `setgid(0)` both **fail** from a non-root shell (the syscalls are already
   privileged), which is what keeps stage two and stage three separate.
   Root is passwordless on the stock image — the guest **must** set a root
   password at build time or stage three dies to a one-word `su`.
8. **Terminal I/O / resources — BRIDGE PROTOTYPED.** Measured with
   `set cpu idle`: **~1.8% of one core idle, ~13 MB RSS, ~1.1 s boot**.
   A 20-instance pool costs roughly a third of a core and ~260 MB —
   comfortably viable. Without `set cpu idle` the emulator spin-waits at
   ~100% of a core (V4 has no halt-based idle); idle detection is mandatory
   in every config. The browser bridge is built and passing end-to-end on a
   single instance: vendored xterm.js page, cookie session, websocket ↔ TCP
   relay to the guest's DLI terminal line, **detach/reconnect preserves the
   guest login**, reset reprovisions. The 5→20 pool, cap behavior, idle
   reclamation, stale-browser invalidation, and lifecycle tests are complete.
9. **Provenance and redistribution — APPROVED 2026-10-03.**
   The 2002 Caldera license (SPDX: `Caldera`) grants fee-free use, modify,
   and distribute rights — including derived binaries — for "UNIX Operating
   Systems that operate on the 16-Bit PDP-11 CPU," which covers V4. Build
   our image from the original tape distribution (TUHS / Internet Archive,
   not the workshop repo's derived `disk.rk`, which carries no license),
   credit the recovery (Archibald / Papenhoff / CHM), and ship the Caldera
   text with the handout. Not legal advice — organizers confirm.

### New facts from the spike that shape the design

- **V4 `/etc/passwd` has six fields — no login-shell field.** ~~Everyone
  gets `sh`.~~ **CORRECTED BY THE BUILD: there IS an optional 7th field**
  — `login.c` execs it, defaulting to `/bin/sh`. The clerk lands in the
  ledger via `clerk::12:12::/usr/clerk:/usr/ledger/ledger`; nothing to
  patch.
- **The workshop `disk.rk` is polluted** with ~40 workshop user accounts.
  Production images get rebuilt clean from the original tape per the
  documented `install.ini` recipe, then customized. Note: everything in this
  spike was verified on the workshop's *patched* 32-terminal kernel; the
  stock tape kernel's device expectations (the `tc`/`dci`/`dli` presence
  requirement) must be re-verified during the image build.
- **Disks mutate.** Every session writes its RK05 image, and hard-killing
  the emulator may leave that copy inconsistent. Each reset/reclaim discards
  the copy and starts from the immutable master, so no dirty disk is ever
  reused or persisted.
- V4's `cat` fails **silently** on unreadable files — no error text. Keep in
  mind for puzzle text and CI expectations.
- The guest clock runs in **September 1974** on the workshop image; set our
  own date at build time for determinism (and story).
- Console device is `/dev/tty8`; `/etc/ttys` governs getty lines; a failed
  login re-prompts with `Name:`.
- **SIMH console buffering:** `set log` files are block-buffered inside the
  simulator — watching them live starves. Anything that must observe
  console output boots the emulator on a pty.
- **SIMH tmxr sets no SO_REUSEADDR:** an emulator killed with an open mux
  TCP connection leaves the port in kernel TIME_WAIT (~60 s), and
  re-attaching that port fails *silently* — boot completes, the player's
  terminal line just never appears. Every boot gets a fresh port from the
  instance manager; a tmxr patch is a hardening option for the image build.
- **The simh DH11 device is unreliable for interactive telnet lines:**
  its poll service is coscheduled with a hardcoded tick count (unlike
  DC/DL's adaptive `tmxr_poll`) and is never activated at attach — under
  `set cpu idle`, clock-calibration stretching starves it nondetermin-
  istically. Three vendored dh.c patches helped but did not fully cure it.
  **Resolved:** the guest kernel now has eight floating KL/DL11 lines;
  OpenSIMH `dli` line 0 maps to KL minor 1 (`/dev/tty9`). DLO0 uses 7-bit mode,
  and the KL driver default no longer enables V4 `LCASE`, so lowercase flag
  text and braces survive both login and `sh /dev/tty9`. Full browser solves,
  reconnect/reset, reclamation, and concurrent-cap tests are green.
- **Player terminals are mux lines, never the SIMH console** — the console
  reaches the simulator's own prompt (Ctrl-E) and must stay operator-only.

## Sequencing

1. Design document (this file).
2. Feasibility spike — one bootable guest, scripted boot, measurements.
3. Reconnectable-terminal prototype (one instance, cookie, browser
   terminal). **DONE** — all tests passing (login, exec, reconnect
   survival, repeated resets).
4. **Session gateway + pool lifecycle — DONE.** Warm start, growth to cap,
   atomic allocation, keystroke-only activity, idle reclamation at cap,
   stale-browser invalidation, exact capacity message, reclaimed-token notice,
   reconnect/reset, and no auto-shrink are covered. The shipping architecture
   intentionally uses one aggregate hardened container and no Docker socket;
   see *Session architecture* for the accepted residual risk.
5. **Master image and three-stage content — DONE.** Clean rebuild from the
   original tape (Caldera license), rebuilt KL/DL11 kernel, root password,
   passworded `clerk` account whose 7th passwd field launches the real ledger,
   proprietor's mode-400 file, mailbox and all three runtime flag tokens.
   Player terminal is DLI line 0 -> `/dev/tty9`; every stage and boundary has
   passed through the browser gateway.
6. **Cartridge handout — DONE.** Separate bootable RK05, deterministic clue
   chain for `clerk` / `lantern`, old operator manual, stock source trees
   scrubbed before unlink, raw leak scan clean, disposable-copy boot solve
   passing.
7. **Runtime flag injection — DONE.** Three fixed-width slots are patched only
   in private disk copies; the immutable master contains no flag literals.
8. **Challenge bundle and CI — DONE.** Three manifests and autosolves,
   handout/master boundary tests, lifecycle/concurrency tests, hardened image
   leak scan, and a 20-instance 64 MiB tmpfs stress test all pass.
9. PR review and merge; organizers flip `state: visible` at kickoff. Caldera
   redistribution and aggregate-container threat-model sign-offs were received
   on 2026-10-03.
