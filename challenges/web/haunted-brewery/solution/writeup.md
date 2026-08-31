# Haunted Brewery - author's write-up

**Flag:** declared in `challenge.yml`

## Intended path

1. `curl https://brewery.chal.nocohackers.com/robots.txt` reveals
   `Disallow: /cellar-inventory/`. The landing page hints at it in prose
   ("Staff only. Please do not go down there.") for players who don't reach
   for robots.txt first.
2. That directory index names `cask-manifest.json`.
3. The flag is the `note` field on cask 13.

Three steps, no tooling beyond curl or a browser. This is the intended
first-blood-in-under-five-minutes challenge - it exists so that everyone in
the room gets on the board early and learns the flag format.

## Unintended paths

None meaningful. Directory listing is off, so there is no shortcut past
robots.txt, but honestly a player who guesses `/cellar/` and then pokes around
gets there too. That's fine.

## Difficulty

Beginner. Expect 90% solve rate.

## Organizer notes

Static nginx, 128 MB, no state. If this one falls over, something is wrong
with the host rather than the challenge.
