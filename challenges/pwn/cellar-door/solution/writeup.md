# Cellar Door - author's write-up

**Flag:** `noco{the_door_was_never_really_locked}`

## Intended path

`nc` in, type `help`, the program tells you the password (`sourdough`), type
it, get the flag. This is the pwn-category warmup - it teaches players the
`nc host port` connection pattern and the flag format without requiring any
actual exploitation. Every category gets one of these.

## Difficulty

Beginner. If someone can't solve this, they need the intro workshop, and
that's fine - point them at it.

## Organizer notes

64 MB, no persistent state, fork-per-connection. Nothing to reset. If it dies,
`make restart S=pwn-cellar-door` on the challenge host.
