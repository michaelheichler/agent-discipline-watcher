#!/bin/sh
set -eu

[ "$#" -eq 1 ] || {
  echo "read_claude_journal.sh: requires exactly one session id" >&2
  exit 2
}

DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/resolve-python.sh"
read -r FLOOR < "$(cd "$DIR/.." && pwd)/.python-version"
PYTHON="$(adw_resolve_python "$FLOOR")"
[ -n "$PYTHON" ] || {
  echo "read_claude_journal.sh: no Python $FLOOR or newer on PATH" >&2
  exit 2
}
PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$PYTHON" "$DIR/read_claude_journal.py" "$1"
