# Municipal Connectivity Test - author's write-up

## Intended path

Connect to the service with the `nc` command from the challenge description.
The server claims to echo input verbatim, but shell metacharacters change its
behavior. Sending a command separator followed by a command demonstrates that
the input is being interpreted rather than merely repeated:

```sh
hello; id
```

The server builds `echo <player input>` and executes it through `/bin/sh`.
Nothing quotes or escapes the player-controlled portion, so the separator ends
the `echo` command and starts a second command. Read the runtime-provided flag
with:

```sh
hello; cat /flag.txt
```

## Difficulty

Beginner. The greeting identifies the claimed behavior, and testing common
shell metacharacters quickly exposes the command injection.

## Organizer notes

64 MB, no persistent state, and one process per connection. The process runs as
the unprivileged `ctf` user inside the hardened challenge container.
