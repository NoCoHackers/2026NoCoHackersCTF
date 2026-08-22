# Challenge directory layout

```
challenge.yml       required   metadata + deploy config (see comments inside)
Dockerfile          required   unless x-noco.kind is `static`
compose.yml         optional   local dev convenience
src/                           your challenge source
solution/solve.sh   required   automated solve, must print the flag
solution/writeup.md required   prose explanation for organizers
handout/            optional   files players download; listed under `files:`
```

Quick start:

```sh
cp -r challenges/TEMPLATE challenges/web/my-slug
$EDITOR challenges/web/my-slug/challenge.yml
FLAG='noco{local_test}' docker compose -f challenges/web/my-slug/compose.yml up --build
tools/validate.py challenges/web/my-slug
```
