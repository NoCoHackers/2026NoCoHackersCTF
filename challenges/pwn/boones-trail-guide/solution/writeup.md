# Boone's Trail Guide - author's write-up

One TCP service contains four independently scored lessons covering distinct
ways untrusted text can change command-line behavior. The sequence deliberately
moves beyond the easy `input; command` example: shell context and quoting,
dangerous argument semantics without a shell, blind inference, and persisted
second-order injection.

## Lesson 1 - Off the Leash: shell context and quote breaking

The scent is enclosed in single quotes:

```sh
grep -i '<scent>' /srv/trails/scents.txt
```

Submit `pinecone' /srv/trails/scents.txt; printf BOONE_FOUND_1 #`. The first
quote closes the data context, the semicolon starts another command, and `#`
comments out the application's trailing quote and filename. This establishes
the general model: the exploit must first escape its current quoting context,
then introduce syntax meaningful to the interpreter.

Equivalent payloads could use a newline, `&&`, `||`, a pipeline, or command
substitution after escaping the quote. Those are variants of the same bug, not
separate defenses. Blacklisting one metacharacter or trying to hand-escape a
shell command is therefore fragile.

The safe form invokes grep directly and includes `--` before user-controlled
filename-like data:

```go
exec.Command("grep", "-i", "--", scent, "/srv/trails/scents.txt")
```

Flag file: `/flag/flag.txt`.

## Lesson 2 - Dangerous Options: argument injection without a shell

The compression script uses a fixed executable and passes each value as a distinct argv
entry:

```text
tar --checkpoint=1 <your option> -cf /tmp/trail-pack.tar /srv/trails/scents.txt
```

There is no shell parsing at this layer, so `;`, `$()`, and quotes are ordinary
characters. However, GNU tar itself assigns executable behavior to some option
values. Submit:

```text
--checkpoint-action=exec=printf BOONE_FOUND_2
```

This teaches the important boundary between *shell injection* and broader
*argument/option injection*: removing `sh -c` eliminates shell syntax, but the
called program still interprets its own arguments.

Defenses are program-specific: place `--` before filename operands where the
program supports it, reject option-like user values, use allowlists for expected
argument forms, and avoid exposing dangerous utility features at all. `--` is
not a universal substitute for understanding the target program's semantics.

Flag file: `/flag/dangerous-options.txt`.

## Lesson 3 - The Quiet Whistle: blind command injection

Only the exit status of this command is visible:

```sh
test -d '/srv/trails/<path>'
```

A probe such as the following asks whether the first character of the whistle
is greater than `m`:

```sh
x' || [ "$(cut -c1 /srv/trails/whistle)" \> "m" ] #
```

Boone sits for status zero and runs for nonzero. Binary-search each of four
positions, then submit `!claim bark`. The autosolve genuinely performs the
binary search.

The visible status is one example of a blind oracle. Real applications may
leak through response differences, DNS/HTTP callbacks, or timing—for example,
a conditional `sleep`. Hiding stdout does not fix command injection when an
attacker can observe any consequence.

The safe implementation should perform the filesystem operation directly and
validate that the resolved path remains beneath the intended root. Merely using
`filepath.Join` does not stop `..`, symlink escapes, or check/use races.

Flag file: `/flag/quiet-whistle.txt`.

## Lesson 4 - Old Dog, New Tricks: persisted second-order injection

The route is first written to a per-session queue file as plain data. A later
`follow` action reads that stored value and an old worker builds:

```sh
printf "Following route: <stored route>\n"
```

Store `$(printf "\\nBOONE_FOUND_4")`, then choose `follow`. Command substitution
still executes inside double quotes; the leading newline places the marker on
its own output line. Unlike Lesson 1, this needs no quote breakout, separator,
or comment. The write itself is safe; exploitation occurs only when a later
component changes the stored data's interpretation. This models values crossing
a persistence and job-processing boundary.

The lesson is not to sanitize on write or assume double quotes make a shell
safe. Preserve data as data, track its trust across databases, queues, logs, and
jobs, and use the correct safe API at every sink. Here the worker should print
in-process with `fmt.Fprintf` rather than building a shell command.

Flag file: `/flag/old-dog-new-tricks.txt`.

## Curriculum summary

Together the lessons establish these practical rules:

1. Identify the interpreter and the current quoting context.
2. Shell operators have many interchangeable forms; blocklists are unreliable.
3. Prefer fixed executables with separate argv entries, but still validate the
   called program's option and argument semantics.
4. No output does not mean no exploit; status, time, and external effects form
   blind channels.
5. Stored data remains untrusted when it reaches a later command sink.
6. Use least privilege and process isolation as defense in depth, not as a
   replacement for removing injection sinks.

## Organizer notes

- One container listens on `nc chal.nocohackers.com 30003`; socat forks a fresh
  service process for every player.
- Shell commands use a two-second parent timeout and a minimal environment.
- If it dies: `make -C deploy/chals restart S=pwn-boones-trail-guide`.
