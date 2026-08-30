# Midnight Mountain Ave Mile — writeup

**Category:** crypto (web deployment) · **Points:** 200 · **Flag:** see
`challenge.yml`

## The story

The ghosts' annual midnight mile up Mountain Avenue was timed, for the
first time, by Poudre Tracking Systems "Trace" recorders: watch-style
wearables that record continuously, emit ordinary GPX, and carve the
recording into quarter-mile segments. PTS certified the leader's four
segments under a four-leaf Merkle tree and pushed the root to the
certified results feed. Then, mid-race, the logger stopped working: it
had flushed three quarter segments to the archive, but the finish
segment — the one that carries the finisher's bib — existed only in its
memory.

The records office publishes the three surviving quarter segments, the
certified root, and the organizers' official course file (a real GPX of
the Mountain Ave Mile route — City Park end, downhill east into Old
Town). The perpetual award goes to whoever submits a finish file that,
folded into the surviving tree, reproduces the root. The gun clock
caught the winning time — 3:43.7 — and the surviving segments caught
the leader at every quarter, but the finisher's identity is exactly
what nobody can prove. That is the secret the award hangs on.

## What the player is supposed to learn

1. **How a Merkle tree is actually built.** `leaf = CRC16(gpx bytes)`,
   `parent = CRC16(be(left) || be(right))`. The `/algorithm` page
   publishes the CRC-16/XMODEM parameters, a test vector
   (`"123456789" -> 31c3`), and a fully worked fold of `node 01` from
   the real mat files. `/results` publishes the surviving leaves and the
   root, and marks exactly what was lost.
2. **What a Merkle root actually proves.** Only that the leaves are bound
   to each other *by the hash function*. The root is exactly as strong as
   the function underneath it — and CRC-16 is a checksum, not a hash.
3. **Inclusion when you only have the root.** The office has no audit
   paths — PTS lost everything but the root. To test a candidate finish
   file you must fold it up the tree yourself; and to learn what the lost
   leaf even *was*, you exploit that every value in the tree is sixteen
   bits: fold all 65,536 candidates against the root. Exactly one
   matches. That's a Merkle proof-of-inclusion done the hard way, and
   it's the step that forces players to genuinely understand the fold.
4. **CRC is linear over GF(2).** Collision-forging is cheap and certain,
   because flipping message bit *j* moves the digest by a fixed delta
   *dⱼ* independent of the rest of the message.

## The attack

The claim endpoint (`POST /claim`) checks:

- the finish file is well-formed XML with a `<gpx>` root, ≤ 64 KiB;
- the claimed time matches the gun clock — 3:43.7, the finisher's time.
  You are claiming to *be* the finisher, not to beat one;
- **the fold**: `root' = CRC16(be(node01) || be(CRC16(be(leaf_075) ||
  be(CRC16(file)))))` must equal the certified PTS root.

That's the whole gate — the fold is the only substantive check. Bib and
name on the form are trophy-plaque flavor; PTS-Cert never saw them, which
is the office's whole problem in one sentence.
Stage 1 — **recover the lost leaf.** Download the three surviving
segments; rebuild `node01`. The finish leaf is unknown but only sixteen
bits wide, so iterate all 65,536 candidates, folding each through
`node23 = CRC16(be(leaf_075) || be(cand))` and
`root' = CRC16(be(node01) || be(node23))` until it matches the published
root. Exactly one candidate does — the true finisher's leaf hash.

Stage 2 — **forge a file with that CRC.** The office publishes the
organizers' official course GPX (`/course.gpx`), a Trace recorder is
just a GPX watch, and PTS-Cert authenticates bytes rather than
provenance — so the natural forgery is the course file itself plus a
trailing XML comment carrying your bib and a couple of free bytes (a
trailing comment after the root element is well-formed GPX). Then:

- **Brute force:** cache the CRC state of the file prefix once, then try
  all 2^16 two-byte values. Seconds. (A four-hex-digit pad gives exactly
  65,536 distinct candidates; a given base file has roughly a 63% chance
  of being reachable — loop over a couple of bibs, each reshuffles the
  target.) The solve script does exactly this.
- **Linear algebra (the elegant solve):** with init 0 and no final xor,
  CRC-16/XMODEM is affine over GF(2): the digest is a linear function of
  the message bits. Compute a handful of probe digests, derive the
  per-bit deltas, and solve directly for the pad bits instead of
  searching.

Then submit. The office folds your file in, the root comes back, and the
trophy case opens.

## Why the design is shaped this way

- **Four quarter segments = a perfect 4-leaf tree.** Small enough to verify by hand,
  deep enough that the fold means something.
- **The office publishes the fold formula** (it must, for
  interoperability) but not the recovered leaf — the 16-bit recovery
  search is the player's first "aha", the CRC forgery the second.
- **The CRC variant, node construction, and a test vector are all
  published.** Guessing checksum variants is not crypto, it's misery.
- **Failure responses itemize every failed check and echo the folded
  root**, so the challenge is debuggable end-to-end over HTTP.
- **The leaf format is honest.** A watch-style continuous recorder
  emitting GPX is exactly how real race trackers work; the mats-vs-GPX
  mismatch is gone. The proprietary part of PTS is only the
  certification scheme (the CRC tree), which is why a player-built file
  certifies just as well as a recorder's: **PTS-Cert authenticates
  bytes, never provenance.** That is the bug, worn on the challenge's
  sleeve.
- **The official course GPX is the real thing** — the actual Mountain
  Ave Mile route — served from `/course.gpx`. It gives players authentic
  geometry to forge with and gives the challenge a real-Old-Town
  anchor. (Vendored; no outbound network.)
- **The finisher's identity is the secret.** The office's only evidence
  is the root, so whatever bib the certified finish file carries becomes
  the record. The root authenticates bytes, never identity — the whole
  challenge is that lesson wearing a race bib.
- The leader's real finish file exists only in `splits.py` (it defines
  the tree) and is never served — `/segments/finish.gpx` returns 410
  Gone with a note that it never made it off the logger.

## Notes for organizers

- Deterministic content: the segment bytes are generated by `src/splits.py`
  from the vendored `src/course.gpx`, so the root and the solve are
  stable across builds; `solution/solve.sh` is the same path a player
  takes and runs in a few seconds.
- The flag arrives via the `FLAG` environment variable at boot and is
  served only from the claim-success page; nothing is templated into a
  layer.
