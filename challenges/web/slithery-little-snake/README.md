# slithery little snake

A tiny vanilla-JavaScript Snake game backed by a Python standard-library HTTP
server. Each browser cookie has a separate in-memory top-three leaderboard,
seeded by an impossible high score. The browser enforces the finite board score
limit of 3,970, but the server trusts any non-negative integer sent to its score API.

Run locally from the repository root:

```sh
FLAG='noco{local_test}' docker compose -f challenges/web/slithery-little-snake/compose.yml up --build
```

Open <http://localhost:8080>. To understand the intended API flaw and solve,
see `solution/writeup.md`.
