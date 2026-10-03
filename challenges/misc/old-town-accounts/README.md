# Old Town Accounts

Three scored challenges share one PDP-11/45 UNIX Fourth Edition service:

1. `The Night Clerk` — recover a credential from the RK05 handout.
2. `Off the Books` — escape the clerk's restricted ledger.
3. `The Proprietor's Copy` — exploit historical uid/gid truncation to reach root.

## Local run

```sh
FLAG='noco{local_night}' \
NOCO_FLAG_LEDGER_ESCAPE='noco{local_ledger}' \
NOCO_FLAG_PROPRIETOR='noco{local_proprietor}' \
docker compose -f challenges/misc/old-town-accounts/compose.yml up --build
```

Open <http://localhost:8080>. The runtime master has fixed-width slots for all
three environment-provided flags. `gateway.py` validates and substitutes them
only after copying the master into a player's private writable directory.
Neither the image layer nor the handout contains a real flag.

## Session lifecycle

- Five emulator instances are booted at startup.
- The pool grows on demand to twenty and never auto-shrinks.
- The `Secure`/HttpOnly/SameSite `ota_sess` cookie reconnects a browser to its
  existing guest and expires after twelve hours in both browser and service.
- Only terminal input updates activity; reset is limited to once per 30 seconds.
- At capacity, the least-recently-active session idle for at least six hours is
  reclaimed. If none qualifies, the documented capacity message is returned.
- Reset keeps the browser allocation but replaces its disk from the immutable
  master. Deploys and container restarts intentionally discard all progress.

Every emulator receives a private disk and loopback-only DLI port. OpenSIMH and
the gateway run as uid 10001 under a read-only, capability-free container;
guest UNIX root is an emulated privilege and has no relationship to container
or host root. Because all emulator processes share the aggregate container, an
OpenSIMH process escape could affect other player sessions. The organizer
explicitly accepted this residual risk on 2026-10-03.

## Artifact provenance

- `src/master.rk`: SHA-256
  `508abb6f0463e7c69ebf1b85fe7e762b1bd7da88edd3c3c5a075e482bb668738`
- `handout/old-town-accounts.rk`: SHA-256
  `c9c2a5c37e544735ac0eea9c64674257a8c65c44fe829cb10cc6165b6a028fbc`
- Original Utah UNIX V4 tape: SHA-256
  `43e912bb7a5fcc5f421eac30cf87b9e01417f547b248ce5f902fad14eb87b8a2`
- OpenSIMH: clean commit `87eb7d5e96f9ce0ee6ac183e20160e5c486b0712`,
  built with `make pdp11`, stripped binary SHA-256
  `c1fd06ac4bf92fa0888f2e0d9237a146fbc30baaa047dbc2f0dcb28c54a142aa`.

The guest program/data inputs and exact artifact-authoring scripts are retained
under `authoring/`; see `authoring/README.md` for their clean-stock prerequisites.

The container is currently amd64-only because the pinned OpenSIMH executable is
committed as a reproducible build artifact. Its license is included at
`src/licenses/OpenSIMH-LICENSE.txt`. The vendored xterm.js license is at
`src/licenses/xterm.js-LICENSE.txt`, and the websockets wheel carries its
license under `src/vendor/websockets-17.1.dist-info/licenses/`. The Caldera
license and required acknowledgment for UNIX V4 redistribution are included
in both `src/licenses/Caldera-LICENSE.txt` (live image) and the handout.
Organizer approval for this redistribution and attribution was recorded on
2026-10-03.

## Tests

```sh
tools/validate.py challenges/misc/old-town-accounts
tools/test-challenge.sh challenges/misc/old-town-accounts
```

The three autosolves use only Python's standard library and independently
exercise the handout/login, ledger escape, and full root chain.
