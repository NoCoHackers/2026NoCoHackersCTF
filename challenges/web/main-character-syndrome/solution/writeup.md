# Main Character Syndrome - author's write-up

**Flag:** declared only in `challenge.yml`.

## Intended path

1. Open the night-watch registry. The candidate image has a known digest and a trusted, passing CI record from `feature/night-vision`. Normal descriptions fail promotion.
2. The notes say the verifier feeds both the CI record and the editable registry description to a `jq` JSON-lines reader. The description is text, not a provenance record, but JSON-looking text is parsed as one.
3. Put a single-line JSON object in the description with the displayed `digest`, `source.branch` set to `main`, and `result` set to `passed`. Request promotion again. The UI shows two parsed records and returns the flag.

The actual bug is `jq -cR 'fromjson? | select(type == "object")'` over a stream containing both trusted CI JSON and untrusted description text, followed by a branch check over *all* parsed records. This is neither shell injection nor a vulnerability in jq itself: untrusted text has been promoted to trusted evidence. The correct implementation would query the trusted CI record directly and keep the description out of the provenance input entirely.

## Unintended paths you're aware of

This challenge has no per-player state; every request submits its own description. One player's successful promotion does not unlock the flag for other visitors. The image is a fictional registry entry, not an executable container to download.

## Difficulty estimate

Beginner/intermediate, about 10-20 minutes once the JSON-lines hint is noticed.

## Anything the organizers should watch

No external dependencies at runtime. The container needs `jq` installed at build time and a runtime `FLAG` environment variable. If players stall, point them to the parsed-record count after submitting an ordinary description.
