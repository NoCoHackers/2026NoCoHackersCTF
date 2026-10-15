# I-25 Rampage - author's write-up

**Flag:** declared in `challenge.yml`

## Intended path

1. Play the endless road game; the browser posts a pickup-count summary when the
   run ends.
2. Inspect the crash request and see that it contains `pickups` counts, not a
   client-computed score.
3. Change the submitted counts. For example, `{"pickups":{"bonus":52000}}`
   earns 1,300,000 server-calculated points, exceeding the 1,296,000 seeded
   record and returning the flag.

The score is not sent directly: the server applies its own 10-point fuel and
25-point bonus values. The trust flaw is that the server accepts the client's
claim that those pickups were collected without checking which pickups spawned
or could be reached.

The browser JavaScript also ships the HMAC key used to sign submissions, so
compute a valid signature for the fabricated body, then submit it:

```sh
body='{"pickups":{"bonus":52000}}'
signature=$(printf '%s' "$body" | openssl dgst -sha256 -hmac 'i25-road-crew-dispatch-2026' | awk '{print $NF}')
curl -fsS -H 'Content-Type: application/json' -H "X-Run-Signature: $signature" --data "$body" https://i25.chal.nocohackers.com/api/crash
```

## Seed calculation

At most one pickup can be spawned every five seconds. The highest-value pickup
is 25 points. Therefore the maximum theoretical rate is
`(3600 / 5) * 25 = 18,000` points per hour. A 72-hour score is
`18,000 * 72 = 1,296,000`. The game offers a pickup opportunity every five
seconds with at most one spawn, so this bounds legitimate collection even if a
player collects every opportunity and each is a bonus.

## Difficulty estimate

Beginner; a few minutes for someone who inspects browser network traffic.

