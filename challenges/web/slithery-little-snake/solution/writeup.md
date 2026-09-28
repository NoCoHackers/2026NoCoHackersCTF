# slithery little snake — organizer notes

Each browser receives a random cookie that selects its own in-memory leaderboard.
That board begins with an Old Town Ghost score of 1,000,000, so the game cannot
legitimately beat first place: the 20×20 board has only 400 cells and Snake's
client only permits scores through 3,970.

The browser submits its score to `POST /api/score`. The server checks that the
value is a non-negative integer, but does not check whether gameplay could
produce it. Intercept the request or call the endpoint directly with a score
above 1,000,000. The server ranks it first on that browser's board and returns
the runtime-injected flag. The leaderboard is per cookie, so this does not
change another player's board. All state is intentionally in memory and resets
when the service restarts.
