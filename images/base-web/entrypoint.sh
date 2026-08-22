#!/bin/sh
# NoCo base-web entrypoint.
#
# Renders the immutable /srv/app into the tmpfs /srv/www, substituting:
#   __FLAG__           -> $FLAG
#   {{CHAL_NAME}}      -> $CHAL_NAME
#   {{CHAL_CATEGORY}}  -> $CHAL_CATEGORY
#
# Templating at runtime rather than build time is what keeps the flag out of
# the image layers, out of `docker history`, and out of the registry.
set -eu

if [ -z "${FLAG:-}" ]; then
  echo "noco: FATAL - FLAG is empty. Set it in compose or with -e FLAG=..." >&2
  exit 1
fi

case "$FLAG" in
  noco\{*\}) : ;;
  *) echo "noco: FATAL - FLAG does not match noco{...}" >&2; exit 1 ;;
esac

if ! ( : > /srv/www/.writetest ) 2>/dev/null; then
  echo "noco: FATAL - /srv/www is not writable." >&2
  echo "noco:   run with --tmpfs /srv/www (compose: tmpfs: [/srv/www])" >&2
  exit 1
fi
rm -f /srv/www/.writetest

cp -a /srv/app/. /srv/www/

# Only rewrite text files, and only ones that actually contain a token.
find /srv/www -type f \
     \( -name '*.html' -o -name '*.htm' -o -name '*.txt' -o -name '*.js' \
        -o -name '*.css' -o -name '*.json' -o -name '*.xml' -o -name '*.md' \) \
     -exec grep -lE '__FLAG__|\{\{CHAL_(NAME|CATEGORY)\}\}' {} + 2>/dev/null \
| while IFS= read -r f; do
    if sed -e "s|__FLAG__|${FLAG}|g" \
           -e "s|{{CHAL_NAME}}|${CHAL_NAME:-Untitled}|g" \
           -e "s|{{CHAL_CATEGORY}}|${CHAL_CATEGORY:-misc}|g" \
           "$f" > "$f.tmp" && mv "$f.tmp" "$f"; then
      echo "noco: templated ${f#/srv/www}"
    else
      echo "noco: FATAL - could not template $f" >&2
      exit 1
    fi
  done

# The subshell above cannot kill the parent, so verify the result directly:
# an unsubstituted token means a broken challenge and we should not serve it.
if grep -rlE '__FLAG__|\{\{CHAL_(NAME|CATEGORY)\}\}' /srv/www 2>/dev/null | head -1 | grep -q .; then
  echo "noco: FATAL - tokens survived templating:" >&2
  grep -rlE '__FLAG__|\{\{CHAL_(NAME|CATEGORY)\}\}' /srv/www 2>/dev/null | sed 's|^|noco:   |' >&2
  exit 1
fi

echo "noco: '${CHAL_NAME:-Untitled}' [${CHAL_CATEGORY:-misc}] ready on :8080"
exec "$@"
