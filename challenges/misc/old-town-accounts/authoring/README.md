# RK05 artifact authoring

This directory preserves the source inputs used to produce the two committed
RK05 artifacts. It is not copied into the runtime image.

- `guest/ledger/` contains the live accounting program and data installed in
  `src/master.rk`.
- `guest/handout/` contains the clue files installed in
  `handout/old-town-accounts.rk`.
- `build-handout.py` creates the forensic handout from a clean stock V4 RK05,
  installs the clue chain, overwrites removed source bytes, and performs a
  fresh-boot solve check.
- `install-flag-slots.py` installs the three fixed-width source tokens in the
  prepared live master before runtime provisioning.

The authoring scripts are retained as exact build records and expect the
original `/tmp/pdp11-spike` workspace layout, a clean `build/stock.rk`, and a
pinned OpenSIMH `pdp11` executable. They deliberately do not run as part of the
Docker build: flags are inserted only when the service copies `src/master.rk`
for a player.

The clean stock disk was rebuilt from the Utah UNIX V4 tape with the historical
`mcopy` recipe (tape offset 75, count 4000). Artifact and tape hashes, the
OpenSIMH commit, runtime instructions, and licensing are recorded in the
bundle's top-level `README.md` and handout `README.txt`.

After changing guest content, repeat the raw boundary scans in
`solution/solve.py`, update the published artifact hash, run all three
autosolves, and run `tools/test-challenge.sh` so image-layer leakage is checked
again.
