#!/bin/sh
# NoCo base-web entrypoint.
#
# Renders the immutable /srv/app into the tmpfs /srv/www, substituting the
# primary __FLAG__ token plus named __FLAG_<ID>__ bundle tokens at runtime.
set -eu

if [ -z "${FLAG:-}" ]; then
  echo "noco: FATAL - FLAG is empty. Set it in compose or with -e FLAG=..." >&2
  exit 1
fi
case "$FLAG" in
  noco\{*\}) : ;;
  *) echo "noco: FATAL - FLAG does not match noco{...}" >&2; exit 1 ;;
esac

FLAGS_FILE=/tmp/noco-flags.$$
env | grep -E '^NOCO_FLAG_[A-Z0-9_]+=' > "$FLAGS_FILE" || :
while IFS= read -r pair; do
  value=${pair#*=}
  case "$value" in
    noco\{*\}) : ;;
    *) echo "noco: FATAL - named flag does not match noco{...}" >&2; exit 1 ;;
  esac
done < "$FLAGS_FILE"

if ! ( : > /srv/www/.writetest ) 2>/dev/null; then
  echo "noco: FATAL - /srv/www is not writable." >&2
  echo "noco:   run with --tmpfs /srv/www (compose: tmpfs: [/srv/www])" >&2
  exit 1
fi
rm -f /srv/www/.writetest
cp -a /srv/app/. /srv/www/

escape_sed() {
  printf '%s' "$1" | sed 's/[\\&|]/\\&/g'
}

# Only rewrite text files, and only ones that actually contain a token.
find /srv/www -type f \
     \( -name '*.html' -o -name '*.htm' -o -name '*.txt' -o -name '*.js' \
        -o -name '*.css' -o -name '*.json' -o -name '*.xml' -o -name '*.md' \) \
     -exec grep -lE '__FLAG(_[A-Z0-9_]+)?__|\{\{CHAL_(NAME|CATEGORY)\}\}' {} + 2>/dev/null \
| while IFS= read -r f; do
    flag=$(escape_sed "$FLAG")
    chal_name=$(escape_sed "${CHAL_NAME:-Untitled}")
    chal_category=$(escape_sed "${CHAL_CATEGORY:-misc}")
    if sed -e "s|__FLAG__|${flag}|g" \
           -e "s|{{CHAL_NAME}}|${chal_name}|g" \
           -e "s|{{CHAL_CATEGORY}}|${chal_category}|g" \
           "$f" > "$f.tmp" && mv "$f.tmp" "$f"; then
      :
    else
      echo "noco: FATAL - could not template $f" >&2
      exit 1
    fi

    while IFS= read -r pair; do
      variable=${pair%%=*}
      value=${pair#*=}
      entry_id=${variable#NOCO_FLAG_}
      token="__FLAG_${entry_id}__"
      if grep -qF "$token" "$f"; then
        replacement=$(escape_sed "$value")
        sed "s|${token}|${replacement}|g" "$f" > "$f.tmp" && mv "$f.tmp" "$f"
      fi
    done < "$FLAGS_FILE"
    echo "noco: templated ${f#/srv/www}"
  done
rm -f "$FLAGS_FILE"

# A survivor means an entry id was misspelled or its environment variable was
# omitted. Fail rather than serving a literal placeholder to players.
if grep -rlE '__FLAG(_[A-Z0-9_]+)?__|\{\{CHAL_(NAME|CATEGORY)\}\}' /srv/www 2>/dev/null \
   | head -1 | grep -q .; then
  echo "noco: FATAL - tokens survived templating:" >&2
  grep -rlE '__FLAG(_[A-Z0-9_]+)?__|\{\{CHAL_(NAME|CATEGORY)\}\}' /srv/www 2>/dev/null \
    | sed 's|^|noco:   |' >&2
  exit 1
fi

echo "noco: '${CHAL_NAME:-Untitled}' [${CHAL_CATEGORY:-misc}] ready on :8080"
exec "$@"
