# I-25 Rampage

A small endless road-dodging web game. Press **Space** to start or restart, and
use **Left/Right** to switch lanes. Dodge traffic and collect fuel and bonus
tokens. Crashing automatically submits the collected pickup counts to your
personal top-three board.

The game offers one pickup opportunity every five seconds. Fuel is worth 10
points and bonus tokens 25. At the absolute maximum rate—collecting a 25-point
bonus on every opportunity—theoretical perfect-play rate is 18,000 points/hour.
The seeded score is 72 × 18,000 = **1,296,000 points**, about 72 hours of
continuous perfect collection.

The crash request is a compact event summary (`{"pickups":{"fuel":2,"bonus":1}}`)
rather than a long per-frame log. The server checks that pickup types and counts
are shaped reasonably and computes points from server-defined values, but does
not validate that a pickup existed in the game or was reachable. A fake count
of 52,000 bonus pickups scores 1,300,000, just above the seeded record. Counts
are capped at one million each and in total, so this solve remains within the
small request-size bound without large event logs.

Crash submissions now require an HMAC-SHA256 signature of the exact JSON request
body in `X-Run-Signature`. The browser holds the fixed signing key; this is an
intentional challenge weakness, not production authentication. Missing or invalid
signatures receive HTTP 403 before leaderboard changes. Browser signing uses Web
Crypto and requires HTTPS or a trustworthy localhost origin.

The solve recovers the key from the shipped JavaScript, signs a forged
run of 52,000 bonus pickups, and takes first place.

Scores are held in memory and reset with the service. Each browser receives an
opaque player cookie and has its own board. There is no account system or
persistent database.

Local smoke test:

```sh
FLAG='noco{local_test}' docker compose -f challenges/web/i-25-rampage/compose.yml up --build
# In another terminal:
TARGET=http://localhost:8080 challenges/web/i-25-rampage/solution/solve.sh
```
