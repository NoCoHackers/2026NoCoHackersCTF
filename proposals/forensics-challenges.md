# Forensics challenge proposals

Status: ideas only; none are implemented or approved for the event. The first
five form the recommended initial category lineup. Point values are provisional
and should be revisited once each challenge's artifacts, hints, and intended
solve path are finalized.

## Recommended initial lineup

### The Howl on College Avenue

- **Category:** `forensics`
- **Value:** 100 (beginner)
- **Kind:** `static`
- **Artifact:** Audio recording
- **Idea:** A late-night recording contains an unexplained howl beneath traffic
  and crowd noise. Players inspect its metadata and spectrogram to recover a
  message or flag.
- **Skills:** Audio metadata, Audacity, spectrogram analysis
- **Unusual needs:** Nothing unusual.

### Claw Marks in the Logs

- **Category:** `forensics`
- **Value:** 200 (easy)
- **Kind:** `static`
- **Artifact:** Web and server logs
- **Idea:** Something accessed a city system after midnight. Players identify
  the compromised account, reconstruct the request sequence, and decode a
  suspicious user-agent or query parameter.
- **Skills:** Log filtering, IP and session correlation, URL decoding
- **Unusual needs:** Nothing unusual.

### Last Call at the Haunted Pub

- **Category:** `forensics`
- **Value:** 300 (medium)
- **Kind:** `static`
- **Artifact:** Packet capture
- **Idea:** A pub's security camera stopped responding shortly before something
  escaped into the alley. Players examine DNS and HTTP traffic, reconstruct an
  uploaded image, and determine what was transmitted.
- **Skills:** Wireshark filters, protocol inspection, file extraction
- **Unusual needs:** Nothing unusual.

### Something in the Cache

- **Category:** `forensics`
- **Value:** 300 (medium)
- **Kind:** `static`
- **Artifact:** Browser profile
- **Idea:** A city employee searched for increasingly strange things before
  vanishing. Players reconstruct the activity from SQLite history, cache
  entries, downloads, and saved session data.
- **Skills:** Browser artifacts, SQLite, timestamp conversion, cache recovery
- **Unusual needs:** Nothing unusual.

### A Process Possessed

- **Category:** `forensics`
- **Value:** 400 or 500 (hard or expert)
- **Kind:** `static`
- **Artifact:** Memory dump
- **Idea:** A city workstation behaved strangely after an employee opened a
  "festival map." Players inspect processes, command history, network
  connections, and injected or deleted content to reconstruct the compromise.
- **Skills:** Volatility, process trees, memory extraction, command-line
  reconstruction
- **Unusual needs:** The handout may be large; CI and challenge-host storage
  requirements must be evaluated before implementation.

## Additional candidates

### The Missing CSU Cryptozoologist

- **Category:** `forensics`
- **Value:** 200 or 300 (easy or medium)
- **Kind:** `static`
- **Artifact:** USB filesystem image
- **Idea:** A researcher investigating sightings around Old Town disappeared.
  Their USB drive contains deleted field notes, decoy files, and a recoverable
  photograph containing the flag.
- **Skills:** Filesystem analysis, deleted-file recovery, metadata, file carving
- **Unusual needs:** Nothing beyond a moderately sized handout.

### Trail Cam 13

- **Category:** `forensics`
- **Value:** 100 (beginner)
- **Kind:** `static`
- **Artifact:** Archive of trail-camera photographs
- **Idea:** A trail camera near the Poudre captured movement overnight. Most
  images are ordinary, but one has inconsistent timestamps and concealed data.
  Steganography should remain a secondary, well-signposted step rather than a
  guessing exercise.
- **Skills:** Timeline sorting, EXIF comparison, appended-data inspection
- **Unusual needs:** Nothing unusual.

### The Trolley's Final Route

- **Category:** `forensics`
- **Value:** 300 (medium)
- **Kind:** `static`
- **Artifact:** GPS records or a simulated phone backup
- **Idea:** A restored trolley took an impossible route through Old Town.
  Players correlate locations, timestamps, and photographs to determine where
  it stopped and recover the flag from that event.
- **Skills:** SQLite, coordinate extraction, timeline correlation, timezones
- **Unusual needs:** Use wholly fictional data; do not include real personal
  location history.

### Dead Air on 90.5

- **Category:** `forensics`
- **Value:** 300 or 400 (medium or hard)
- **Kind:** `static`
- **Artifact:** Radio capture or demodulated audio
- **Idea:** A local station received an unauthorized Halloween broadcast.
  Players inspect an IQ recording or processed audio and recover embedded
  packet or tone data.
- **Skills:** Signal analysis, modulation recognition, DTMF or APRS decoding
- **Unusual needs:** Provide strong hints and a compact processed sample unless
  SDR experience is an explicit prerequisite.

### The Coroner's Polaroid

- **Category:** `forensics`
- **Value:** 300 (medium)
- **Kind:** `static`
- **Artifact:** Damaged image file
- **Idea:** A photograph recovered from an Old Town alley will not open. Players
  repair its headers, recover thumbnail data, and inspect contrasting or hidden
  image regions.
- **Skills:** Magic bytes, binary repair, thumbnail extraction, image analysis
- **Unusual needs:** Nothing unusual.

## Coverage goal

The recommended lineup provides a progression through audio, logs, network
traffic, application artifacts, and memory analysis. Each challenge should ship
as a deterministic static handout with a `solution/solve.sh` autosolve and keep
the real flag only in its manifest, following the repository's normal runtime
and validation rules.
