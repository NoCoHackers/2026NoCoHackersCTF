# CTFd theme

`noco-2026` is a fork of CTFd's default `core-beta` theme, retinted to match
`theme/tokens.css` so the scoreboard and the challenges are recognisably the
same event.

Bootstrap it once:

```sh
git clone --depth 1 --branch 3.7.7 https://github.com/CTFd/CTFd /tmp/ctfd
cp -r /tmp/ctfd/CTFd/themes/core-beta deploy/scoreboard/themes/noco-2026
cd deploy/scoreboard/themes/noco-2026
# point its SCSS at our colours and system font stacks, then:
yarn install && yarn build
```

Keep the diff against upstream small - override colours and font stacks, don't
restructure templates. CTFd point releases change theme internals, and a light
touch is the difference between a ten-minute upgrade and an evening.
