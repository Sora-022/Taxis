#!/usr/bin/env bash
# Standalone undo: no Python needed. Re-enables every app taxis disabled.
# Usage: ./restore.sh [ip[:port]] [restore-file]
set -u
DEV="${1:-${TAXIS_TV:-}}"
DIR="$HOME/.taxis/snapshots"
S=()
if [ -n "$DEV" ]; then
  case "$DEV" in *:*) ;; *) DEV="$DEV:5555";; esac
  S=(-s "$DEV")
fi
FILE="${2:-}"
if [ -z "$FILE" ]; then
  prefix="${DEV//:/_}_"
  for candidate in "$DIR"/*.restore.txt; do
    [ -f "$candidate" ] || continue
    if [ -n "$DEV" ] && [[ "$(basename "$candidate")" != "$prefix"* ]]; then continue; fi
    if [ -z "$FILE" ] || [ "$candidate" -nt "$FILE" ]; then FILE="$candidate"; fi
  done
fi
[ -f "${FILE:-}" ] || { echo "No restore file found in $DIR"; exit 1; }
if [ -n "$DEV" ]; then
  adb connect "$DEV" >/dev/null
fi
echo "Re-enabling packages from $FILE"
while read -r pkg; do
  [ -z "$pkg" ] && continue
  if [[ ! "$pkg" =~ ^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$ ]]; then
    echo "  SKIP $pkg -> invalid package name"
    continue
  fi
  out=$(adb ${S[@]+"${S[@]}"} shell pm enable "$pkg" 2>&1)
  echo "  $pkg -> $out"
done < "$FILE"
echo "Done. Reboot the Fire TV to be safe."
