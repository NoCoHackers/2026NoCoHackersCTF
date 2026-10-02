# Sam's Burrow Guide - author's write-up

One TCP service contains four independently scored lessons introducing binary
exploitation through small C programs. Lessons 1-3 form one progression:
adjacent data corruption, indirect control-flow corruption, and finally a saved
return-address overwrite. Lesson 4 is a separate format-string side path rather
than a fourth stack-overflow rung.

Every scored entry includes the relevant C source, `common.h`, and a short
binary-input primer. Sam speaks the Python address-encoding expression in the
lessons that need it; networking and prompt synchronization remain part of the
exercise. The service runs amd64 Linux. Executables
are non-PIE and compiled without stack canaries so each lesson can isolate one
primitive. NX remains enabled, stack and shared-library ASLR may remain enabled,
and the intended ret2win reuses existing executable code rather than injecting
code onto the stack.

The launcher switches its PTY to raw mode only after reading the lesson number.
Clients must therefore wait for `Lesson:`, send the choice, wait for the lesson
prompt, and only then send bytes containing NULs. Sending the menu and binary
payload together can let the terminal process those bytes before raw mode is
active. The handout explains this requirement without implementing the receive
loop; the author's autosolve demonstrates the complete sequence.

## Lesson 1 - Too Many Carrots

A struct places a 16-byte name immediately before an unsigned carrot count, but
`fgets` is incorrectly told it may read 64 bytes. The struct begins zeroed. Send
16 padding bytes and then a real newline byte (`0x0a`); `fgets` stores that
newline as the low byte of the adjacent integer, making the count exactly 10:

```python
b"A" * 16 + b"\n"
```

This payload is directly typeable. Enter exactly:

```text
AAAAAAAAAAAAAAAA
```

and press Enter. Do not type the characters `\x0a` or `\n`; those are source
notation for one byte. This is a data-only overflow: control flow is untouched,
yet an authorization value changes.

The safe form passes the destination's actual capacity:

```c
fgets(burrow.name, sizeof burrow.name, stdin);
```

Flag file: `/flag/flag.txt`.

## Lesson 2 - The Secret Tunnel

A note struct contains a 32-byte message immediately followed by a function
pointer. The service discloses `secret_delivery`, then an unsafe line reader
copies bytes into the message without checking its boundary. Replace the
adjacent pointer:

```python
payload = b"A" * 32 + struct.pack("<Q", secret_delivery)
```

`<Q` means a little-endian unsigned 64-bit value. If the live service prints
`0x401264`, the packed address is:

```text
64 12 40 00 00 00 00 00
```

Those are bytes, not the literal text `\x64\x12...`, so this payload is not
fully typeable at a terminal. Sam gives the player the `struct.pack("<Q",
address)` encoding expression, but the player must build a client that waits
for the menu, sends lesson 2, reads through the disclosed address and input
prompt, and then sends
the constructed payload followed by a newline.

The vulnerable reader
consumes but does not copy that delimiter, so only the 32-byte field and the
8-byte pointer are overwritten. The subsequent indirect call enters the secret
function.

Safe code would read at most `sizeof note.message` bytes and leave the function
pointer outside the writable range.

Flag file: `/flag/secret-tunnel.txt`.

## Lesson 3 - Return to Hutch

`follow_trail` has a 64-byte local buffer. The deliberately unoptimized amd64
build keeps an 8-byte saved frame pointer immediately above it; the next eight
bytes are the saved return address. The intended payload is therefore:

```python
payload = b"A" * 72 + struct.pack("<Q", hidden_hutch)
```

That is 64 bytes for the buffer, 8 bytes for saved RBP, then the disclosed
address for saved RIP. As in lesson 2, a player-written client must wait for
`Inscribe the return path: `, use the address printed by the live service, and
send it as packed little-endian bytes.

The teaching reader consumes one byte at a time until a newline delimiter. This
makes network framing deterministic: TCP may split writes however it likes, but
the lesson does not return until the complete inscription arrives. The newline
is not copied beyond the saved return address. When `follow_trail` returns,
execution lands in `hidden_hutch`. The hidden function realigns the stack before
calling libc because a `ret` landing does not have exactly the same alignment as
a normal `call` entry.

Production code must bound every write by the real destination size and check
all read results. Stack canaries, PIE/ASLR, and NX are valuable defense in depth,
but do not replace removing the out-of-bounds write.

Flag file: `/flag/return-to-hutch.txt`.

## Lesson 4 - The Painted Sign

This lesson begins a different vulnerability family. The program passes player
text directly as `printf`'s format string. It supplies a harmless integer as
variadic argument 1 and `&target` as argument 2:

```c
printf(story, 'A', &target);
```

`%n` writes the number of characters printed so far through an `int *`. Use
positional conversions consistently: print argument 1 in a field 4,919
characters wide, then write that count through argument 2:

```text
%1$4919c%2$n
```

This payload is entirely printable: type it exactly and press Enter. Because
4,919 is `0x1337`, the target check succeeds. Separate, correctly typed arguments keep the
lesson focused on output counts and `%n`, rather than depending on one variadic
argument being interpreted as two incompatible types.

The safe form keeps player text out of the format-string position:

```c
printf("%s", story);
```

Flag file: `/flag/painted-sign.txt`.

## Curriculum summary

1. **Too Many Carrots:** corrupt adjacent data without controlling execution.
2. **The Secret Tunnel:** redirect an indirect call through an adjacent pointer.
3. **Return to Hutch:** identify saved RBP/RIP and perform a minimal ret2win.
4. **The Painted Sign:** branch into format-string writes with positional `%n`.

Each successful lesson explains the corresponding safe C pattern before
printing its flag. A failed process may disconnect because corrupt control flow
crashed it; the launcher calls this out explicitly so learners can distinguish a
crash from a network mystery, reconnect, and adjust their bytes.

## Organizer notes

- One container listens on `nc chal.nocohackers.com 30004`; socat starts a
  fresh launcher for each connection.
- The binaries intentionally use `-O0 -fno-stack-protector -no-pie`. Changing
  those flags changes the curriculum and may invalidate offsets.
- The container still uses the event's runtime hardening: read-only root,
  dropped capabilities after startup, no-new-privileges, resource limits, and
  an unprivileged challenge process.
- `tools/test-challenge.sh challenges/pwn/sams-burrow-guide` exercises every
  intended exploit against a fresh hardened container.
- If it dies: `make -C deploy/chals restart S=pwn-sams-burrow-guide`.
