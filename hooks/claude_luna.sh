#!/bin/sh
set -eu

[ "$#" -eq 0 ] || {
  echo "claude_luna.sh: accepts hook input on stdin and no arguments" >&2
  exit 2
}

DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/resolve-python.sh"
read -r FLOOR < "$(cd "$DIR/.." && pwd)/.python-version"
PYTHON="$(adw_resolve_python "$FLOOR")"
[ -n "$PYTHON" ] || {
  echo "claude_luna.sh: no Python $FLOOR or newer on PATH" >&2
  exit 2
}
PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}" exec "$PYTHON" "$DIR/claude_luna.py"
