#!/bin/sh
set -eu
CDPATH=

if [ "$#" -eq 2 ] && [ "$1" = "--documents" ]
then
  shift
  FLAGS="--documents"
elif [ "$#" -eq 1 ]
then
  FLAGS=""
else
  echo "read_claude_journal.sh: requires one session id, optionally after --documents" >&2
  exit 2
fi

DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/resolve-python.sh"
read -r FLOOR < "$(cd "$DIR/.." && pwd)/.python-version"
PYTHON="$(adw_resolve_python "$FLOOR")"
[ -n "$PYTHON" ] || {
  echo "read_claude_journal.sh: no Python $FLOOR or newer on PATH" >&2
  exit 2
}
PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$PYTHON" "$DIR/read_claude_journal.py" $FLAGS "$1"
