#!/usr/bin/env bash
# Interactive, host-only backup for the identified sacrificial board.
set -euo pipefail
umask 077

SERIAL=9423D016AADE5950
KEY_DIR="$HOME/.local/share/noco-ctf-2026/keys/sacrificial-$SERIAL"
HASH_ARTIFACT=0
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
MOUNT=/run/media/bjames/NOCO_BACKUP
EXPECTED_UUID=FFEB-102B

fatal() {
    printf 'FATAL: %s\n' "$*" >&2
    exit 1
}

if [[ "${1:-}" == --hash-artifact ]]; then
    [[ $# -eq 2 ]] || fatal 'Usage: backup_sacrificial.sh --hash-artifact exact-sidecar-directory'
    HASH_ARTIFACT=1
    KEY_DIR="$2"
else
    [[ $# -le 1 ]] || fatal 'Usage: backup_sacrificial.sh [exact-prepared-bundle-directory]'
    KEY_DIR="${1:-$KEY_DIR}"
fi
[[ -t 0 && -t 2 ]] || fatal 'Run this in your own terminal; the passphrase must not enter chat or tool logs.'
for tool in gpg tar python3 openssl sha256sum mountpoint findmnt mktemp sync; do
    command -v "$tool" >/dev/null || fatal "Install $tool before creating the backup."
done
mountpoint -q "$MOUNT" || fatal "Mount the NOCO_BACKUP USB drive at $MOUNT first."
[[ "$(findmnt -n -o UUID --target "$MOUNT")" == "$EXPECTED_UUID" ]] ||
    fatal 'Wrong backup filesystem; inspect the USB identity instead of changing this guard blindly.'
[[ "$(findmnt -n -o FSTYPE --target "$MOUNT")" == exfat ]] || fatal 'Expected the prepared exFAT backup drive.'
[[ -w "$MOUNT" ]] || fatal 'The USB backup filesystem is not writable.'
[[ -d "$KEY_DIR" ]] || fatal 'Persistent sacrificial keys are missing; do not substitute disposable /tmp keys.'

# The new profile has its own exact allowlist; the eight-/37-file validators
# and their default path are unchanged. Never auto-detect or merge profiles.
PROFILE_PREFIX=""
if [[ "$HASH_ARTIFACT" -eq 1 ]]; then
    LIST=$(python3 "$SCRIPT_DIR/restore_signing_hash.py" --list-files "$KEY_DIR") ||
        fatal 'Hash artifact/journal validation failed; investigate before backing it up.'
    PROFILE_PREFIX=slot0-hash-v1-
else
    LIST=$(python3 "$SCRIPT_DIR/prepare_recovery.py" --list-files "$KEY_DIR") ||
        fatal 'Bundle validation failed; investigate before backing it up.'
fi
mapfile -t FILES <<< "$LIST"
[[ ${#FILES[@]} -gt 0 ]] || fatal 'No validated bundle members.'

OUT="$MOUNT/noco2026-sacrificial-$SERIAL-${PROFILE_PREFIX}$(date -u +%Y%m%dT%H%M%SZ).tar.gz.gpg"
[[ ! -e "$OUT" ]] || fatal 'That timestamped backup already exists; retry later rather than overwriting it.'
TEMP=$(mktemp "$MOUNT/.noco-backup-XXXXXX.gpg.partial")
trap 'rm -f -- "$TEMP"' EXIT
export GPG_TTY
GPG_TTY=$(tty)

printf 'Use the backup passphrase saved in Bitwarden. Do not paste it into chat.\n'
# Only ciphertext reaches the USB. GPG reads the passphrase from the terminal,
# not the tar stream, arguments, environment, or a passphrase file.
stream_backup() {
    if [[ "$HASH_ARTIFACT" -eq 1 ]]; then
        # The helper freezes four artifact files plus their bound journal in
        # private local staging, validates that copy, then streams five members.
        python3 "$SCRIPT_DIR/restore_signing_hash.py" --stream-artifact "$KEY_DIR"
    else
        tar -C "$KEY_DIR" -czf - -- "${FILES[@]}"
    fi
}
stream_backup |
    gpg --no-options --no-symkey-cache --pinentry-mode loopback \
        --symmetric --cipher-algo AES256 --yes --output "$TEMP"
[[ -s "$TEMP" ]] || fatal 'GPG produced no backup; do not proceed to OTP.'
sync -f "$TEMP"
# Neither replace another backup nor move inside a directory that appeared
# while the passphrase was entered. This must remain an exact file destination.
mv -nT -- "$TEMP" "$OUT"
[[ ! -e "$TEMP" ]] || fatal 'Destination appeared during encryption; existing backup was preserved.'
sync -f "$MOUNT"
printf '\nEncrypted backup created: %s\n' "$OUT"
if [[ "$HASH_ARTIFACT" -eq 1 ]]; then
    printf 'Next: restore these five files from USB. Keep the separate key archives; no OTP approval.\n'
    printf 'python3 %q --artifact-dir %q %q\n' "$SCRIPT_DIR/restore_signing_hash.py" "$KEY_DIR" "$OUT"
else
    printf 'Next: restore from USB and verify the keys and rebuilt images before any OTP programming.\n'
fi
if [[ "$HASH_ARTIFACT" -eq 0 && -f "$KEY_DIR/binding.json" ]]; then
    printf 'Expanded restore command (passphrase remains local):\n'
    printf 'python3 %q --prepared --bundle-dir %q %q\n' "$SCRIPT_DIR/restore_sacrificial.py" "$KEY_DIR" "$OUT"
fi
