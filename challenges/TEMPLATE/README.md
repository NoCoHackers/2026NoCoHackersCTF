# Challenge directory layout

```
challenge.yml             required   primary metadata + deploy config
challenge.<id>.yml         optional   another independently scored entry
Dockerfile                 required   unless x-noco.kind is `static`
compose.yml                optional   local dev convenience
src/                                  shared challenge source
solution/solve.sh          required   primary automated solve
solution/solve-<id>.sh     required   default solve for a supplemental entry
solution/writeup.md        required   shared prose explanation for organizers
handout/                   optional   files players download; listed under `files:`
```

Quick start:

```sh
cp -r challenges/TEMPLATE challenges/web/my-slug
$EDITOR challenges/web/my-slug/challenge.yml
FLAG='noco{local_test}' docker compose -f challenges/web/my-slug/compose.yml up --build
tools/validate.py challenges/web/my-slug
```

## Multiple scoreboard entries, one codebase

Add root-level manifests named `challenge.<id>.yml`, where `<id>` is lowercase
kebab-case (`uart`, `firmware-dump`, and so on). Each is a complete ctfcli
manifest with exactly one flag, but its `x-noco` block may only select an
`autosolve`; the primary `challenge.yml` owns the shared service, endpoint, and
resource limits.

```yaml
name: My Challenge: UART
# ...the normal ctfcli fields...
flags: [noco{one_unique_flag}]
x-noco:
  autosolve: solution/solve-uart.sh
```

All entries share `src/`, `handout/`, and `solution/writeup.md`. Runnable
bundles receive named `NOCO_FLAG_<ID>` environment variables; base-web also
renders `__FLAG_<ID>__` (uppercase, with hyphens changed to underscores), while
base-pwn writes `/flag/<id>.txt`. The primary
`FLAG`, `__FLAG__`, and `/flag/flag.txt` aliases remain available.
